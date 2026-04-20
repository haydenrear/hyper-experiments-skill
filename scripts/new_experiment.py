#!/usr/bin/env python3
"""Create a new (child) experiment under an existing hyper-experiments project.

Auto-detects the project root by walking up from the current directory until it
finds a `hyper-experiments.md` file. Pass --experiments-root to override.

Every experiment must declare parentage, a bounded counterfactual delta,
invariants, and a measurement plan. Required fields here are kept minimal so
the experiment can be scaffolded quickly; fill in the rest in plan.md and
index.md before launching.

Usage:
  python new_experiment.py \\
      --family q_schedule \\
      --title "lower lr after structure formation" \\
      --question "Does lowering LR after ckpt-12k preserve sparse structure?" \\
      --parent exp-0001 \\
      --checkpoint checkpoints/exp-0001/ckpt-step-12000.pt \\
      --delta "learning_rate: 3e-4 -> 1e-4" \\
      --invariant "dataset unchanged" \\
      --invariant "architecture unchanged" \\
      --command "python train.py --config configs/exp-0002.yaml --resume ..."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _lib import (
    allocate_experiment_id,
    bullet_list,
    find_experiment_dir,
    find_experiments_root,
    inherit_run_config,
    load_template,
    render_template,
    slugify,
    utcnow_iso,
)


RUN_CONFIG_TEMPLATE = "code-run-config.json"
RUN_CONFIG_OUT = "code/run_config.json"

SUBDIRS = ("code", "logs", "tensorboard", "checkpoints")
DATA_SUBDIRS = ("generation-scripts", "generated")
FILE_TEMPLATES = {
    "index.md": "experiment-index.md",
    "plan.md": "plan.md",
    "run.md": "run.md",
    "results.md": "results.md",
    "hypotheses.md": "hypotheses.md",
}
ARTIFACT_FILES = {
    "artifacts/AGENTS.md": "artifacts-agents.md",
    "artifacts/memory.md": "artifacts-memory.md",
}
DATA_FILES = {
    "data/manifest.md": "manifest.md",
}
CODE_FILES = {
    "code/pyproject.toml": "code-pyproject.toml",
    "code/run_experiment.py": "code-run-experiment.py",
    "code/check_regressions.py": "code-check-regressions.py",
}


def _write_run_config(*, exp_dir: Path, root: Path, parent_id, child_vars):
    """Render `code/run_config.json` for the child, inheriting from the parent
    config when one exists. Returns a list of (path, old, new) renames so the
    caller can report them."""
    template_obj = json.loads(load_template(RUN_CONFIG_TEMPLATE))

    parent_config = None
    parent_config_path = None
    if parent_id:
        parent_dir = find_experiment_dir(root, parent_id)
        if parent_dir is not None:
            candidate = parent_dir / "code" / "run_config.json"
            if candidate.exists():
                parent_config = json.loads(candidate.read_text())
                parent_config_path = candidate.relative_to(root)

    merged, renames = inherit_run_config(template_obj, parent_config, child_vars)
    (exp_dir / RUN_CONFIG_OUT).write_text(json.dumps(merged, indent=2) + "\n")
    return {"renames": renames, "parent_config_path": parent_config_path}


def _print_run_config_report(report, parent_id):
    renames = report["renames"]
    src = report["parent_config_path"]
    if src is None:
        if parent_id:
            print(f"run_config.json: parent {parent_id} had no run_config.json — "
                  f"rendered the template for this experiment instead.")
        else:
            print("run_config.json: no parent to inherit from — rendered template fresh.")
        return
    print(f"run_config.json: inherited from {src}.")
    if renames:
        print("  Name-bearing fields updated for this experiment:")
        for path, old, new in renames:
            def _trim(v):
                s = json.dumps(v, ensure_ascii=False)
                return s if len(s) <= 60 else s[:57] + "..."
            print(f"    - {path}: {_trim(old)} -> {_trim(new)}")
    else:
        print("  (no name-bearing fields needed rewriting)")
    print("  Remaining hyperparameters were inherited verbatim.")
    print("  Before launch, cross-check every inherited value against this")
    print("  experiment's counterfactual delta and update run_config.json for")
    print("  anything that is part of the declared delta.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--experiments-root", type=Path, default=None,
                    help="Project root (contains hyper-experiments.md). "
                         "Auto-detected from cwd if omitted.")
    ap.add_argument("--family", required=True,
                    help="Experiment family name (e.g. q_schedule).")
    ap.add_argument("--title", required=True,
                    help="Short human-readable title; used for the slug.")
    ap.add_argument("--question", default="",
                    help="Research question this experiment tests.")
    ap.add_argument("--parent", default=None,
                    help="Parent experiment id (e.g. exp-0001).")
    ap.add_argument("--checkpoint", default=None,
                    help="Parent checkpoint path to resume from.")
    ap.add_argument("--ancestor", default=None,
                    help="Ancestor baseline experiment id, if distinct from --parent.")
    ap.add_argument("--delta", action="append", default=[],
                    help="Counterfactual change in form 'key: old -> new'. Repeatable.")
    ap.add_argument("--invariant", action="append", default=[],
                    help="Declared invariant. Repeatable.")
    ap.add_argument("--command", default="",
                    help="Exact launch command.")
    args = ap.parse_args()

    if args.experiments_root is not None:
        root = args.experiments_root.resolve()
        if not (root / "hyper-experiments.md").exists():
            print(f"error: {root} does not contain hyper-experiments.md",
                  file=sys.stderr)
            return 1
    else:
        root = find_experiments_root(Path.cwd())
        if root is None:
            print("error: could not find hyper-experiments.md by walking up from cwd.",
                  file=sys.stderr)
            print("       run scripts/init_project.py first, or pass --experiments-root.",
                  file=sys.stderr)
            return 1

    exp_id = allocate_experiment_id(root)
    slug = slugify(args.title)
    family_dir = root / "experiments" / "families" / args.family
    family_dir.mkdir(parents=True, exist_ok=True)

    family_index = family_dir / "index.md"
    if not family_index.exists():
        family_index.write_text(render_template(
            load_template("family-index.md"),
            {"family": args.family, "created_at": utcnow_iso()},
        ))

    exp_dir = family_dir / f"{exp_id}-{slug}"
    if exp_dir.exists():
        print(f"error: {exp_dir} already exists", file=sys.stderr)
        return 1
    exp_dir.mkdir()
    for sub in SUBDIRS:
        (exp_dir / sub).mkdir()
    (exp_dir / "artifacts").mkdir()
    (exp_dir / "data").mkdir()
    for sub in DATA_SUBDIRS:
        (exp_dir / "data" / sub).mkdir()

    parent_dir_rel = "null"
    if args.parent:
        p = find_experiment_dir(root, args.parent)
        if p is not None:
            parent_dir_rel = str(p.relative_to(root))
        else:
            print(f"warning: parent {args.parent} not found under experiments/families/",
                  file=sys.stderr)

    vars_ = {
        "experiment_id": exp_id,
        "slug": slug,
        "title": args.title,
        "family": args.family,
        "status": "planned",
        "created_at": utcnow_iso(),
        "research_question": args.question or "TODO",
        "parent_experiment": args.parent or "null",
        "parent_checkpoint": args.checkpoint or "null",
        "parent_directory": parent_dir_rel,
        "ancestor_baseline": args.ancestor or "null",
        "counterfactual_delta": bullet_list(args.delta) or "- TODO",
        "invariants": bullet_list(args.invariant) or "- TODO",
        "command": args.command or "TODO",
        "branched_from": "null",
        "branched_at": "null",
        "branch_copied_files": "null",
    }

    for out_name, tmpl_name in FILE_TEMPLATES.items():
        (exp_dir / out_name).write_text(
            render_template(load_template(tmpl_name), vars_)
        )
    for out_name, tmpl_name in {**ARTIFACT_FILES, **DATA_FILES, **CODE_FILES}.items():
        (exp_dir / out_name).write_text(
            render_template(load_template(tmpl_name), vars_)
        )

    run_config_renames = _write_run_config(
        exp_dir=exp_dir, root=root, parent_id=args.parent, child_vars=vars_,
    )

    rel = exp_dir.relative_to(root)
    print(f"Created {exp_id} at {rel}")
    print()
    _print_run_config_report(run_config_renames, args.parent)
    print()
    print("Next steps:")
    print(f"  1. Fill in decision policy and measurement plan in {rel}/plan.md")
    print(f"  2. Complete {rel}/index.md (continue/stop/branch criteria, key signals)")
    print(f"  3. Add a row to experiments/experiments.md under 'Active experiments'")
    print(f"  4. Append this experiment to experiments/families/{args.family}/index.md")
    print(f"     under 'Experiments in this family' and note whether it tests")
    print(f"     an existing working theory or opens a new one")
    print(f"  5. Copy the relevant code snapshot into {rel}/code/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
