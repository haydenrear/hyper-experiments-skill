# {{project_name}} — Hyper-Experiments Project

This file marks the root of a hyper-experiments project. Tooling locates this
project by walking up from the current directory until it finds a
`hyper-experiments.md` file.

## Project
- Name: {{project_name}}
- Created: {{created_at}}
- Description: {{description}}
- Variant: {{variant}}

<!-- `Variant` is the project's default for new experiments. Per-
     experiment variant lives in `code/run_config.json["variant"]`. The
     two valid values today are `default` (PyTorch + tensorboard) and
     `evolve` (an OpenEvolve evolutionary loop, see SKILL.md > Variants).
     Tooling reads this line to pick the right `references/templates/`
     overlay when scaffolding a new experiment. -->


## Layout
- `global-hypothesis.md` — the project-level falsifiable claim every experiment ultimately tests
- `experiments/experiments.md` — global research ledger
- `experiments/families/<family>/` — one directory per experiment family
- `experiments/families/<family>/<exp-id>-<slug>/` — a single experiment
- `tools/` — shared tooling used across experiments (scripts, jars,
  launchers, evaluation binaries, etc.). Reference these from an
  experiment's `data/manifest.md`, `run.md`, or `index.md` using a path
  relative to this file.

## Global hypothesis
The project's falsifiable claim lives in [`global-hypothesis.md`](./global-hypothesis.md). Every experiment references it. See `SKILL.md` > "Chain of reasoning".

## Protocol
This project follows the hyper-experiments skill. Every experiment must declare:
- a type (`root` or `iteration`),
- an anchor (the empirically-viable parent it is built on; `null` only for roots),
- a bounded counterfactual delta (the iteration — what changed vs. the anchor),
- a primary hypothesis (why we think the delta will work, framed in terms of the global hypothesis),
- pre-declared falsifiers (observations that would rule the primary hypothesis out),
- explicit invariants,
- a measurement plan,
- continue/stop/branch decision criteria.

See the skill's `SKILL.md` for the full protocol.
