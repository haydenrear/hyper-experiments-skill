# Families Index — {{project_name}}

Created: {{created_at}}

This document is the **cross-family planning and orchestration index**.
It sits above every experiment family and captures theories, config
recommendations, and plans that transcend any single family.

How this file relates to the others:

- `experiments/experiments.md` — operational ledger (what was run, what
  is running, what is completed, best checkpoints). Backward-looking.
- `experiments/families/index.md` (this file) — cross-family strategy.
  Theories, recommendations, and plans that span multiple families.
  Forward-looking.
- `experiments/families/<family>/index.md` — per-family strategy within
  a single family. Forward-looking.

Update this document when:

- a theory strengthens or weakens in one family in a way that affects
  another,
- a config recommendation emerges that holds across families,
- a new family is proposed or retired,
- a meta-observation about the research process itself is worth
  recording.

---

## Families
Brief one-line characterization per family plus its current state.
`active experiments` counts only experiments whose status is
`planned`, `running`, or `stopped` awaiting review.

| family | research line | active experiments | status |
|--------|---------------|--------------------|--------|

## Cross-family theories
Hypotheses that span more than one family. Each entry should state the
theory, its mechanistic grounding, the families that bear on it, and
the experiments that most strongly support or contradict it.

Template for an entry:

> **Theory name** — one-sentence claim.
> *Mechanism*: why this might be true.
> *Families*: family_a, family_b.
> *Supported by*: exp-XXXX (family_a), exp-YYYY (family_b).
> *Weakened by*: exp-ZZZZ (family_a).
> *Status*: active | retired | superseded-by-<theory-name>.

- TODO

## Cross-family config recommendations
Settings that hold up regardless of family. Each entry should list the
families that have confirmed the setting, the families that are known
exceptions, and the mechanistic reason the setting generalizes.

- TODO

## Proposed future families
Research lines not yet opened. Each entry should describe the driving
question, why a new family is warranted (rather than an extension of an
existing one), and an initial experiment idea.

- TODO

## Dependencies between families
Which families' results feed into or are prerequisite for which. Use
this to plan which family to push forward first when the backlog is
mixed.

- TODO

## Meta-observations about the research process
Observations about what is and is not working as a research practice
across the project — pipeline ergonomics, decision-policy patterns,
polling cadence, checkpoint-branching discipline, data-generation
reuse. These are meta-hypotheses, not object-level hypotheses about
model behavior.

- TODO
