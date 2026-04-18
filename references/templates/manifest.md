---
experiment_id: {{experiment_id}}
family: {{family}}
created_at: {{created_at}}
---

# Data manifest — {{experiment_id}}

This file describes the datasets and generation scripts that belong to this
experiment, plus references to datasets or scripts owned by other experiments
that this one inherits.

All reference paths in this file are **relative to the hyper-experiments
project root** — i.e. the directory containing `hyper-experiments.md`. This
keeps references stable across families and across experiments, and avoids
duplicating data on disk.

Local (unqualified) paths in the "Generated datasets" and "Generation scripts"
sections below are relative to this experiment's `data/` directory.

---

## Generated datasets

Datasets physically produced under this experiment's `data/generated/`.

Each entry must state what the dataset is, where it lives, and which script
produced it.

| name | path | description | producer |
|------|------|-------------|----------|
| _example_ | `generated/train.parquet` | training split after filtering | `generation-scripts/build_train.py` |
| TODO | TODO | TODO | TODO |

If this experiment does not generate new data (it only consumes referenced
data from ancestors), replace this table with `- none`.

---

## Generation scripts

Scripts in this experiment's `data/generation-scripts/` that produced the
datasets above.

### `<script-name>.py`
- Path: `generation-scripts/<script-name>.py`
- Entry point: `main()` (or `python generation-scripts/<script-name>.py`)
- Run:
  ```bash
  python generation-scripts/<script-name>.py --out generated/<name>
  ```
- Inputs: TODO — where the raw inputs come from (local path, URL, or a
  referenced dataset from another experiment).
- Outputs: TODO — which paths under `generated/` this script writes.
- Determinism: TODO — seed, version, or "nondeterministic".

(Repeat this block per script. Delete if this experiment has no scripts.)

---

## References

Pointers to datasets owned by **other experiments** that this experiment
reuses. Paths are resolved from the hyper-experiments root (the directory
containing `hyper-experiments.md`), so references work across families.

Chain of custody rules apply (see `references/chain-of-custody.md`):

- **Referencing generated data** owned by another experiment is allowed
  **only** if that ancestor is in a frozen status (`running`,
  `completed`, `archived`). Never reference data owned by a `planned`
  experiment — its data pipeline has not yet been committed.
- **Referencing generation scripts** owned by another experiment is
  **not** allowed in a launched experiment. If this experiment needs to
  run someone else's generation logic, copy the script into this
  experiment's own `data/generation-scripts/` and record the source
  (exp-id, original path, git SHA if available) in a provenance comment
  at the top of the copied script. Then list the copied script under
  "Generation scripts" above, not here.

### Inherited datasets (allowed)
- `experiments/families/<family>/<exp-id>-<slug>/data/generated/<name>` —
  reason this experiment relies on it; ancestor status must be frozen.
- TODO

### Inherited generation scripts (forbidden after launch)

This section exists only to remind you of the vendoring rule:

> If you see a path here at launch time, **stop**: copy the script into
> this experiment's own `data/generation-scripts/` with a provenance
> comment and remove the entry from this section.

- TODO — expect this list to be empty by the time the experiment is
  frozen.

If this experiment inherits nothing, replace the dataset list with `- none`.
