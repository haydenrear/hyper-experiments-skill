# Experiment: {{experiment_id}}

- Title: {{title}}
- Family: {{family}}
- Status: {{status}}
- Created: {{created_at}}

## Parent
- Parent experiment: {{parent_experiment}}
- Parent checkpoint: {{parent_checkpoint}}
- Parent directory: {{parent_directory}}
- Ancestor baseline: {{ancestor_baseline}}

## Branch provenance
<!-- Populated by scripts/branch_experiment.py when this experiment was
     deep-copied from another. `null` means this experiment was scaffolded
     from templates rather than branched. The branched-from id may equal
     `parent_experiment` (normal case) or differ (rare: branched from a
     sibling for code convenience, but conceptual parent is elsewhere). -->
- Branched from: {{branched_from}}
- Branched at: {{branched_at}}
- Files copied from source: {{branch_copied_files}}

## Intent
{{research_question}}

## Counterfactual delta
{{counterfactual_delta}}

## Invariants
{{invariants}}

## Command
```bash
{{command}}
```

## Decision policy

### Continue if
- TODO

### Stop if
- TODO

### Branch if
- TODO

## Key signals
- TODO

## Artifacts
- code/ — standalone uv project; run with `uv run run-experiment`
- code/run_experiment.py — entry point
- code/run_config.json — machine-readable run configuration (inherited from parent)
- code/check_regressions.py — per-experiment regression check (contract assertions against `python_exp`)
- tensorboard/
- checkpoints/
- logs/
- artifacts/AGENTS.md, artifacts/memory.md — agent instructions and scratch memory
- data/manifest.md — datasets, generation scripts, and references to other experiments' data
- data/generation-scripts/ — scripts that produce this experiment's data
- data/generated/ — locally produced datasets (may be empty if this experiment only references inherited data)
- plan.md
- run.md
- results.md
- hypotheses.md
