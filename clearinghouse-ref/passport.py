"""AI Passport v1 verification + Revocation Check v1 caller.

Implements the gateway check (AI Passport v1 §1, §3-§7, §9.1, §10) and
the caller-side interpretation of revocation answers (Revocation Check
v1 §5, §6) for the clearinghouse. Fail-closed throughout: anything
wrong or unknown denies.

Interoperability is measured against ServiceNow's published test
vectors, run unmodified (see passport-interop/). Canonicalization is
RFC 8785 via eyd.canonical; signatures are ES256 detached JWS verified
over the received protected header plus the canonical form of the
Passport without `signatures`.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from eyd.canonical import canonical_bytes

REQUIRED = ["schema_version", "subject", "subject_type", "issuer",
            "revision", "valid_from", "valid_to", "status", "bindings",
            "business_context"]
SUBJECT_TYPES = ("agent", "harness", "tool_server", "model_endpoint")
REJECTED_HEADER = ("b64", "crit")
RESOLVERS = ("authentication", "configured_mapping")
SAFE_INT = 2**53 - 1
SKEW_SECONDS = 300          # 01 §14: at most 5 minutes
IRREVERSIBLE_REUSE = 5      # 02 §5.3 where the organisation sets no limit
ABSOLUTE_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s#]+$")


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate member {k!r}")
        out[k] = v
    return out


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")


def strict_json(text: str):
    """Parse JSON rejecting duplicate members (RFC 7493 §2.3) and the
    NaN / Infinity literals Python would otherwise accept."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    return json.loads(text, object_pairs_hook=_no_duplicates,
                      parse_constant=_no_constant)


def _bad_text(s: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF or 0xFDD0 <= ord(c) <= 0xFDEF
               or ord(c) & 0xFFFE == 0xFFFE for c in s)


def not_ijson(v: Any) -> bool:
    """True if v holds what RFC 7493 forbids (01 §4)."""
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, int):
        return not -SAFE_INT <= v <= SAFE_INT
    if isinstance(v, float):
        return v != v or v in (float("inf"), float("-inf"))
    if isinstance(v, str):
        return _bad_text(v)
    if isinstance(v, list):
        return any(not_ijson(x) for x in v)
    if isinstance(v, dict):
        return any(_bad_text(k) or not_ijson(x) for k, x in v.items())
    return True


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def origin(url):
    """RFC 6454 origin (scheme, host, port) of an absolute URL, or None."""
    from urllib.parse import urlsplit
    if not isinstance(url, str):
        return None
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return None
    if not u.scheme or not u.hostname:
        return None
    scheme = u.scheme.lower()
    return scheme, u.hostname, port or {"https": 443, "http": 80}.get(scheme)


# --- trust anchors (01 §9.1) ----------------------------------------------


def anchor_for(anchors: dict, issuer):
    """The trust anchor configured for this exact issuer string."""
    return anchors.get(issuer) if isinstance(issuer, str) else None


def accepts(anchor: dict, authority, tenant) -> bool:
    """Whether the anchor accepts this authority (and tenant). Absent
    `authorities` accepts every authority and tenant."""
    if "authorities" not in anchor:
        return True
    for a in anchor["authorities"]:
        if a == authority:
            return True
        if isinstance(a, dict) and a.get("id") == authority and tenant in a.get("tenants", []):
            return True
    return False


def _fell_through(answer) -> bool:
    """Only 200, subject null, reason unresolved_identity lets a verifier
    pass to a lower-ranked issuer (01 §9.1, 02 §5.5)."""
    if not isinstance(answer, dict) or answer.get("status") != 200:
        return False
    body = answer.get("body")
    return isinstance(body, dict) and body.get("subject") is None \
        and body.get("reason") == "unresolved_identity"


def issuer_accepted(anchors: dict, issuer, authority, inp: dict, tenant=None) -> bool:
    accepting = [i for i, a in anchors.items() if accepts(a, authority, tenant)]
    if issuer not in accepting:
        return False
    if len(accepting) == 1:
        return True
    rank = inp.get("issuer_rank") or []
    if any(i not in rank for i in accepting):
        return False  # shared and not ranked: deny
    higher = [i for i in rank[:rank.index(issuer)] if i in accepting]
    answers = inp.get("higher_ranked_answers") or {}
    return all(_fell_through(answers.get(i)) for i in higher)


# --- member shape checks ----------------------------------------------------


def _names_party(obj, ref) -> bool:
    """An object with neither its reference nor a `name` reads as absent
    (01 §8.3, §8.5)."""
    return isinstance(obj, dict) and any(
        isinstance(obj.get(m), str) and obj[m] for m in (ref, "name"))


def has_manager(bc) -> bool:
    """`accountable` names at least one manager (01 §8.5)."""
    acc = bc.get("accountable") if isinstance(bc, dict) else None
    return isinstance(acc, list) and any(
        _names_party(e, "principal") and e.get("role") == "manager" for e in acc)


def binding_ok(b) -> bool:
    """01 §3.3 entry shape: authority object with id (absolute URI) and/or
    non-empty name; non-empty identifier."""
    if not isinstance(b, dict) or not isinstance(b.get("authority"), dict):
        return False
    a, ident = b["authority"], b.get("identifier")
    if not isinstance(ident, str) or not ident:
        return False
    if any(m in a and not (isinstance(a[m], str) and a[m]) for m in ("id", "name")):
        return False
    if "id" not in a and "name" not in a:
        return False
    return "id" not in a or bool(ABSOLUTE_URI.match(a["id"]))


def binding_pair(b):
    """The (authority, identifier) a binding attributes: only
    `authority.id`, never `name` or `type` (01 §3.3)."""
    a = b.get("authority") if isinstance(b, dict) else None
    if not isinstance(a, dict) or "id" not in a:
        return None
    return {"authority": a["id"], "identifier": b.get("identifier")}


def parent_ok(p) -> bool:
    """01 §3.4: absent or null names none; otherwise subject + same issuer."""
    par = p.get("parent")
    return par is None or (isinstance(par, dict) and isinstance(par.get("subject"), str)
                           and par.get("issuer") == p["issuer"])


def revocation_uri_ok(uri, issuer, anchor) -> bool:
    """01 §9.1: https on the issuer's origin, or a configured responder."""
    o = origin(uri)
    if o is None:
        return False
    if o[0] == "https" and o == origin(issuer):
        return True
    return o in [origin(r) for r in anchor.get("responders", [])]


# --- Revocation Check caller (02 §5, §6) -------------------------------------


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _valid_answer(body) -> bool:
    """02 §5.1: every REQUIRED member, of its type."""
    if not isinstance(body, dict) or any(m not in body for m in
            ("subject", "revoked", "revoked_scopes", "min_required_revision",
             "evaluated_at", "state_version")):
        return False  # absent `revoked` is not false
    if not (body["subject"] is None or isinstance(body["subject"], str)) \
            or not _count(body["state_version"]) or not isinstance(body["evaluated_at"], str):
        return False
    try:
        _ts(body["evaluated_at"])
    except ValueError:
        return False
    return True


def _max_age(cache_control):
    """Freshness lifetime from Cache-Control; first max-age counts;
    None if absent or unparseable (02 §5.3)."""
    if not isinstance(cache_control, str):
        return None
    life = None
    for d in (x.strip().lower() for x in cache_control.split(",") if x.strip()):
        if d in ("no-store", "no-cache"):
            return 0
        if d.startswith("max-age=") and life is None:
            if not d[8:].isdigit():
                return None
            life = int(d[8:])
    return life


def interpret_revocation(received, held=None, previous=None, asked=None,
                         now=None, previous_expired=False) -> str:
    """-> 'proceed' | 'deny' | 'refetch' (02 §5, §6).

    `held` = {subject, revision} of the Passport held; `asked` = the
    request's {subject} when asked by subject; `now` = caller clock.
    """
    if "error" in received or received.get("status") != 200:
        return "deny"  # listed or not, a timeout / non-200 denies
    body = received.get("body")
    if "body_text" in received:
        try:
            body = strict_json(received["body_text"])
        except ValueError:
            return "deny"
    if not _valid_answer(body):
        return "deny"
    mr = body["min_required_revision"]
    if not _count(mr):
        return "deny"  # 02 §5.6
    if received.get("cache_expired"):
        return "deny"  # 02 §5.3
    if "headers" in received or received.get("reused"):
        hdrs = {k.lower(): v for k, v in (received.get("headers") or {}).items()}
        life = _max_age(hdrs.get("cache-control"))
        if received.get("reused") and life is None:
            return "deny"  # not reusable without a lifetime
        age = hdrs.get("age")
        if life is None and age is not None and str(age) != "0":
            return "deny"  # applied once only if Age is 0
        if life is not None and age is not None and (not str(age).isdigit() or int(age) >= life):
            return "deny"  # stale on arrival
        if now is not None and (_ts(now) - _ts(body["evaluated_at"])).total_seconds() > (life or 0) + SKEW_SECONDS:
            return "deny"  # evaluated_at too old
        if received.get("reused") and received.get("irreversible") and (
                now is None or (_ts(now) - _ts(body["evaluated_at"])).total_seconds() > IRREVERSIBLE_REUSE):
            return "deny"
    if previous and body["subject"] == previous["subject"]:
        if body["state_version"] < previous["state_version"]:
            if previous_expired:
                return "deny"  # discarded, and nothing current
            body = previous  # discard the older answer (02 §5.4)
        elif body["state_version"] == previous["state_version"] and not previous_expired:
            body = dict(body,  # the more restrictive reading wins
                        revoked=body["revoked"] is not False or previous["revoked"] is not False,
                        min_required_revision=max(mr, previous["min_required_revision"]),
                        revoked_scopes=list(previous["revoked_scopes"]) + list(body["revoked_scopes"]))
    if body["subject"] is None:
        return "deny"  # unresolved / ambiguous / binding_revoked
    if asked and "subject" in asked and body["subject"] != asked["subject"]:
        return "deny"  # not the subject asked about
    if held and "issuer" in held and "issuer" in received and received["issuer"] != held["issuer"]:
        return "deny"  # another issuer's responder answered (02 §3.1)
    if held and body["subject"] != held["subject"]:
        return "deny"  # 02 §3.1 subject mismatch
    if body["revoked"] is not False:
        return "deny"  # only the literal false proceeds (02 §5.1)
    if not isinstance(body["revoked_scopes"], list) or body["revoked_scopes"]:
        return "deny"  # 02 §6: this version defines no entry type
    if held is not None and held["revision"] < body["min_required_revision"]:
        return "refetch"  # 02 §5.6: fetch the current Passport
    return "proceed"


# --- Passport verifier (01 §1, §3-§7, §9.1, §10) ------------------------------


def _typ_ok(hdr) -> bool:
    """`typ` absent, or ai-passport+jws / application forms / JOSE,
    case-insensitive (01 §4)."""
    if "typ" not in hdr:
        return True
    t = hdr["typ"]
    return isinstance(t, str) and t.lower() in (
        "ai-passport+jws", "application/ai-passport+jws", "jose", "application/jose")


def _es256_verify(key_jwk: dict, msg: bytes, sig: bytes) -> bool:
    try:
        numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(b64u_dec(key_jwk["x"]), "big"),
            int.from_bytes(b64u_dec(key_jwk["y"]), "big"), ec.SECP256R1())
        if len(sig) != 64:
            return False
        dss = utils.encode_dss_signature(int.from_bytes(sig[:32], "big"),
                                         int.from_bytes(sig[32:], "big"))
        numbers.public_key().verify(dss, msg, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return False


def verify_passport(inp: dict, jwks: dict | None = None, issuer: str | None = None):
    """-> (outcome, step): accept | reject | deny | refetch.

    `inp` carries the Passport (`passport` or `passport_text`), `now`,
    optional `presenter`, `refetched`, `trust_anchors`, `issuer_rank`,
    `higher_ranked_answers`, and the `revocation` answer received. With
    no `trust_anchors`, the verifier trusts the single configured
    `issuer` + `jwks` (01 §9.1)."""
    try:
        p = strict_json(inp["passport_text"]) if "passport_text" in inp else inp["passport"]
    except (ValueError, KeyError, TypeError):
        return "reject", "signature"
    if not isinstance(p, dict) or not_ijson(p):
        return "reject", "signature"
    sigs = p.get("signatures")
    if not isinstance(sigs, list) or len(sigs) != 1 or not isinstance(sigs[0], dict):
        return "reject", "signature"  # exactly one signature
    try:
        hdr = strict_json(b64u_dec(sigs[0]["protected"]).decode("utf-8"))
        sig = b64u_dec(sigs[0]["signature"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        return "reject", "signature"
    if not isinstance(hdr, dict) or not_ijson(hdr) \
            or any(m in hdr for m in REJECTED_HEADER) or not _typ_ok(hdr):
        return "reject", "signature"
    anchors = inp.get("trust_anchors") or {issuer: {"jwks": jwks}}
    anchor = anchor_for(anchors, p.get("issuer"))
    if anchor is None:
        return "reject", "signature"  # no anchor for this issuer
    keys = {k.get("kid"): k for k in anchor["jwks"]["keys"]}
    key = keys.get(hdr.get("kid"))
    if key is None or hdr.get("alg") != key.get("alg") or hdr.get("alg") != "ES256":
        return "reject", "signature"
    unsigned = {k: v for k, v in p.items() if k != "signatures"}
    msg = (sigs[0]["protected"] + "." + b64u(canonical_bytes(unsigned))).encode()
    if not _es256_verify(key, msg, sig):
        return "reject", "signature"
    if any(m not in p for m in REQUIRED):
        return "reject", "members"
    if p["schema_version"] != "1" or p["subject_type"] not in SUBJECT_TYPES \
            or p.get("issuance_class") not in (None, "owned", "proxy"):
        return "reject", "members"  # absent or null issuance_class is unknown, not wrong
    if not has_manager(p["business_context"]):
        return "reject", "members"
    if not isinstance(p["bindings"], list) or not all(binding_ok(b) for b in p["bindings"]):
        return "reject", "members"
    try:
        now = _ts(inp["now"])
        if not _ts(p["valid_from"]) <= now <= _ts(p["valid_to"]):
            return "reject", "validity"
    except (ValueError, TypeError, KeyError):
        return "reject", "validity"
    refetched = bool(inp.get("refetched") or inp.get("fetched_by_presenter_identity"))
    pres = inp.get("presenter")
    pairs = [binding_pair(b) for b in p["bindings"]]
    if pres:
        if pres.get("authenticated", True) is not True:
            return "deny", "bindings"  # retrieval is not authentication
        if pres.get("resolved_by", "authentication") not in RESOLVERS:
            return "deny", "bindings"  # never from the presenter's own value
        if {"authority": pres.get("authority"), "identifier": pres.get("identifier")} not in pairs:
            return ("deny" if refetched else "refetch"), "bindings"
        if not issuer_accepted(anchors, p["issuer"], pres.get("authority"), inp,
                               pres.get("tenant")):
            return "deny", "bindings"  # not this issuer's to bind
    if not parent_ok(p):
        return "deny", "parent"  # treated as revoked (01 §3.4)
    rc = p["status"].get("revocation_check") if isinstance(p["status"], dict) else None
    if not isinstance(rc, dict) or not revocation_uri_ok(rc.get("uri"), p["issuer"], anchor):
        return "deny", "status"  # treated as revoked (01 §7, §9.1)
    got = interpret_revocation(inp["revocation"],
                               held={"subject": p["subject"], "revision": p["revision"]})
    if got == "refetch" and refetched:
        got = "deny"  # one refetch per verification (01 §10)
    return {"proceed": "accept", "deny": "deny", "refetch": "refetch"}[got], "revocation"


def check_passport_live(passport: dict, anchors: dict, *, presenter=None,
                        http_get: Callable, fetch_passport: Callable | None = None,
                        now: str, refetched: bool = False):
    """The clearinghouse's live gateway check: verify the Passport and
    ask its revocation responder, following one refetch (01 §10).

    `http_get(url) -> {"status", "body", "headers"?} | {"error": ...}`;
    `fetch_passport(authority, identifier) -> passport dict` retrieves
    the current Passport by the presenter's pair after a refetch."""
    issuer = passport.get("issuer") if isinstance(passport, dict) else None
    anchor = anchor_for(anchors, issuer)
    revocation = {"error": "timeout"}
    rc = None
    if isinstance(passport, dict) and isinstance(passport.get("status"), dict):
        rc = passport["status"].get("revocation_check")
    if isinstance(rc, dict) and isinstance(rc.get("uri"), str) and anchor is not None:
        url = rc["uri"].replace("{subject}", quote(str(passport.get("subject", "")), safe=""))
        revocation = http_get(url)
    inp = {"passport": passport, "now": now, "revocation": revocation,
           "trust_anchors": anchors, "refetched": refetched}
    if presenter:
        inp["presenter"] = presenter
    jwks = anchor["jwks"] if anchor else None
    outcome, step = verify_passport(inp, jwks, issuer)
    if outcome == "refetch" and not refetched and fetch_passport and presenter:
        current = fetch_passport(presenter.get("authority"), presenter.get("identifier"))
        if current:
            return check_passport_live(current, anchors, presenter=presenter,
                                       http_get=http_get, fetch_passport=fetch_passport,
                                       now=now, refetched=True)
        return "deny", step
    if outcome == "refetch" and refetched:
        return "deny", step
    return outcome, step
