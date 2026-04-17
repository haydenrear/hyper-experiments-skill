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
- code/
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
