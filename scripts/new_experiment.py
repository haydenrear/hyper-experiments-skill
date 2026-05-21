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
    DEFAULT_VARIANT,
    OPENEVOLVE_VARIANTS,
    ProjectLockError,
    VALID_VARIANTS,
    acquire_project_lock,
    allocate_experiment_id,
    bullet_list,
    find_experiment_dir,
    find_experiments_root,
    inherit_run_config,
    load_template,
    print_vendoring_provenance,
    project_variant_from_marker,
    render_template,
    run_smoke_test_and_cleanup,
    slugify,
    utcnow_iso,
    vendor_python_exp_from_tools,
)


RUN_CONFIG_TEMPLATE = "code-run-config.json"
RUN_CONFIG_OUT = "code/run_config.json"

SUBDIRS = ("code", "logs", "tensorboard", "checkpoints")
DATA_SUBDIRS = ("generation-scripts", "generated")
EVOLVE_DATA_SUBDIRS = ("acp-openai-server/jsonl", "acp-openai-server/process")
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

# Variant-specific code/ files added on top of CODE_FILES. Maps the
# output path inside the experiment to the template name (the loader
# resolves it under `references/templates/<variant>/`).
EXTRA_CODE_FILES_BY_VARIANT = {
    "default": {},
    "evolve": {
        "code/initial_program.py": "code-initial-program.py",
        "code/evaluator.py": "code-evaluator.py",
        "code/config.yaml": "code-config.yaml",
        "code/openevolve_capacity.py": "code-openevolve-capacity.py",
        "code/openevolve_db.py": "code-openevolve-db.py",
        "code/prompt-templates/diff_user.txt": "code-prompt-templates-diff_user.txt",
    },
    "openevolve-agentic-fitness": {
        "code/initial_program.py": "code-initial-program.py",
        "code/evaluator.py": "code-evaluator.py",
        "code/config.yaml": "code-config.yaml",
        "code/openevolve_capacity.py": "code-openevolve-capacity.py",
        "code/openevolve_db.py": "code-openevolve-db.py",
        "code/prompt-templates/diff_user.txt": "code-prompt-templates-diff_user.txt",
    },
}


def _scaffold_experiment(args, *, root: Path, variant: str) -> dict:
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

    family_baselines = family_dir / "baselines"
    family_baselines.mkdir(exist_ok=True)
    family_baselines_index = family_baselines / "index.md"
    if not family_baselines_index.exists():
        family_baselines_index.write_text(render_template(
            load_template("family-baselines-index.md"),
            {"family": args.family, "created_at": utcnow_iso()},
        ))

    exp_dir = family_dir / f"{exp_id}-{slug}"
    if exp_dir.exists():
        raise ProjectLockError(
            f"experiment id {exp_id} already exists; another agent likely "
            f"allocated it concurrently. Retry the command to allocate the next id."
        )
    exp_dir.mkdir()
    for sub in SUBDIRS:
        (exp_dir / sub).mkdir()
    (exp_dir / "artifacts").mkdir()
    (exp_dir / "data").mkdir()
    for sub in DATA_SUBDIRS:
        (exp_dir / "data" / sub).mkdir()
    if variant in OPENEVOLVE_VARIANTS:
        for sub in EVOLVE_DATA_SUBDIRS:
            (exp_dir / "data" / sub).mkdir(parents=True)

    parent_dir_rel = "null"
    if args.parent:
        p = find_experiment_dir(root, args.parent)
        if p is not None:
            parent_dir_rel = str(p.relative_to(root))
        else:
            print(f"warning: parent {args.parent} not found under experiments/families/",
                  file=sys.stderr)

    iteration_delta_oneline = args.delta[0] if args.delta else "TODO"

    vars_ = {
        "experiment_id": exp_id,
        "slug": slug,
        "title": args.title,
        "family": args.family,
        "variant": variant,
        "status": "planned",
        "created_at": utcnow_iso(),
        "experiment_type": args.exp_type,
        "iteration_delta_oneline": iteration_delta_oneline,
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
            render_template(load_template(tmpl_name, variant=variant), vars_)
        )
    for out_name, tmpl_name in {**ARTIFACT_FILES, **DATA_FILES, **CODE_FILES}.items():
        (exp_dir / out_name).write_text(
            render_template(load_template(tmpl_name, variant=variant), vars_)
        )
    for out_name, tmpl_name in EXTRA_CODE_FILES_BY_VARIANT.get(variant, {}).items():
        (exp_dir / out_name).parent.mkdir(parents=True, exist_ok=True)
        (exp_dir / out_name).write_text(
            render_template(load_template(tmpl_name, variant=variant), vars_)
        )

    run_config_renames = _write_run_config(
        exp_dir=exp_dir, root=root, parent_id=args.parent,
        child_vars=vars_, variant=variant,
    )

    try:
        vendor_prov = vendor_python_exp_from_tools(
            root / "tools" / "python_exp",
            exp_dir / "code",
        )
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        import shutil as _shutil
        _shutil.rmtree(exp_dir, ignore_errors=True)
        raise ProjectLockError(
            f"vendoring python_exp failed: {e}\n"
            f"       scaffolded experiment directory was rolled back."
        ) from e

    return {
        "exp_id": exp_id,
        "exp_dir": exp_dir,
        "run_config_renames": run_config_renames,
        "vendor_prov": vendor_prov,
    }


def _write_run_config(*, exp_dir: Path, root: Path, parent_id, child_vars, variant):
    """Render `code/run_config.json` for the child, inheriting from the parent
    config when one exists. Returns a list of (path, old, new) renames so the
    caller can report them."""
    template_obj = json.loads(load_template(RUN_CONFIG_TEMPLATE, variant=variant))

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


def _print_smoke_report(exp_dir: Path, rel: Path, variant: str) -> int:
    """Run the smoke test, clean up its artifacts, and report. Returns the
    process exit code to propagate (0 on success, 1 on failure)."""
    if variant in OPENEVOLVE_VARIANTS:
        print("Smoke test: running `uv sync && OPENEVOLVE_SMOKE=1 uv run run-experiment` "
              "(no LLM calls) ...")
    else:
        print("Smoke test: running `uv sync && uv run run-experiment` ...")
    result = run_smoke_test_and_cleanup(exp_dir, variant=variant)
    if result["skipped"]:
        print(f"  skipped: {result['skipped']}")
        print()
        return 0
    if not result["ok"]:
        print("  FAILED — artifacts left in place for inspection.")
        print()
        for line in (result["stdout"] or "").splitlines()[-20:]:
            print(f"    {line}")
        print()
        print(f"error: smoke test failed under {rel}/code/.", file=sys.stderr)
        return 1
    print("  ok.")
    if result["removed"]:
        print("  Cleaned up smoke artifacts:")
        for path in result["removed"]:
            print(f"    - {path}")
    print()
    return 0


def _print_evolve_preflight(root: Path, rel: Path) -> None:
    """Print the OpenEvolve-variant prerequisites: the ACP-backed
    OpenAI-compatible server (from the `acp-cdc-ai-python` skill) and
    this experiment's database location. New experiments get their
    own empty database; branching is what inherits a parent's.
    """
    print("OpenEvolve-variant prerequisites:")
    print("  1. ACP server (required by the default config.yaml).")
    print("     The default config.yaml points `llm.api_base` at the")
    print("     local OpenAI-compatible server provided by the")
    print("     `acp-cdc-ai-python` skill (a skill_reference of")
    print("     hyper-experiments). Start a fresh server for this")
    print("     experiment before launching it. The launcher root and")
    print("     logs should be inside this experiment:")
    print()
    exp_dir = root / rel
    process_dir = exp_dir / "data/acp-openai-server/process"
    print(f'       mkdir -p "{process_dir}"')
    print('       "$SKILL_MANAGER_HOME/skills/acp-cdc-ai-python/scripts/start-server.py" \\')
    print(f'           --project-root "{exp_dir}" \\')
    print("           --host 127.0.0.1 \\")
    print("           --log-dir data/acp-openai-server/jsonl \\")
    print(f'           > "{process_dir}/stdout.log" \\')
    print(f'           2> "{process_dir}/stderr.log" &')
    print()
    print("     The launcher drops this experiment's")
    print("     `.acp-server/server.json`; `code/run_experiment.py`")
    print("     probes that file, points OpenEvolve at the recorded")
    print("     host/port, and refuses to start if the server is")
    print("     missing or stale.")
    print("     JSONL traces:      data/acp-openai-server/jsonl/")
    print("     server stdout/err: data/acp-openai-server/process/")
    print("     Mutation prompt:   code/prompt-templates/diff_user.txt")
    print("                        enforces diff-only/no-write-tools output.")
    print("     Model cooldowns:   data/openevolve_model_capacity.json")
    print("                        records quota reset times by model.")
    print("     Cooldown events:   data/openevolve_model_capacity_events.jsonl")
    print("                        logs exhaustion and viable-again times.")
    print("     See SKILL.md > 'Prerequisite: the ACP-backed")
    print("     OpenAI-compatible server' for the full rationale.")
    print()
    print("  2. OpenEvolve database — this experiment owns its own.")
    print(f"     Database path:     {rel}/logs/openevolve_output/")
    print("     checkpoint_resume: null (fresh database; the seed program")
    print("                        is scored as iteration 0 by openevolve).")
    print("     Inspect with:      `uv run openevolve-db status` from")
    print(f"                        inside {rel}/code/.")
    print("     Do NOT point `paths.openevolve_output` at another")
    print("     experiment's directory — concurrent writes corrupt both.")
    print("     To resume from an existing experiment's database, branch")
    print("     it with `branch_experiment.py` instead (which seeds the")
    print("     child's `openevolve.checkpoint_resume` from the parent's")
    print("     latest checkpoint by default).")
    print()


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
    ap.add_argument("--type", dest="exp_type",
                    choices=("root", "iteration"), default="iteration",
                    help="root = empirically-viable starting point with no anchor; "
                         "iteration = builds on a parent (default).")
    ap.add_argument("--question", default="",
                    help="Research question this experiment tests.")
    ap.add_argument("--parent", default=None,
                    help="Parent experiment id (e.g. exp-0001). "
                         "Required when --type=iteration.")
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
    ap.add_argument("--smoke", action="store_true",
                    help="After scaffolding, run `uv sync && uv run run-experiment` "
                         "inside code/ to confirm the frozen experiment is "
                         "self-reproducible, then wipe the artifacts the smoke "
                         "produced (.venv, __pycache__, tensorboard/*, logs/*). "
                         "For OpenEvolve variants the smoke run sets "
                         "OPENEVOLVE_SMOKE=1 to avoid LLM calls.")
    ap.add_argument("--variant", choices=VALID_VARIANTS, default=None,
                    help="Experiment variant. Defaults to the project's default "
                         "(read from `hyper-experiments.md`'s `Variant:` line). "
                         "`default` = PyTorch + tensorboard scaffold; "
                         "`evolve` = OpenEvolve loop scaffold (initial_program.py, "
                         "evaluator.py, config.yaml in code/); "
                         "`openevolve-agentic-fitness` = evolve scaffold with "
                         "agentic fitness reranking enabled.")
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

    if args.exp_type == "iteration" and not args.parent:
        print("error: --type=iteration requires --parent (the anchor experiment id).",
              file=sys.stderr)
        print("       use --type=root for an experiment with no anchor (a known-working baseline).",
              file=sys.stderr)
        return 1
    if args.exp_type == "root" and args.parent:
        print(f"error: --type=root experiments must not declare a --parent (got {args.parent!r}).",
              file=sys.stderr)
        print("       a root is an empirically-viable starting point; it is the anchor for downstream iterations.",
              file=sys.stderr)
        return 1

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

    project_default_variant = project_variant_from_marker(root)
    variant = args.variant or project_default_variant

    try:
        with acquire_project_lock(
            root,
            "scaffold-project-state",
            timeout_seconds=args.lock_timeout,
            wait=not args.no_wait_lock,
            stale_after_seconds=args.lock_stale_after,
        ):
            scaffold = _scaffold_experiment(args, root=root, variant=variant)
    except ProjectLockError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    exp_id = scaffold["exp_id"]
    exp_dir = scaffold["exp_dir"]
    run_config_renames = scaffold["run_config_renames"]
    vendor_prov = scaffold["vendor_prov"]

    rel = exp_dir.relative_to(root)
    print(f"Created {exp_id} at {rel}")
    variant_note = ""
    if args.variant is None:
        variant_note = f" (project default from {root.name}/hyper-experiments.md)"
    print(f"  variant: {variant}{variant_note}")
    print()
    print_vendoring_provenance(vendor_prov, source_kind="tools")
    print()
    _print_run_config_report(run_config_renames, args.parent)
    print()
    if args.smoke:
        if _print_smoke_report(exp_dir, rel, variant) != 0:
            return 1
    if variant in OPENEVOLVE_VARIANTS:
        _print_evolve_preflight(root, rel)
    print("Next steps:")
    print(f"  1. Fill in decision policy and measurement plan in {rel}/plan.md")
    print(f"  2. Complete {rel}/index.md (continue/stop/branch criteria, key signals)")
    print(f"  3. Add a row to experiments/experiments.md under 'Active experiments'")
    print(f"  4. Append this experiment to experiments/families/{args.family}/index.md")
    print(f"     under 'Experiments in this family' and note whether it tests")
    print(f"     an existing working theory or opens a new one")
    print(f"  5. Copy the relevant code snapshot into {rel}/code/")
    print()
    print("Git discipline (see SKILL.md > 'Git discipline'):")
    print(f"  * Commit the scaffold now so the starting state is in the log:")
    print(f"      git add {rel}/")
    print(f"      git commit -m \"[{exp_id}] scaffold\"")
    print(f"  * After the freeze procedure and before launch, make the")
    print(f"    mandatory pre-launch commit:")
    print(f"      git commit -m \"[{exp_id}] freeze: scaffold + vendored tools\"")
    print(f"  * After the experiment finishes and the ledger / strategy indexes")
    print(f"    are updated, make the mandatory post-finish commit:")
    print(f"      git commit -m \"[{exp_id}] complete: <one-line finding>\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
