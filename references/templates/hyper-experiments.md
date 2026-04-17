# {{project_name}} — Hyper-Experiments Project

This file marks the root of a hyper-experiments project. Tooling locates this
project by walking up from the current directory until it finds a
`hyper-experiments.md` file.

## Project
- Name: {{project_name}}
- Created: {{created_at}}
- Description: {{description}}

## Layout
- `experiments/experiments.md` — global research ledger
- `experiments/families/<family>/` — one directory per experiment family
- `experiments/families/<family>/<exp-id>-<slug>/` — a single experiment

## Protocol
This project follows the hyper-experiments skill. Every experiment must declare:
- parentage (parent experiment and/or parent checkpoint),
- a bounded counterfactual delta,
- explicit invariants,
- a measurement plan,
- continue/stop/branch decision criteria.

See the skill's `SKILL.md` for the full protocol.
