"""EyD CLI: init, id, verify-local, run (Day 2), enroll (stub for now)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .chain import LocalChain
from .identity import Identity, default_chain_path, default_identity_path


def _load_identity(path: Path | None = None) -> Identity:
    p = path or default_identity_path()
    if not p.exists():
        print(f"no identity at {p} — run `eyd init` first", file=sys.stderr)
        raise SystemExit(2)
    return Identity.load(p)


def cmd_init(args) -> int:
    p = Path(args.identity) if args.identity else default_identity_path()
    if p.exists() and not args.force:
        ident = Identity.load(p)
        print(f"identity already exists: {ident.id} ({p}) — use --force to regenerate")
        return 0
    ident = Identity.generate(kind="agent")
    ident.save(p)
    print(f"agent_id: {ident.id}")
    print(f"pubkey:   {ident.pubkey_b64}")
    print(f"saved:    {p}")
    return 0


def cmd_id(args) -> int:
    ident = _load_identity(Path(args.identity) if args.identity else None)
    print(ident.id)
    return 0


def cmd_verify_local(args) -> int:
    ident = _load_identity(Path(args.identity) if args.identity else None)
    chain_path = Path(args.chain) if args.chain else default_chain_path()
    ok, msg = LocalChain(chain_path, ident).verify()
    print(("PASS " if ok else "FAIL ") + msg)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eyd", description="EyD runtime")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="generate Ed25519 identity")
    p.add_argument("--identity", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("id", help="print agent_id")
    p.add_argument("--identity", default=None)
    p.set_defaults(fn=cmd_id)

    p = sub.add_parser("verify-local", help="walk and verify the local chain")
    p.add_argument("--identity", default=None)
    p.add_argument("--chain", default=None)
    p.set_defaults(fn=cmd_verify_local)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
