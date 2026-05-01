# Baselines — {{project_name}}

Created: {{created_at}}

This directory caches **cross-family baselines** — reusable comparison
points that are valid across more than one family. Anything filed here
is a contract with the project: it will not change, and any experiment
in any family may reference it.

The point of caching baselines here is to **run baselines as few times
as possible**. A baseline that has already been computed should be
referenced, not re-run. Adding a new entry to this index is a
deliberate decision, not a routine action.

How this relates to other baseline scopes:

- `experiments/baselines/` (this file) — cross-family, project-wide.
- `experiments/families/<family>/baselines/` — scoped to a single
  family.
- per-experiment `code/run_experiment.py` `run_baselines()` —
  baselines an individual experiment produces for its own use.

Promotion path: a baseline starts inside an experiment, gets promoted
to a family when a sibling needs it, and gets promoted here when a
second family needs it. Demote a baseline out of this index only when
no remaining experiment references it.

Chain-of-custody note: like a frozen experiment, a baseline's
artifacts are immutable once an experiment references them. If the
underlying computation needs to change, file a new baseline (with a
distinct name) and supersede the old one — never edit a baseline in
place.

---

## Baselines

Append-only listing. Each entry must say what the baseline measures,
what produced it, when it was produced (ISO timestamp + commit SHA),
and which experiments reference it.

Template for an entry:

> **&lt;baseline-name&gt;** — one-sentence description.
> *Produced by*: exp-XXXX (or external pipeline + script path).
> *Produced at*: 2025-01-01T00:00:00Z @ &lt;commit-sha&gt;.
> *Artifacts*: relative paths under this directory.
> *Used by*: exp-YYYY, exp-ZZZZ.
> *Status*: active | superseded-by-&lt;name&gt; | retired.

- TODO
