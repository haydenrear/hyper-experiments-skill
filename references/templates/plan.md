# Plan: {{experiment_id}} — {{title}}

## Research question
{{research_question}}

## Parentage
- Parent experiment: {{parent_experiment}}
- Parent checkpoint: {{parent_checkpoint}}
- Ancestor baseline: {{ancestor_baseline}}

## Counterfactual delta
{{counterfactual_delta}}

## Invariants
{{invariants}}

## Expected mechanism
<!-- Why might this change matter mechanistically? -->
- TODO

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

## Risks
- TODO

## Comparison targets
- TODO
