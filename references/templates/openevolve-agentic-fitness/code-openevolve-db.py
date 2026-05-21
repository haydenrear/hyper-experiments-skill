"""OpenEvolve database inspector for {{experiment_id}} — {{title}}.

Each evolve-variant experiment owns its own openevolve database under
`<exp>/logs/openevolve_output/` (pointed at by
`paths.openevolve_output` in `run_config.json`). The database is the
persisted MAP-Elites state: population, archive, per-island state,
candidate programs and their evaluator metrics. OpenEvolve snapshots
it into `checkpoint_N/` subdirectories at the `checkpoint_interval`
declared in `config.yaml`.

This script answers the boring-but-load-bearing questions about that
database without making the operator spelunk through the directory:

    uv run openevolve-db status              # paths + latest checkpoint
    uv run openevolve-db latest-checkpoint   # absolute path of highest ckpt
    uv run openevolve-db list                # all checkpoints in order

It is also imported by `branch_experiment.py` at the skill level to
discover a parent's latest checkpoint when seeding a child's
`openevolve.checkpoint_resume`.

Database policy recap (see SKILL.md > "OpenEvolve database — one per
experiment, shareable on branch"):

  * Each new experiment gets its own empty database.
  * Branched experiments default to resuming from the parent's
    latest checkpoint (the child writes new checkpoints into its
    own `logs/openevolve_output/`; "inherits" means "starts seeded
    from", not "shares files").
  * `branch_experiment.py --new-openevolve-database` opts out and
    starts the child with a fresh database.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CODE_DIR = Path(__file__).parent
RUN_CONFIG_PATH = CODE_DIR / "run_config.json"
CHECKPOINT_RE = re.compile(r"^checkpoint_(\d+)$")


def _load_run_config() -> dict:
    with RUN_CONFIG_PATH.open() as f:
        return json.load(f)


def _resolve_db_dir(run_config: dict | None = None) -> Path:
    """Resolve the database directory from `run_config.json`."""
    cfg = run_config or _load_run_config()
    rel = cfg["paths"]["openevolve_output"]
    return (CODE_DIR / rel).resolve()


def list_checkpoints(db_dir: Path) -> list[tuple[int, Path]]:
    """Return [(iteration, path), ...] sorted ascending by iteration.

    A checkpoint is any subdirectory of `db_dir` whose name matches
    `checkpoint_<N>` for some integer N. This is openevolve's own
    naming convention.
    """
    if not db_dir.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for child in db_dir.iterdir():
        if not child.is_dir():
            continue
        m = CHECKPOINT_RE.match(child.name)
        if m:
            out.append((int(m.group(1)), child))
    out.sort(key=lambda x: x[0])
    return out


def latest_checkpoint(db_dir: Path) -> Path | None:
    """Return the highest-numbered checkpoint dir, or None if empty."""
    cps = list_checkpoints(db_dir)
    return cps[-1][1] if cps else None


def _cmd_status(args) -> int:
    cfg = _load_run_config()
    db_dir = _resolve_db_dir(cfg)
    cps = list_checkpoints(db_dir)
    resume = (cfg.get("openevolve") or {}).get("checkpoint_resume")
    print(f"experiment:        {cfg.get('experiment_id')}")
    print(f"variant:           {cfg.get('variant')}")
    print(f"database dir:      {db_dir}")
    print(f"exists:            {db_dir.is_dir()}")
    print(f"checkpoint_resume: {resume!r}  "
          f"({'fresh database' if not resume else 'resuming from parent / external state'})")
    if cps:
        print(f"checkpoints:       {len(cps)} "
              f"(first={cps[0][0]}, latest={cps[-1][0]})")
        print(f"latest path:       {cps[-1][1]}")
    else:
        print("checkpoints:       (none yet — database is empty or has not been launched)")
    return 0


def _cmd_latest_checkpoint(args) -> int:
    db_dir = _resolve_db_dir()
    latest = latest_checkpoint(db_dir)
    if latest is None:
        print(f"error: no checkpoints under {db_dir}", file=sys.stderr)
        return 1
    print(latest)
    return 0


def _cmd_list(args) -> int:
    db_dir = _resolve_db_dir()
    cps = list_checkpoints(db_dir)
    if not cps:
        print(f"(no checkpoints under {db_dir})")
        return 0
    for n, path in cps:
        print(f"{n:>8}  {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Inspect this experiment's openevolve database."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Print db path + checkpoint summary.")
    sub.add_parser("latest-checkpoint",
                   help="Print absolute path of the highest-numbered checkpoint.")
    sub.add_parser("list", help="List every checkpoint in iteration order.")
    args = ap.parse_args()
    handlers = {
        "status": _cmd_status,
        "latest-checkpoint": _cmd_latest_checkpoint,
        "list": _cmd_list,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
