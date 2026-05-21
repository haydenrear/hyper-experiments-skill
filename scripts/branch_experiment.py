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
- `code/` tree (including `vendored/` if present), with source-id
  text references retargeted to the child,
- `data/generation-scripts/`,
- `data/manifest.md`,
- `code/run_config.json` — copied from the source and retargeted by the
  same plain text search/replace as the rest of the copied tree. The
  source's config remains the source of truth for hyperparameters and
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
import os
import re
import shutil
import sys
from pathlib import Path

from _lib import (
    OPENEVOLVE_VARIANTS,
    ProjectLockError,
    acquire_project_lock,
    allocate_experiment_id,
    bullet_list,
    experiment_variant_from_run_config,
    find_experiment_dir,
    find_experiments_root,
    load_template,
    openevolve_latest_checkpoint,
    parent_slug_from_dir,
    print_vendoring_provenance,
    render_template,
    rewrite_branch_identity_in_text_files,
    slugify,
    utcnow_iso,
    verify_or_fix_branched_python_exp,
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
    "code/ (entire tree, including any vendored/ subdir; source ids retargeted)",
    "data/generation-scripts/",
    "data/manifest.md (source ids retargeted)",
    "code/run_config.json (hyperparameters inherited; identity/source ids rewritten)",
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
# `tensorboard/` and PyTorch-Lightning's `lightning_logs/` are run output
# from the parent. They never belong inside `code/`, but if a previous
# misconfiguration wrote them there they must not be carried into the
# branched child — every child writes its own event stream into
# `<exp>/tensorboard/`, and inheriting parent events silently merges two
# runs in TensorBoard.
#
# Top-level entries to remove first (so subsequent recursive scans don't
# descend into them — a venv contains thousands of __pycache__ dirs we
# don't want to enumerate).
_BUILD_CRUFT_TOP_LEVEL = (".venv",)
_BUILD_CRUFT_TOP_LEVEL_GLOBS = ("*.egg-info",)
# Recursive entries — scanned after top-level removals so they only find
# the child experiment's own bytecode caches, not the venv's.
_BUILD_CRUFT_RECURSIVE = ("__pycache__", "tensorboard", "lightning_logs")
_BUILD_CRUFT_RECURSIVE_FILES = (".DS_Store",)
_BUILD_CRUFT_RECURSIVE_FILE_GLOBS = ("events.out.tfevents.*",)


def _rmtree_with_retry(path: Path, max_attempts: int = 4) -> None:
    """`shutil.rmtree` with retry — macOS occasionally fails with "directory
    not empty" on deeply-nested venvs (torch in particular) when bulk-
    deleting fast. The races resolve within a few hundred ms, so a small
    retry loop is enough.
    """
    import time
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            shutil.rmtree(path)
            return
        except OSError as e:
            last_err = e
            time.sleep(0.2 * (attempt + 1))
    if last_err is not None:
        raise last_err


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
            _rmtree_with_retry(d)
            removed.append(d.relative_to(root))
    for pattern in _BUILD_CRUFT_TOP_LEVEL_GLOBS:
        for d in list(code_dir.glob(pattern)):
            if d.is_dir():
                _rmtree_with_retry(d)
                removed.append(d.relative_to(root))
    for name in _BUILD_CRUFT_RECURSIVE:
        for d in list(code_dir.rglob(name)):
            if d.is_dir():
                _rmtree_with_retry(d)
                removed.append(d.relative_to(root))
    for name in _BUILD_CRUFT_RECURSIVE_FILES:
        for f in list(code_dir.rglob(name)):
            if f.is_file():
                f.unlink()
                removed.append(f.relative_to(root))
    for pattern in _BUILD_CRUFT_RECURSIVE_FILE_GLOBS:
        for f in list(code_dir.rglob(pattern)):
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


def _print_openevolve_db_report(report: dict, *, source_dir: Path,
                                exp_dir: Path, root: Path) -> None:
    """Surface the database-inheritance decision in the branch report.

    Three cases: (a) inherited the source's latest checkpoint,
    (b) operator passed `--new-openevolve-database` so the child starts
    fresh, (c) the source has no openevolve checkpoints yet so there's
    nothing to inherit. In all three the child writes its OWN future
    checkpoints into `<child>/logs/openevolve_output/`; "inherits"
    means "seeded from", not "shares files".
    """
    rel_child = exp_dir.relative_to(root)
    print("OpenEvolve database:")
    print(f"  child writes to:   {rel_child}/logs/openevolve_output/")
    if report["mode"] == "inherited":
        ckpt_rel = report["parent_checkpoint"].relative_to(root)
        print(f"  inherited from:    {ckpt_rel}  (iteration {report['iteration']})")
        print(f"  checkpoint_resume: {report['relative']!r}")
        print(f"  -> run_experiment.py will load the source's MAP-Elites state at")
        print(f"     launch and continue the search from there. Re-run with")
        print(f"     `--new-openevolve-database` if the counterfactual delta")
        print(f"     invalidates the parent's search state (different seed,")
        print(f"     evaluator contract change, database-shape change in config.yaml).")
    elif report["mode"] == "fresh-by-flag":
        print(f"  inherited from:    none (--new-openevolve-database was passed)")
        print(f"  checkpoint_resume: null")
        print(f"  -> child starts a fresh database. The seed program is scored as")
        print(f"     iteration 0 by openevolve.")
    else:  # fresh-no-parent-db
        rel_src = source_dir.relative_to(root)
        print(f"  inherited from:    none (source {rel_src} has no openevolve")
        print(f"                     checkpoints yet — its logs/openevolve_output/")
        print(f"                     is empty)")
        print(f"  checkpoint_resume: null")
        print(f"  -> child starts a fresh database. If you wanted to resume from")
        print(f"     the source, launch the source first and re-branch once it")
        print(f"     has at least one checkpoint, or set `checkpoint_resume` by")
        print(f"     hand in {rel_child}/code/run_config.json before launch.")


def _inherit_openevolve_db(
    *,
    exp_dir: Path,
    source_dir: Path,
    new_database: bool,
    root: Path,
) -> dict:
    """Set the child's `openevolve.checkpoint_resume` so it resumes from
    the source's latest MAP-Elites snapshot.

    Returns a report dict for the caller to print:
        {
          "mode":              "inherited" | "fresh-by-flag" | "fresh-no-parent-db",
          "parent_checkpoint": absolute Path or None,
          "relative":          string written into run_config.json or None,
          "iteration":         int or None,
        }
    """
    child_config_path = exp_dir / "code" / "run_config.json"
    if not child_config_path.exists():
        return {"mode": "fresh-no-parent-db", "parent_checkpoint": None,
                "relative": None, "iteration": None}

    cfg = json.loads(child_config_path.read_text())
    openevolve = cfg.setdefault("openevolve", {})

    if new_database:
        openevolve["checkpoint_resume"] = None
        child_config_path.write_text(json.dumps(cfg, indent=2) + "\n")
        return {"mode": "fresh-by-flag", "parent_checkpoint": None,
                "relative": None, "iteration": None}

    latest = openevolve_latest_checkpoint(source_dir)
    if latest is None:
        openevolve["checkpoint_resume"] = None
        child_config_path.write_text(json.dumps(cfg, indent=2) + "\n")
        return {"mode": "fresh-no-parent-db", "parent_checkpoint": None,
                "relative": None, "iteration": None}

    iteration, ckpt_path = latest
    child_code_dir = exp_dir / "code"
    relative = Path(os.path.relpath(ckpt_path, child_code_dir)).as_posix()
    openevolve["checkpoint_resume"] = relative
    child_config_path.write_text(json.dumps(cfg, indent=2) + "\n")
    return {"mode": "inherited", "parent_checkpoint": ckpt_path,
            "relative": relative, "iteration": iteration}


def _branch_experiment(args, *, root: Path, source_dir: Path) -> dict:
    # Variant is inherited from the source experiment — branching is
    # variant-blind by construction (it deep-copies whatever the parent
    # had in code/). We just propagate the value into freshly-rendered
    # templates so e.g. index.md shows the right variant tag and the
    # same `{{variant}}` placeholder resolves.
    variant = experiment_variant_from_run_config(source_dir)
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

    family_baselines = family_dir / "baselines"
    family_baselines.mkdir(exist_ok=True)
    family_baselines_index = family_baselines / "index.md"
    if not family_baselines_index.exists():
        family_baselines_index.write_text(render_template(
            load_template("family-baselines-index.md"),
            {"family": family, "created_at": utcnow_iso()},
        ))

    exp_dir = family_dir / f"{exp_id}-{slug}"
    if exp_dir.exists():
        raise ProjectLockError(
            f"experiment id {exp_id} already exists; another agent likely "
            f"allocated it concurrently. Retry the command to allocate the next id."
        )
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
    if variant in OPENEVOLVE_VARIANTS:
        (exp_dir / "data" / "acp-openai-server" / "jsonl").mkdir(parents=True)
        (exp_dir / "data" / "acp-openai-server" / "process").mkdir(parents=True)

    # 3. Create empty output subdirs.
    for sub in EMPTY_SUBDIRS:
        (exp_dir / sub).mkdir(exist_ok=True)

    # 4. Render fresh index.md / plan.md / run.md / results.md / hypotheses.md /
    #    artifacts/*.md with the child's identity + branch provenance.
    branched_at = utcnow_iso()
    iteration_delta_oneline = args.delta[0] if args.delta else "TODO"

    vars_ = {
        "experiment_id": exp_id,
        "slug": slug,
        "title": args.title,
        "family": family,
        "variant": variant,
        "status": "planned",
        "created_at": branched_at,
        "experiment_type": "iteration",
        "iteration_delta_oneline": iteration_delta_oneline,
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
            render_template(load_template(tmpl_name, variant=variant), vars_)
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

    # 5b. Verify the parent's vendored python_exp came along with the
    #     deep-copy and ensure the child's pyproject points at the local
    #     vendored copy (regex-rewrites if the parent's pyproject was on
    #     the legacy editable link). Returns provenance for the agent to
    #     verify nothing unrelated got clobbered.
    try:
        vendor_prov = verify_or_fix_branched_python_exp(
            parent_code_dir=source_dir / "code",
            child_code_dir=exp_dir / "code",
        )
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        shutil.rmtree(exp_dir, ignore_errors=True)
        raise ProjectLockError(
            f"vendored python_exp inheritance failed: {e}\n"
            f"       scaffolded experiment directory was rolled back."
        ) from e

    # 6. Run the branch retargeting as plain search/replace over copied text
    #    files. This intentionally includes JSON as text: full source
    #    id+slug first, then bare source id, then bare source slug. Generated
    #    files (index.md, plan.md, run.md, ...) are not swept, so they can
    #    still record the lineage parent and branch provenance accurately.
    source_config_path = source_dir / "code" / "run_config.json"
    parent_identity = (args.source, parent_slug)
    child_identity = (exp_id, slug)
    text_file_rewrites = rewrite_branch_identity_in_text_files(
        [
            exp_dir / "code",
            exp_dir / "data" / "generation-scripts",
            exp_dir / "data" / "manifest.md",
        ],
        report_root=exp_dir,
        parent_identity=parent_identity,
        child_identity=child_identity,
    )

    # 7. Evolve-variant: inherit (or refuse to inherit) the parent's
    #    openevolve database. By default the child's
    #    `openevolve.checkpoint_resume` is set to the source's latest
    #    `checkpoint_N/` directory, written as a relative path from the
    #    child's `code/` (where run_experiment.py resolves paths). The
    #    --new-openevolve-database flag opts out (leaves null).
    openevolve_db_report = None
    if variant in OPENEVOLVE_VARIANTS:
        openevolve_db_report = _inherit_openevolve_db(
            exp_dir=exp_dir,
            source_dir=source_dir,
            new_database=args.new_openevolve_database,
            root=root,
        )

    return {
        "exp_id": exp_id,
        "exp_dir": exp_dir,
        "purged_cruft": purged_cruft,
        "vendor_prov": vendor_prov,
        "source_config_path": source_config_path,
        "text_file_rewrites": text_file_rewrites,
        "openevolve_db_report": openevolve_db_report,
        "branched_at": branched_at,
        "family": family,
        "variant": variant,
        "parent_id": parent_id,
    }


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
    ap.add_argument("--new-openevolve-database", action="store_true",
                    help="(OpenEvolve variants only) Skip inheriting the source's "
                         "openevolve database. By default the child's "
                         "`run_config.json:openevolve.checkpoint_resume` is "
                         "set to the source's latest `checkpoint_N/` so the "
                         "MAP-Elites search continues seeded from the parent. "
                         "Pass this flag when the counterfactual delta "
                         "invalidates the parent's search state (e.g. swapping "
                         "initial_program.py, changing the evaluator contract, "
                         "or restructuring config.yaml's database block).")
    ap.add_argument("--lock-timeout", type=float, default=30.0,
                    help="Seconds to wait for the git-backed project lock "
                         "before failing with retry guidance (default: 30).")
    ap.add_argument("--lock-stale-after", type=float, default=900.0,
                    help="Seconds after which a held project lock may be "
                         "stolen as stale (default: 900).")
    ap.add_argument("--no-wait-lock", "--fail-if-locked",
                    dest="no_wait_lock", action="store_true",
                    help="Try the git-backed project lock once and fail "
                         "immediately if another process holds it.")
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

    try:
        with acquire_project_lock(
            root,
            "scaffold-project-state",
            timeout_seconds=args.lock_timeout,
            wait=not args.no_wait_lock,
            stale_after_seconds=args.lock_stale_after,
        ):
            branch = _branch_experiment(args, root=root, source_dir=source_dir)
    except ProjectLockError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    exp_id = branch["exp_id"]
    exp_dir = branch["exp_dir"]
    purged_cruft = branch["purged_cruft"]
    vendor_prov = branch["vendor_prov"]
    source_config_path = branch["source_config_path"]
    text_file_rewrites = branch["text_file_rewrites"]
    openevolve_db_report = branch["openevolve_db_report"]
    branched_at = branch["branched_at"]
    family = branch["family"]
    variant = branch["variant"]
    parent_id = branch["parent_id"]

    rel = exp_dir.relative_to(root)
    print(f"Branched {args.source} -> {exp_id} at {rel}")
    print(f"  branched_at: {branched_at}")
    print(f"  family: {family}" + (" (inherited from source)" if args.family is None else ""))
    print(f"  variant: {variant} (inherited from source)")
    print(f"  lineage parent: {parent_id}"
          + (" (== source)" if parent_id == args.source else ""))
    print()
    print("Copied from source:")
    for item in COPIED_FROM_SOURCE:
        print(f"  - {item}")
    print()
    print_vendoring_provenance(vendor_prov, source_kind="parent")
    print()
    if source_config_path.exists():
        print(f"run_config.json: copied from {source_config_path.relative_to(root)} and swept as text.")
    else:
        print("run_config.json: source had none — child has none either.")
    if text_file_rewrites:
        print()
        print("Search/replace report:")
        for path, counts in text_file_rewrites:
            print(f"  - {path}:")
            for item in counts:
                suffix = "replacement" if item["count"] == 1 else "replacements"
                print(f"      {item['kind']}: {item['old']!r} -> {item['new']!r} ({item['count']} {suffix})")
    else:
        print()
        print("Search/replace report: no source id or slug strings found in copied text files.")
    if purged_cruft:
        print()
        print("Purged build artifacts copied from source code/ tree:")
        for path in purged_cruft:
            print(f"  - {path}")
    if openevolve_db_report is not None:
        print()
        _print_openevolve_db_report(openevolve_db_report, source_dir=source_dir,
                                    exp_dir=exp_dir, root=root)
    print()
    print("Reminders before launch:")
    if openevolve_db_report is not None:
        process_dir = exp_dir / "data/acp-openai-server/process"
        print(f"  0. ACP server (required by the default config.yaml): start a")
        print(f"     fresh server for this experiment before launching it. Keep")
        print(f"     the launcher root and logs inside the child experiment:")
        print(f'         mkdir -p "{process_dir}"')
        print(f'         "$SKILL_MANAGER_HOME/skills/acp-cdc-ai-python/scripts/start-server.py" \\')
        print(f'             --project-root "{exp_dir}" \\')
        print(f"             --host 127.0.0.1 \\")
        print(f"             --log-dir data/acp-openai-server/jsonl \\")
        print(f'             > "{process_dir}/stdout.log" \\')
        print(f'             2> "{process_dir}/stderr.log" &')
        print(f"     `code/run_experiment.py` probes")
        print(f"     this experiment's `.acp-server/server.json`, points")
        print(f"     OpenEvolve at the recorded host/port, and refuses to run if")
        print(f"     the server is missing. JSONL traces go to")
        print(f"     `data/acp-openai-server/jsonl/`; stdout/stderr go to")
        print(f"     `data/acp-openai-server/process/`. See SKILL.md > 'Prerequisite:")
        print(f"     the ACP-backed OpenAI-compatible server' for the full rationale.")
        print(f"     Also confirm `code/config.yaml` and")
        print(f"     `code/prompt-templates/diff_user.txt` keep the strict")
        print(f"     diff-only/no-write-tools mutation-agent contract; older")
        print(f"     source experiments may not have this prompt hardening.")
        print(f"     Confirm `code/openevolve_capacity.py` exists if this child")
        print(f"     should fail over across `llm.models` on provider capacity")
        print(f"     errors and persist cooldowns in")
        print(f"     `data/openevolve_model_capacity.json` plus append events to")
        print(f"     `data/openevolve_model_capacity_events.jsonl`.")
    print(f"  1. Inherited config audit (see SKILL.md > 'Inherited config audit'):")
    print(f"     - Review the search/replace report above. If any retargeted")
    print(f"       copied reference was intentionally parent-facing, restore it")
    print(f"       explicitly and record why in plan.md.")
    print(f"     - For each inherited run_config key, decide keep | override |")
    print(f"       delete. Override now if the key is in the counterfactual delta;")
    print(f"       delete if it was a parent-specific setting that does not apply.")
    print(f"     - Record decisions in {rel}/plan.md under '## Inherited config audit'")
    print(f"       before the freeze commit. Do NOT carry parent cruft forward —")
    print(f"       the next agent should not have to spelunk to figure out why")
    print(f"       a stale field is still in this config.")
    print(f"  2. Review copied implementation notes and comments if this branch")
    print(f"     intentionally needs to mention {args.source}; the automatic")
    print(f"     source-id sweep retargeted copied text references to {exp_id}.")
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
