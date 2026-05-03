# Plan: {{experiment_id}} — {{title}}

## Chain of reasoning

- Type: {{experiment_type}}
- Anchor (parent): {{parent_experiment}}
- Anchor evidence: TODO
- Iteration (one-line delta): {{iteration_delta_oneline}}
- Primary hypothesis: TODO
- Falsifiers: TODO
- Parent checkpoint: {{parent_checkpoint}}
- Ancestor baseline: {{ancestor_baseline}}
- Global hypothesis: [`global-hypothesis.md`](../../../../global-hypothesis.md)

## Counterfactual delta
{{counterfactual_delta}}

## Invariants
{{invariants}}

## Implementation

### Command
```bash
{{command}}
```

### Code changes
- file:
  modification:
  reason:

## Measurement plan
| metric | why | expected direction |
|--------|-----|---------------------|
| train/loss | primary optimization signal | down |
| val/loss | generalization signal | down |

## Decision policy

### Continue criteria
- TODO

### Stop criteria
- TODO

### Branch criteria
- TODO

## Inherited config audit
<!--
Filled in after running new_experiment.py / branch_experiment.py.
The scaffolder prints three audit blocks; record the decisions here
so the next reader can see what was deliberate vs. inherited cruft.
See SKILL.md > 'Inherited config audit' for the ritual.
-->

### Parent-identity references reviewed
| path | original value | decision | rationale |
|------|----------------|----------|-----------|
| _e.g._ `logging.wandb.tags[1]` | `"exp-0001-lower-lr"` | rewritten | stale tag from parent |

### Inherited verbatim — disposition
| key | value | decision (keep/override/delete) | rationale |
|-----|-------|----------------------------------|-----------|
| _e.g._ `learning_rate` | `0.0003` | override -> `0.0001` | part of counterfactual delta |
| _e.g._ `hyperparameters.warmup_steps` | `500` | keep | unchanged from parent regime |
| _e.g._ `hyperparameters.legacy_flag_x` | `true` | delete | parent-only setting, no longer applies |
