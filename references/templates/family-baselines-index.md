# Baselines — family: {{family}}

Created: {{created_at}}

This directory caches **per-family baselines** — reusable comparison
points that are valid for experiments in `{{family}}` but not (yet)
required at the cross-family level.

The point of caching baselines here is to run baselines as few times
as possible. Before producing a new baseline, check whether one
already exists at this level or one level up
(`../../baselines/index.md`).

Promote a baseline to `experiments/baselines/` (cross-family) once a
second family needs it; demote a baseline out of this index only when
no experiment in the family references it any more.

Chain-of-custody note: a baseline's artifacts are immutable once an
experiment references them. If the underlying computation needs to
change, file a new baseline (with a distinct name) and supersede the
old one — never edit a baseline in place.

---

## Baselines

Append-only listing. Each entry must say what the baseline measures,
what produced it, when it was produced (ISO timestamp + commit SHA),
and which experiments in this family reference it.

Template for an entry:

> **&lt;baseline-name&gt;** — one-sentence description.
> *Produced by*: exp-XXXX (or external pipeline + script path).
> *Produced at*: 2025-01-01T00:00:00Z @ &lt;commit-sha&gt;.
> *Artifacts*: relative paths under this directory.
> *Used by*: exp-YYYY, exp-ZZZZ.
> *Status*: active | superseded-by-&lt;name&gt; | retired.

- TODO
