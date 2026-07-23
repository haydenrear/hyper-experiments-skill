#!/usr/bin/env python3
"""Bootstrap a hyper-experiments project.

Creates:
  <root>/hyper-experiments.md      (project marker — used to auto-detect root)
  <root>/global-hypothesis.md      (project-level falsifiable claim)
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

from _lib import (
    DEFAULT_VARIANT,
    ROOT_MARKER,
    VALID_VARIANTS,
    load_template,
    render_template,
    utcnow_iso,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path.cwd(),
                    help="Project root (default: current directory).")
    ap.add_argument("--project-name", required=True,
                    help="Human-readable project name.")
    ap.add_argument("--description", default="",
                    help="One-paragraph project description.")
    ap.add_argument("--variant", choices=VALID_VARIANTS, default=DEFAULT_VARIANT,
                    help="Project's default variant for new experiments. "
                         "`default` = PyTorch + tensorboard scaffold; "
                         "`evolve` = OpenEvolve evolutionary loop scaffold. "
                         "Per-experiment variant can override this via "
                         "`new_experiment.py --variant ...`. Branches inherit "
                         "their parent's variant automatically.")
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
    (root / "experiments" / "baselines").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    python_exp = root / "tools" / "python_exp"
    (python_exp / "src" / "python_exp").mkdir(parents=True, exist_ok=True)

    vars_ = {
        "project_name": args.project_name,
        "description": args.description or "TODO",
        "created_at": utcnow_iso(),
        "variant": args.variant,
    }

    marker.write_text(render_template(load_template("hyper-experiments.md"), vars_))

    global_hypothesis = root / "global-hypothesis.md"
    if not global_hypothesis.exists() or args.force:
        global_hypothesis.write_text(
            render_template(load_template("global-hypothesis.md"), vars_)
        )

    ledger = root / "experiments" / "experiments.md"
    if not ledger.exists() or args.force:
        ledger.write_text(render_template(load_template("experiments.md"), vars_))

    families_index = root / "experiments" / "families" / "index.md"
    if not families_index.exists() or args.force:
        families_index.write_text(
            render_template(load_template("families-index.md"), vars_)
        )

    baselines_index = root / "experiments" / "baselines" / "index.md"
    if not baselines_index.exists() or args.force:
        baselines_index.write_text(
            render_template(load_template("baselines-index.md"), vars_)
        )

    tools_pyproject = python_exp / "pyproject.toml"
    if not tools_pyproject.exists() or args.force:
        tools_pyproject.write_text(
            render_template(load_template("tools-python-exp-pyproject.toml"), vars_)
        )
    tools_init = python_exp / "src" / "python_exp" / "__init__.py"
    if not tools_init.exists() or args.force:
        tools_init.write_text(
            render_template(load_template("tools-python-exp-init.py"), vars_)
        )
    tools_observability = python_exp / "src" / "python_exp" / "observability.py"
    if not tools_observability.exists() or args.force:
        tools_observability.write_text(
            render_template(
                load_template("tools-python-exp-observability.py"),
                vars_,
            )
        )

    project_scripts = {
        "scripts/new_experiment.py": "project-scripts-new-experiment.py",
        "scripts/branch_experiment.py": "project-scripts-branch-experiment.py",
        "scripts/run_experiments.py": "project-scripts-run-experiments.py",
    }
    for out_name, tmpl_name in project_scripts.items():
        out_path = root / out_name
        if not out_path.exists() or args.force:
            out_path.write_text(render_template(load_template(tmpl_name), vars_))
            out_path.chmod(0o755)

    print(f"Initialized hyper-experiments project at {root}")
    print(f"  default variant: {args.variant}")
    print(f"  - {ROOT_MARKER}")
    print(f"  - global-hypothesis.md          (project-level falsifiable claim)")
    print(f"  - experiments/experiments.md")
    print(f"  - experiments/families/")
    print(f"  - experiments/families/index.md (cross-family strategy)")
    print(f"  - experiments/baselines/        (cross-family baseline cache)")
    print(f"  - experiments/baselines/index.md")
    print(f"  - tools/")
    print(f"  - tools/python_exp/ (shared library, importable as `python_exp`)")
    print(f"    - default tracing, logging, native OTel metrics, and trace artifact")
    print(f"  - scripts/new_experiment.py    (project wrapper around the skill)")
    print(f"  - scripts/branch_experiment.py (project wrapper around the skill)")
    print(f"  - scripts/run_experiments.py   (project orchestrator with run_baselines() hook)")
    print()
    print("new_experiment.py and branch_experiment.py are thin wrappers that")
    print("delegate to the installed hyper-experiments skill. Edit the marked")
    print("'# add prep code (before)' / '# add templating code (after)' sections")
    print("to layer in project-specific behavior.")
    print()
    print("run_experiments.py is a self-contained orchestrator. Its run_baselines()")
    print("function is intentionally a skip-by-default stub — fill it in only when")
    print("a baseline is needed that is not already cached under experiments/baselines/")
    print("or experiments/families/<family>/baselines/.")
    print()
    print("Next: create an experiment with `python scripts/new_experiment.py`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
