#!/usr/bin/env python3
"""Branch an existing experiment: deep-copy its `code/`, data generation
scripts, and `run_config.json`; stamp a new identity and branch
provenance.

Auto-detects the project root by walking up from cwd until it finds
`hyper-experiments.md`. Pass --experiments-root to override.

Use this when the child should start from the parent's actual
implementation state (custom code in `code/`, any vendored shared
library, the parent's exact `run_config.json`) rather than from
templates. For a clean counterfactual scaffolded from templates, use
`new_experiment.py` instead.

What is copied from the source:
- `code/` tree verbatim (including `vendored/` if present),
- `data/generation-scripts/`,
- `data/manifest.md`,
- `code/run_config.json` — copied verbatim from the source. Identity-
  bearing string values (`experiment_id`, `slug`, `run_name`) are then
  swept and rewritten for the child via `sweep_identity_in_json`. The
  source's config is the source of truth for hyperparameters and
  schema; we deliberately do NOT re-merge through a template, because
  template-driven structural injection silently overrode parent
  choices and caused real bugs.

What is generated fresh (from templates, with the child's identity):
- `index.md` with a Branch provenance block,
- `plan.md`, `run.md`, `results.md`, `hypotheses.md`,
- `artifacts/AGENTS.md`, `artifacts/memory.md`.

What stays empty:
- `logs/`, `tensorboard/`, `checkpoints/`, `data/generated/`.

Usage:
  python branch_experiment.py \\
      --from exp-0003 \\
      --title "drop weight decay" \\
      --question "Does removing WD hurt val loss?" \\
      --delta "weight_decay: 0.1 -> 0.0" \\
      --invariant "LR schedule unchanged" \\
      [--family q_schedule]      # defaults to source experiment's family
      [--parent exp-XXXX]        # defaults to --from
      [--checkpoint <path>]
      [--ancestor <exp-id>]
      [--command "..."]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from _lib import (
    allocate_experiment_id,
    bullet_list,
    find_experiment_dir,
    find_experiments_root,
    load_template,
    parent_slug_from_dir,
    render_template,
    slugify,
    sweep_identity_in_json,
    utcnow_iso,
)


RUN_CONFIG_OUT = "code/run_config.json"

EMPTY_SUBDIRS = ("logs", "tensorboard", "checkpoints")
FRESH_FILE_TEMPLATES = {
    "index.md": "experiment-index.md",
    "plan.md": "plan.md",
    "run.md": "run.md",
    "results.md": "results.md",
    "hypotheses.md": "hypotheses.md",
    "artifacts/AGENTS.md": "artifacts-agents.md",
    "artifacts/memory.md": "artifacts-memory.md",
}

COPIED_FROM_SOURCE = [
    "code/ (entire tree, including any vendored/ subdir)",
    "data/generation-scripts/",
    "data/manifest.md",
    "code/run_config.json (hyperparameters inherited; identity rewritten)",
]


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy `src` to `dst`, creating parents as needed. Skips if src missing."""
    if not src.exists():
        return
    shutil.copytree(src, dst)


# Build artifacts that `shutil.copytree` pulls in alongside source files.
# `__pycache__` and `*.egg-info` carry the parent's package name and stale
# bytecode; `.venv` is a per-experiment virtualenv that must be rebuilt
# against the child's pyproject. All are regenerated on first build of
# the child and should never be inherited from the parent.
#
# Top-level entries to remove first (so subsequent recursive scans don't
# descend into them — a venv contains thousands of __pycache__ dirs we
# don't want to enumerate).
_BUILD_CRUFT_TOP_LEVEL = (".venv",)
_BUILD_CRUFT_TOP_LEVEL_GLOBS = ("*.egg-info",)
# Recursive entries — scanned after top-level removals so they only find
# the child experiment's own bytecode caches, not the venv's.
_BUILD_CRUFT_RECURSIVE = ("__pycache__",)
_BUILD_CRUFT_RECURSIVE_FILES = (".DS_Store",)


def _purge_build_cruft(code_dir: Path, root: Path) -> list:
    """Remove build artifacts copied from the source `code/` tree.

    Returns the list of removed paths (relative to `root`) so the caller
    can report them. Safe to call on a code_dir that doesn't exist (no-op).

    Order matters: top-level removals run before recursive scans so that
    e.g. a `.venv` containing thousands of nested `__pycache__` dirs is
    deleted as a single tree rather than enumerated.
    """
    removed: list = []
    if not code_dir.exists():
        return removed
    for name in _BUILD_CRUFT_TOP_LEVEL:
        d = code_dir / name
        if d.is_dir():
            shutil.rmtree(d)
            removed.append(d.relative_to(root))
    for pattern in _BUILD_CRUFT_TOP_LEVEL_GLOBS:
        for d in list(code_dir.glob(pattern)):
            if d.is_dir():
                shutil.rmtree(d)
                removed.append(d.relative_to(root))
    for name in _BUILD_CRUFT_RECURSIVE:
        for d in list(code_dir.rglob(name)):
            if d.is_dir():
                shutil.rmtree(d)
                removed.append(d.relative_to(root))
    for name in _BUILD_CRUFT_RECURSIVE_FILES:
        for f in list(code_dir.rglob(name)):
            if f.is_file():
                f.unlink()
                removed.append(f.relative_to(root))
    return removed


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _rewrite_pyproject_name(
    pyproject_path: Path,
    *,
    parent_exp_id: str,
    parent_slug: str | None,
    child_exp_id: str,
    child_slug: str,
    new_description: str | None,
) -> None:
    """Rewrite the `name` (and optionally `description`) of [project].

    `name` retargeting preserves any project-specific suffix that follows
    the parent identity prefix. For example, a parent named
    `exp-0036-polynomial-grpo-overfit-shakedown-code` branched into
    `exp-0037` with slug `polynomial-grpo-gate-init-fix` becomes
    `exp-0037-polynomial-grpo-gate-init-fix-code` — the trailing `-code`
    is preserved rather than dropped.

    `description` is only rewritten when `new_description` is provided
    (i.e., the user passed `--description`). Otherwise we leave the
    inherited description alone — overwriting it with `--title` (which
    is the slug source, not paragraph-prose) was the source of repeated
    manual fixups.
    """
    if not pyproject_path.exists():
        return
    text = pyproject_path.read_text()

    parent_prefix = (
        f"{parent_exp_id}-{parent_slug}" if parent_slug else parent_exp_id
    )
    child_prefix = f"{child_exp_id}-{child_slug}"

    def _replace_name(m):
        old = m.group(2)
        if parent_prefix and old.startswith(parent_prefix):
            new = child_prefix + old[len(parent_prefix):]
        else:
            new = child_prefix
        return f'{m.group(1)}"{new}"'

    text = re.sub(
        r'(?m)^(name\s*=\s*)"([^"]*)"',
        _replace_name,
        text,
        count=1,
    )
    if new_description is not None:
        text = re.sub(
            r'(?m)^(description\s*=\s*)"[^"]*"',
            lambda m: f'{m.group(1)}"{new_description}"',
            text,
            count=1,
        )
    pyproject_path.write_text(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--experiments-root", type=Path, default=None,
                    help="Project root (contains hyper-experiments.md). "
                         "Auto-detected from cwd if omitted.")
    ap.add_argument("--from", dest="source", required=True,
                    help="Source experiment id to deep-copy (e.g. exp-0003).")
    ap.add_argument("--title", required=True,
                    help="Short human-readable title; used for the slug.")
    ap.add_argument("--family", default=None,
                    help="Target family. Defaults to the source experiment's family.")
    ap.add_argument("--question", default="",
                    help="Research question this branched experiment tests.")
    ap.add_argument("--parent", default=None,
                    help="Lineage parent id. Defaults to --from. Set if the "
                         "conceptual counterfactual parent differs from the "
                         "experiment being deep-copied.")
    ap.add_argument("--checkpoint", default=None,
                    help="Parent checkpoint path to resume from.")
    ap.add_argument("--ancestor", default=None,
                    help="Ancestor baseline experiment id, if distinct from --parent.")
    ap.add_argument("--delta", action="append", default=[],
                    help="Counterfactual change in form 'key: old -> new'. Repeatable.")
    ap.add_argument("--invariant", action="append", default=[],
                    help="Declared invariant. Repeatable.")
    ap.add_argument("--command", default="",
                    help="Exact launch command. Defaults to TODO.")
    ap.add_argument("--description", default=None,
                    help="Description for code/pyproject.toml. If omitted, the "
                         "parent's description is kept verbatim — pass this when "
                         "the child needs a distinct one-line description (e.g. "
                         "'exp-XXXX sibling: <delta>').")
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
            return 1

    source_dir = find_experiment_dir(root, args.source)
    if source_dir is None:
        print(f"error: source experiment {args.source} not found under "
              f"experiments/families/", file=sys.stderr)
        return 1

    source_family = source_dir.parent.name
    family = args.family or source_family
    parent_id = args.parent or args.source

    # Resolve the lineage parent's directory for parent_directory in index.md.
    lineage_parent_dir = find_experiment_dir(root, parent_id)
    parent_dir_rel = (
        str(lineage_parent_dir.relative_to(root)) if lineage_parent_dir else "null"
    )

    exp_id = allocate_experiment_id(root)
    slug = slugify(args.title)
    family_dir = root / "experiments" / "families" / family
    family_dir.mkdir(parents=True, exist_ok=True)

    family_index = family_dir / "index.md"
    if not family_index.exists():
        family_index.write_text(render_template(
            load_template("family-index.md"),
            {"family": family, "created_at": utcnow_iso()},
        ))

    exp_dir = family_dir / f"{exp_id}-{slug}"
    if exp_dir.exists():
        print(f"error: {exp_dir} already exists", file=sys.stderr)
        return 1
    exp_dir.mkdir()

    # 1. Deep-copy code/ (includes run_config.json, pyproject.toml, vendored/, etc.)
    _copy_tree(source_dir / "code", exp_dir / "code")
    purged_cruft = _purge_build_cruft(exp_dir / "code", root)

    # 2. Copy data/generation-scripts/ and data/manifest.md; leave generated/ empty.
    (exp_dir / "data").mkdir()
    _copy_tree(source_dir / "data" / "generation-scripts",
               exp_dir / "data" / "generation-scripts")
    (exp_dir / "data" / "generated").mkdir(exist_ok=True)
    _copy_file(source_dir / "data" / "manifest.md",
               exp_dir / "data" / "manifest.md")

    # 3. Create empty output subdirs.
    for sub in EMPTY_SUBDIRS:
        (exp_dir / sub).mkdir(exist_ok=True)

    # 4. Render fresh index.md / plan.md / run.md / results.md / hypotheses.md /
    #    artifacts/*.md with the child's identity + branch provenance.
    branched_at = utcnow_iso()
    vars_ = {
        "experiment_id": exp_id,
        "slug": slug,
        "title": args.title,
        "family": family,
        "status": "planned",
        "created_at": branched_at,
        "research_question": args.question or "TODO",
        "parent_experiment": parent_id,
        "parent_checkpoint": args.checkpoint or "null",
        "parent_directory": parent_dir_rel,
        "ancestor_baseline": args.ancestor or "null",
        "counterfactual_delta": bullet_list(args.delta) or "- TODO",
        "invariants": bullet_list(args.invariant) or "- TODO",
        "command": args.command or "TODO",
        "branched_from": args.source,
        "branched_at": branched_at,
        "branch_copied_files": "\n  - " + "\n  - ".join(COPIED_FROM_SOURCE),
    }

    (exp_dir / "artifacts").mkdir(exist_ok=True)
    for out_name, tmpl_name in FRESH_FILE_TEMPLATES.items():
        (exp_dir / out_name).write_text(
            render_template(load_template(tmpl_name), vars_)
        )

    # 5. Rewrite name-bearing slots in the copied code/pyproject.toml.
    parent_slug = parent_slug_from_dir(source_dir.name)
    _rewrite_pyproject_name(
        exp_dir / "code" / "pyproject.toml",
        parent_exp_id=args.source,
        parent_slug=parent_slug,
        child_exp_id=exp_id,
        child_slug=slug,
        new_description=args.description,
    )

    # 6. Sweep every JSON file under code/ for identity-bearing keys
    #    (experiment_id, slug, run_name). This includes run_config.json
    #    itself: we deliberately do NOT re-merge it through a template.
    #    The source's config is the source of truth for hyperparameters,
    #    architecture, and any project-specific schema; injecting fields
    #    from a generic template silently overrides the parent's choices
    #    and was a real footgun (see commit history). Identity sweep
    #    only changes name-bearing string values, never structural keys.
    source_config_path = source_dir / "code" / "run_config.json"
    parent_identity = (args.source, parent_slug)
    run_config_renames: list = []
    extra_json_changes: dict = {}
    code_dir = exp_dir / "code"
    if code_dir.exists():
        for json_path in sorted(code_dir.rglob("*.json")):
            try:
                changed = sweep_identity_in_json(json_path, vars_, parent_identity)
            except json.JSONDecodeError:
                continue
            if not changed:
                continue
            if json_path == exp_dir / RUN_CONFIG_OUT:
                run_config_renames = changed
            else:
                extra_json_changes[json_path.relative_to(exp_dir)] = changed

    rel = exp_dir.relative_to(root)
    print(f"Branched {args.source} -> {exp_id} at {rel}")
    print(f"  branched_at: {branched_at}")
    print(f"  family: {family}" + (" (inherited from source)" if args.family is None else ""))
    print(f"  lineage parent: {parent_id}"
          + (" (== source)" if parent_id == args.source else ""))
    print()
    print("Copied from source:")
    for item in COPIED_FROM_SOURCE:
        print(f"  - {item}")
    print()
    if source_config_path.exists():
        print(f"run_config.json: copied verbatim from {source_config_path.relative_to(root)}.")
        if run_config_renames:
            print("  Identity-bearing fields swept:")
            for path, old, new in run_config_renames:
                def _trim(v):
                    s = json.dumps(v, ensure_ascii=False)
                    return s if len(s) <= 60 else s[:57] + "..."
                print(f"    - {path}: {_trim(old)} -> {_trim(new)}")
        else:
            print("  (no identity-bearing fields needed rewriting)")
        print("  All hyperparameters inherited verbatim from source.")
    else:
        print("run_config.json: source had none — child has none either.")
    if purged_cruft:
        print()
        print("Purged build artifacts copied from source code/ tree:")
        for path in purged_cruft:
            print(f"  - {path}")
    if extra_json_changes:
        print()
        print("Identity rewritten in additional code/ JSON files:")
        for path, changes in extra_json_changes.items():
            print(f"  {path}:")
            for dotted, old, new in changes:
                def _trim(v):
                    s = json.dumps(v, ensure_ascii=False)
                    return s if len(s) <= 60 else s[:57] + "..."
                print(f"    - {dotted}: {_trim(old)} -> {_trim(new)}")
    print()
    print("Reminders before launch:")
    print(f"  1. Update run_config.json for every hyperparameter listed in the")
    print(f"     counterfactual delta — inherited values are the SOURCE's choices,")
    print(f"     not this experiment's counterfactual.")
    print(f"  2. Review code/run_experiment.py and code/check_regressions.py —")
    print(f"     their module docstrings may still reference {args.source}'s")
    print(f"     identity; update to {exp_id} where the identity matters.")
    print(f"  3. Chain of custody: if code/vendored/ was copied from the source,")
    print(f"     it captures the SOURCE's freeze, not this experiment's. Re-run")
    print(f"     the freeze procedure (see references/chain-of-custody.md) and")
    print(f"     fill in {rel}/run.md's Freeze block before launch.")
    print(f"  4. Complete {rel}/plan.md and {rel}/index.md (decision policy,")
    print(f"     key signals), then add a row to experiments/experiments.md")
    print(f"     and experiments/families/{family}/index.md.")
    print()
    print("Git discipline (see SKILL.md > 'Git discipline'):")
    print(f"  * Commit the branched scaffold now so the branch point is in the log:")
    print(f"      git add {rel}/")
    print(f"      git commit -m \"[{exp_id}] scaffold: branched from {args.source}\"")
    print(f"  * After the freeze procedure and before launch, make the")
    print(f"    mandatory pre-launch commit:")
    print(f"      git commit -m \"[{exp_id}] freeze: scaffold + vendored tools\"")
    print(f"  * After the experiment finishes and the ledger / strategy indexes")
    print(f"    are updated, make the mandatory post-finish commit:")
    print(f"      git commit -m \"[{exp_id}] complete: <one-line finding>\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
