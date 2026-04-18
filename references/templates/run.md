# Run Journal: {{experiment_id}}

## Freeze (chain of custody)

Fill this in **before** launch. The experiment must not transition to
`running` until every row below has a real value. See
`references/chain-of-custody.md`.

- frozen_at (UTC):
- vendored `python_exp` from: `tools/python_exp/` @ git SHA
- vendored to: `code/vendored/python_exp/`
- `[tool.uv.sources]` switched to local path: yes | no
- other vendored tools (jars, binaries, CLIs):
- vendored generation scripts (source exp-id + path → local path):
- referenced frozen-ancestor datasets (exp-id + path):
- smoke-run verified (`uv sync && uv run run-experiment` succeeds): yes | no
- operator / agent who froze:

## Launch
- timestamp:
- host:
- command: {{command}}
- code snapshot:
- parent experiment: {{parent_experiment}}
- parent checkpoint: {{parent_checkpoint}}

## Poll 1
- timestamp:
- observed:
- comparisons:
- decision:
- rationale:

## Final decision
- completed | stopped | branched | aborted
- rationale:
