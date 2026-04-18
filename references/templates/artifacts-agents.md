# Agent instructions — {{experiment_id}}

Operating instructions for any LLM or agent working inside this experiment's
directory. Keep this scoped to **this experiment**; project-wide agent
guidance belongs in the hyper-experiments `SKILL.md`, not here.

## Role
What this agent is expected to do inside this experiment (e.g. run the
experiment, poll it, evaluate it, propose children).

## Preferred tools and scripts
- TODO — scripts the agent should prefer (`generation-scripts/*.py`, launchers,
  eval tools).
- TODO — which logs / TensorBoard runs to inspect.

## Boundaries
- Do **not** edit `index.md`'s Parent section after launch — lineage is frozen.
- Do **not** overwrite `generated/` outputs without recording the regeneration
  in `run.md`.
- Do **not** edit `code/` or `data/generation-scripts/` after launch. If a
  change is needed, create a child experiment. See
  `references/chain-of-custody.md`.
- Do **not** launch this experiment until it has been frozen: `tools/python_exp`
  vendored into `code/vendored/`, `[tool.uv.sources]` pointing inside this
  experiment, every generation-script reference resolved to a local copy, and
  the `Freeze` block in `run.md` filled in.
- TODO — anything else this experiment considers off-limits.

## Conventions
- Append to `run.md` for every poll, decision, or anomaly.
- Write post-run conclusions to `results.md` and `hypotheses.md`.
- Update the root `experiments/experiments.md` ledger when status changes.

## Handoff notes
Short-form notes for the next agent picking up this experiment: what is
in-flight, what is blocked, what to watch for.
