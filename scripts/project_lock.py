#!/usr/bin/env python3
"""Git-backed project lock CLI.

The lock is stored as an atomic git ref under
`refs/hyper-experiments/locks/...`, so every process using the same repository
sees the same owner. Use `run -- <command...>` for normal critical sections.

Examples:
  python scripts/project_lock.py status --root .
  python scripts/project_lock.py run --root . --name scaffold-project-state -- python scripts/new_experiment.py ...
  python scripts/project_lock.py acquire --root . --name shared-ledger
  python scripts/project_lock.py release --root . --name shared-ledger --token <token>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from _lib import (
    ProjectLockError,
    acquire_project_lock,
    find_experiments_root,
    project_lock_status,
    release_project_lock,
)


DEFAULT_LOCK_NAME = "scaffold-project-state"


def _resolve_root(raw: Path | None) -> Path:
    if raw is not None:
        return raw.resolve()
    root = find_experiments_root(Path.cwd())
    return root if root is not None else Path.cwd().resolve()


def _print_json(obj: dict) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))
    sys.stdout.flush()


def _cmd_status(args) -> int:
    root = _resolve_root(args.root)
    _print_json(project_lock_status(root, args.name))
    return 0


def _cmd_acquire(args) -> int:
    root = _resolve_root(args.root)
    lock = acquire_project_lock(
        root,
        args.name,
        timeout_seconds=args.lock_timeout,
        wait=not args.no_wait_lock,
        stale_after_seconds=args.lock_stale_after,
    )
    status = {
        "locked": True,
        "ref": lock.ref,
        "oid": lock.oid,
        "metadata": lock.metadata,
    }
    _print_json(status)
    if args.hold:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            lock.release()
    return 0


def _cmd_release(args) -> int:
    root = _resolve_root(args.root)
    status = release_project_lock(
        root,
        args.name,
        token=args.token,
        force=args.force,
    )
    _print_json(status)
    return 0


def _cmd_run(args) -> int:
    root = _resolve_root(args.root)
    if not args.command:
        raise ProjectLockError("run requires a command after --")
    with acquire_project_lock(
        root,
        args.name,
        timeout_seconds=args.lock_timeout,
        wait=not args.no_wait_lock,
        stale_after_seconds=args.lock_stale_after,
    ):
        proc = subprocess.run(args.command, cwd=args.cwd or None)
    return proc.returncode


def _add_common(sub):
    sub.add_argument("--root", type=Path, default=None,
                     help="Project root inside a git worktree. Defaults to a "
                          "hyper-experiments root if found, otherwise cwd.")
    sub.add_argument("--name", default=DEFAULT_LOCK_NAME,
                     help=f"Lock name (default: {DEFAULT_LOCK_NAME}).")


def _add_acquire_options(sub):
    sub.add_argument("--lock-timeout", type=float, default=30.0,
                     help="Seconds to wait for the lock before failing (default: 30).")
    sub.add_argument("--lock-stale-after", type=float, default=900.0,
                     help="Seconds after which a held lock may be stolen as stale (default: 900).")
    sub.add_argument("--no-wait-lock", "--fail-if-locked",
                     dest="no_wait_lock", action="store_true",
                     help="Try once and fail immediately if another process holds the lock.")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = ap.add_subparsers(dest="command_name", required=True)

    status = subparsers.add_parser("status", help="Print lock status as JSON.")
    _add_common(status)
    status.set_defaults(func=_cmd_status)

    acquire = subparsers.add_parser(
        "acquire",
        help="Acquire the lock and print owner metadata. By default the lock remains held after exit.",
    )
    _add_common(acquire)
    _add_acquire_options(acquire)
    acquire.add_argument("--hold", action="store_true",
                         help="Hold until interrupted, then release automatically.")
    acquire.set_defaults(func=_cmd_acquire)

    release = subparsers.add_parser("release", help="Release a lock by owner token.")
    _add_common(release)
    release.add_argument("--token", default=None,
                         help="Owner token printed by acquire.")
    release.add_argument("--force", action="store_true",
                         help="Release without a token after confirming the owner died.")
    release.set_defaults(func=_cmd_release)

    run = subparsers.add_parser("run", help="Run a command while holding the lock.")
    _add_common(run)
    _add_acquire_options(run)
    run.add_argument("--cwd", type=str, default=None,
                     help="Working directory for the child command.")
    run.add_argument("command", nargs=argparse.REMAINDER,
                     help="Command to run, usually after --.")
    run.set_defaults(func=_cmd_run)
    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "command", None) and args.command[:1] == ["--"]:
        args.command = args.command[1:]
    try:
        return args.func(args)
    except ProjectLockError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
