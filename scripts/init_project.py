#!/usr/bin/env python3
"""Bootstrap a hyper-experiments project.

Creates:
  <root>/hyper-experiments.md      (project marker — used to auto-detect root)
  <root>/experiments/experiments.md (global research ledger)
  <root>/experiments/families/     (empty; populated by new_experiment.py)

Usage:
  python init_project.py --project-name "my-project" [--root PATH] [--description TEXT]

After running, use scripts/new_experiment.py to create the first experiment.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _lib import load_template, render_template, utcnow_iso, ROOT_MARKER


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path.cwd(),
                    help="Project root (default: current directory).")
    ap.add_argument("--project-name", required=True,
                    help="Human-readable project name.")
    ap.add_argument("--description", default="",
                    help="One-paragraph project description.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing marker / ledger if present.")
    args = ap.parse_args()

    root = args.root.resolve()
    marker = root / ROOT_MARKER
    if marker.exists() and not args.force:
        print(f"error: {marker} already exists. Use --force to overwrite.",
              file=sys.stderr)
        return 1

    root.mkdir(parents=True, exist_ok=True)
    (root / "experiments" / "families").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)

    vars_ = {
        "project_name": args.project_name,
        "description": args.description or "TODO",
        "created_at": utcnow_iso(),
    }

    marker.write_text(render_template(load_template("hyper-experiments.md"), vars_))

    ledger = root / "experiments" / "experiments.md"
    if not ledger.exists() or args.force:
        ledger.write_text(render_template(load_template("experiments.md"), vars_))

    print(f"Initialized hyper-experiments project at {root}")
    print(f"  - {ROOT_MARKER}")
    print(f"  - experiments/experiments.md")
    print(f"  - experiments/families/")
    print(f"  - tools/")
    print()
    print("Next: create an experiment with scripts/new_experiment.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
