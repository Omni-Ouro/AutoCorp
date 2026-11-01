# AI Passport interoperability (EyD)

EyD interoperates with AI Passport: the PoT Clearinghouse reads Passports
as an identity credential alongside EyD's own action records (see
[AI_PASSPORT.md](../AI_PASSPORT.md) for the acceptance policy). This folder
holds the evidence that our Passport check — [clearinghouse/passport.py](../clearinghouse/passport.py) —
implements the spec as written by its authors: we run ServiceNow's own
published test vectors against it, unmodified.

- `vectors/` — ServiceNow's test vectors (`passport-verification.json`,
  `revocation-check.json`, `jwks.json`), copied verbatim from
  [github.com/ServiceNow/ai-passport](https://github.com/ServiceNow/ai-passport)
  at commit `ae3134d407156a7a91e0cbdea5ad26fa762d2e7d`. Code and test data
  there are Apache-2.0 (see [LICENSE](LICENSE)); the specifications are
  Community Specification License 1.0. Never trust the vector key `k1`
  outside tests — the private half is held by the spec maintainers.
- [adapter.py](adapter.py) — connects our verifier and revocation caller
  to the upstream suite's runner protocol (one JSON request per line).

## Running

With the upstream suite checked out next to this repo:

```bash
python ../ai-passport/conformance/run.py --role verifier \
    --adapter "python passport-interop/adapter.py" --name "EyD clearinghouse"
python ../ai-passport/conformance/run.py --role caller \
    --adapter "python passport-interop/adapter.py" --name "EyD clearinghouse"
```

The verifier vectors (81) and the caller-side revocation vectors
(41 of the 74 revocation cases) also run in-repo, without the
upstream checkout:

```bash
python -m pytest tests/test_passport_interop.py
```

The remaining 33 revocation cases are responder-side — the issuer
interface, out of scope for the clearinghouse; EyD's demo issuer is
checked with the runner's live responder checks instead (below).

The responder role is an issuer-side interface and out of scope for the
clearinghouse; EyD's demo issuer answers by subject only and is checked
with the runner's live checks (`--role responder --url ...`).

Validated 2026-10-27: verifier 81/81 and caller 74/74 against upstream,
and the demo issuer's revocation endpoint passes the suite's live
responder checks 8/8 (`--role responder --url http://127.0.0.1:8010/revocation`).
