"""EyD CLI: init, id, enroll, verify-local, run."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .chain import LocalChain
from .identity import Identity, default_chain_path, default_identity_path
from .reporter import Reporter


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


def cmd_enroll(args) -> int:
    ident = _load_identity(Path(args.identity) if args.identity else None)
    reporter = Reporter(args.clearinghouse,
                        queue_path=default_chain_path().parent / "queue.jsonl")
    status, body = reporter.enroll(ident)
    flushed = reporter.flush_queue()
    print(f"enroll: {status} {body}" + (f" (flushed {flushed} queued)" if flushed else ""))
    return 0 if status == 200 else 1


def cmd_run(args) -> int:
    """Launcher mode (§3.1): start the agent with EyD identity in its env.

    The agent is not modified and does not learn EyD exists from its own
    output; EyD's Dispatcher is what its tools route through when the
    hosting framework points at EyD (agent-demo shows the pattern).
    """
    ident = _load_identity(Path(args.identity) if args.identity else None)
    if args.clearinghouse:
        Reporter(args.clearinghouse).enroll(ident)
    env = {**os.environ, "EYD_AGENT_ID": ident.id,
           "EYD_CLEARINGHOUSE": args.clearinghouse or "",
           "EYD_IDENTITY": str(Path(args.identity) if args.identity else default_identity_path())}
    if not args.command:
        print("usage: eyd run [--clearinghouse URL] -- <agent command>", file=sys.stderr)
        return 2
    print(f"eyd: agent {ident.id} -> {' '.join(args.command)}", file=sys.stderr)
    return subprocess.call(args.command, env=env)


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

    p = sub.add_parser("enroll", help="enroll with a clearinghouse")
    p.add_argument("--identity", default=None)
    p.add_argument("--clearinghouse", default="http://127.0.0.1:8787")
    p.set_defaults(fn=cmd_enroll)

    p = sub.add_parser("run", help="launcher mode: run an agent command under EyD")
    p.add_argument("--identity", default=None)
    p.add_argument("--clearinghouse", default="http://127.0.0.1:8787")
    p.add_argument("command", nargs=argparse.REMAINDER,
                   help="agent command (after --)")
    p.set_defaults(fn=cmd_run)

    args = parser.parse_args(argv)
    if getattr(args, "command", None) and args.command[:1] == ["--"]:
        args.command = args.command[1:]
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
