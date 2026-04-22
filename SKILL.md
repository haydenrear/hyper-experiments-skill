---
name: hyper-experiments
description: Use this skill when the user is planning, running, polling, evaluating, or extending machine learning experiments — especially when the question involves comparing a training run to a parent run or checkpoint (hyperparameter sweeps, ablations, branching from a checkpoint, LR/schedule tweaks, architecture or loss variations). Treat every experiment as a counterfactual claim relative to an ancestor, with explicit lineage, a bounded change set, declared invariants, a measurement plan, and decision criteria. Trigger on phrases like "run an experiment", "branch from checkpoint", "try lower LR", "ablation", "hyperparameter sweep", "continue training from", or when the user references an `experiments/` tree, a TensorBoard run, or poll/decision language.
---

# Hyper-Experiments Skill

## Purpose

This skill defines how to create, run, monitor, evaluate, and extend machine learning experiments as first-class lineage objects.

The core idea is that an experiment is not merely a run. An experiment is a **counterfactual claim relative to an ancestor**.

A child experiment may inherit:
- a parent experiment,
- a parent checkpoint,
- a copied code snapshot,
- and a bounded change set.

This skill is designed so an LLM can operate the experiment loop with minimal ambiguity, initially even before deep automation exists.

---

## Tooling

Two scaffolding scripts ship with this skill.

### `scripts/init_project.py` — bootstrap a new hyper-experiments project

Lays down the root marker, ledger, and directory scaffold in an existing or new repo.

```bash
python scripts/init_project.py \
    --root /path/to/repo \
    --project-name "my-project" \
    --description "one-line description"
```

Creates:
- `<root>/hyper-experiments.md` — the project marker; used by all other tooling to auto-detect project root,
- `<root>/experiments/experiments.md` — the operational research ledger (backward-looking: active/completed runs, best checkpoints),
- `<root>/experiments/families/` — populated by `new_experiment.py`,
- `<root>/experiments/families/index.md` — cross-family planning index (forward-looking: theories, recommendations, and plans spanning multiple families; see "Index layers" below),
- `<root>/tools/` — shared cross-experiment tooling (see "Shared tools" below),
- `<root>/tools/python_exp/` — a standalone Python package named `python-exp` (importable as `python_exp`) that every experiment depends on via an editable `[tool.uv.sources]` link.

Run this once when starting a new hyper-experiments project. If the user says "set up a hyper-experiments project here", run this script.

### `scripts/new_experiment.py` — create a child experiment

Finds the project root (walks up from `cwd` looking for `hyper-experiments.md`, or use `--experiments-root`), allocates the next `exp-NNNN` id, and stamps out a fully scaffolded experiment directory from `references/templates/`.

```bash
python scripts/new_experiment.py \
    --family q_schedule \
    --title "lower lr after structure formation" \
    --question "Does lowering LR after ckpt-12k preserve sparse structure?" \
    --parent exp-0001 \
    --checkpoint checkpoints/exp-0001/ckpt-step-12000.pt \
    --delta "learning_rate: 3e-4 -> 1e-4" \
    --invariant "dataset unchanged" \
    --invariant "architecture unchanged" \
    --command "python train.py --config configs/exp-0002.yaml --resume ..."
```

Creates `experiments/families/<family>/<exp-NNNN>-<slug>/` containing:

- top-level files: `index.md`, `plan.md`, `run.md`, `results.md`, `hypotheses.md`,
- empty subdirs: `logs/`, `tensorboard/`, `checkpoints/`,
- `code/` — standalone **uv project** with a `pyproject.toml` named `<exp-id>-<slug>`; drop the experiment's code snapshot in here and run `uv sync` to reproduce its environment,
- `artifacts/` — `AGENTS.md` (agent instructions) + `memory.md` (cross-session scratch memory),
- `data/` — `manifest.md` (dataset schema with references), `generation-scripts/`, `generated/`.

Also creates `experiments/families/<family>/index.md` on first use of a new family.

The script enforces the lineage object model but does *not* fill in decision criteria, key signals, or the measurement plan — those require human judgment. After scaffolding, complete `plan.md` and `index.md`, then add a row to `experiments/experiments.md` under "Active experiments".

### `scripts/branch_experiment.py` — branch (deep-copy) an experiment

Where `new_experiment.py` scaffolds a child from templates,
`branch_experiment.py` creates a child by **deep-copying an existing
experiment**, rewriting the identity, and stamping a branch-provenance
record into the new `index.md`. Use it when the child should start from
the parent's actual implementation state — custom code in `code/`, any
`vendored/` shared library, the parent's exact `run_config.json`
hyperparameters — rather than from fresh templates.

```bash
python scripts/branch_experiment.py \
    --from exp-0003 \
    --title "drop weight decay" \
    --question "Does removing WD hurt val loss?" \
    --delta "weight_decay: 0.1 -> 0.0" \
    --invariant "LR schedule unchanged"
    # optional:
    # --family q_schedule        # defaults to source's family
    # --parent exp-XXXX          # defaults to --from
    # --checkpoint <path>
    # --ancestor <exp-id>
    # --command "..."
```

Copied verbatim from the source:

- `code/` tree in full (including `vendored/` if the source was already frozen),
- `data/generation-scripts/`,
- `data/manifest.md`,
- `code/run_config.json` — merged through the template so name-bearing
  slots (`experiment_id`, `slug`, `run_name`, `logging.wandb.run_name`,
  `logging.wandb.tags`) are rewritten for the child and every other
  hyperparameter is inherited byte-for-byte. The script emits the same
  rename report as `new_experiment.py`.

Rewritten in place in the copied tree:

- `code/pyproject.toml` `name` and `description` fields (the project
  name must match `<exp-id>-<slug>`).

Generated fresh from templates, with the child's identity and a
populated **Branch provenance** block:

- `index.md`, `plan.md`, `run.md`, `results.md`, `hypotheses.md`,
- `artifacts/AGENTS.md`, `artifacts/memory.md`.

Left empty:

- `logs/`, `tensorboard/`, `checkpoints/`, `data/generated/`.

What the script **does not** touch:

- `code/run_experiment.py` and `code/check_regressions.py` docstrings
  (they may still reference the source's id/title — the branch report
  reminds the operator to review them).

#### Branch vs. scaffold — which to use

| Use `new_experiment.py` when… | Use `branch_experiment.py` when… |
|---|---|
| The parent is another experiment in principle only; the child's code comes from templates or a separate snapshot. | The child should start from the parent's actual `code/` contents (custom modifications, vendored library, frozen deps). |
| The counterfactual delta is a hyperparameter that fits in `run_config.json` and `plan.md`. | The counterfactual delta is a small edit on top of the parent's exact implementation. |
| You are starting a new family or a fresh line of inquiry. | You are iterating within an existing line where the parent's code state is the baseline. |

#### Chain-of-custody note

A copied `vendored/` captures the **source's** freeze, not the child's.
The child must still perform its own freeze procedure (see
`references/chain-of-custody.md`) before launch: verify that
`code/vendored/python_exp/` is the version this experiment intends to
be pinned to, and fill in the `Freeze` block in the child's `run.md`.
The branch report prints this reminder explicitly.

#### Branch provenance in `index.md`

Every experiment's `index.md` carries a `## Branch provenance` block:

- for a scaffolded experiment: `Branched from: null` / `Branched at: null`,
- for a branched experiment: the source id, the ISO timestamp of the
  branch action, and the list of paths copied from the source.

`parent_experiment` (conceptual lineage) is separate from
`branched_from` (physical deep-copy source). They are usually the same
id, but `branched_from` may differ when a child is branched from a
sibling for code convenience while its counterfactual parent is
elsewhere — the branch provenance block documents that distinction.

### `scripts/check_regressions.py` — test shared tools against every experiment's contract

Walks every experiment under `experiments/families/` and runs its
`code/check_regressions.py` (the `check-regressions` console script)
against the CURRENT `tools/python_exp/`, force-installing it over any
vendored copy inside each experiment's venv. Reports which experiments
would break if re-vendored against the current shared library.

```bash
python scripts/check_regressions.py
```

Exit code is 0 only if every experiment passes. Run this after editing
anything in `tools/python_exp/` and before updating a frozen
experiment's vendoring.

### `scripts/check_disk.py` — disk report + pre-launch gate

Reports total / used / free on the filesystem hosting the project,
per-experiment footprint (`checkpoints/`, `tensorboard/`,
`data/generated/`), and tiered pruning candidates. Used both as an
ad-hoc diagnostic and as a mandatory pre-launch gate:

```bash
# Diagnostic — show the report.
python scripts/check_disk.py

# Pre-launch gate — exit non-zero if less than N GiB free.
python scripts/check_disk.py --needed-gb 50
```

Pruning candidates are emitted in three tiers ordered by safety:

1. **Tier 1 — safe.** `planned` experiments with stray
   `checkpoints/`, `tensorboard/`, or `data/generated/` content (the
   experiment has not launched, so its on-disk state is not yet frozen).
2. **Tier 2 — safe if cold-archived.** `archived` experiments'
   checkpoints. These can be moved to cold storage (not deleted)
   without breaking chain of custody, *provided* the move is documented
   in the experiment's `run.md` under a `Cold Storage` block so the
   next operator knows where the checkpoint tree lives.
3. **Tier 3 — requires waiver.** `running` / `stopped` / `completed`
   experiments. Pruning their checkpoints violates chain-of-custody
   Rule 4 ("existing checkpoints are immutable") and must be an
   explicit, documented deviation — never a silent cleanup.

The script **never deletes anything**: it prints paths and the commands
the operator would run. Actual deletion or archival is a manual,
operator-driven step, because the right call depends on cross-family
context the script cannot see (e.g. whether the experiment appears in
`experiments.md`'s "Best parent checkpoints" list).

### `tb-query` — query TensorBoard event files from the CLI

`tb-query` (installed at `/usr/local/bin/tb-query`; source:
https://github.com/Alir3z4/tb-query) is the default lens for inspecting
an experiment's TensorBoard event files during polling and post-run
analysis. It emits JSON, so its output is consumable both by humans and
by the LLM operating the experiment loop — prefer it over spinning up a
full `tensorboard` server when a single numeric answer will do.

Subcommands (run `tb-query <cmd> --help` for the authoritative flags):

- `tb-query find <dir>` — list every event file under a directory.
- `tb-query tags <event_file> [--filter <substr>]` — list scalar tags, optionally filtered.
- `tb-query query <event_file> [--tags <tag>...] [--start_step N] [--end_step N]` — dump scalar values as JSON.
- `tb-query stats <event_file> --tags <tag>...` — min/max/mean/std per tag.
- `tb-query steps <event_file> --tags <tag>...` — the step indices each tag was written at.
- `tb-query correlation <event_file> <tags> [--start_step N] [--end_step N] [--display-interpretation BOOL] [--rounding N]` — scalar-to-scalar correlation between tags.

Typical usage at each poll (see "Polling protocol" below):

```bash
EXP=experiments/families/<family>/<exp-id>-<slug>
EVT=$(tb-query find "$EXP/tensorboard" | head -1)

tb-query tags  "$EVT" --filter loss --filter grad_norm
tb-query stats "$EVT" --tags train/loss --tags val/loss --tags grad_norm
tb-query query "$EVT" --tags val/loss --start_step <last_poll_step>
```

For counterfactual comparison against a parent or sibling, run the same
`query` / `stats` against the ancestor's event file and diff the two
JSON blobs — this is how `delta_val_loss_vs_parent` and friends (see
"Counterfactual comparison signals") are computed when no automated
derived metric exists yet.

`tb-query` is a system-wide read-only CLI: it only reads event files and
never mutates the experiment, so it is **not** part of the measured
system and is not subject to the chain-of-custody vendoring rules in
`references/chain-of-custody.md`. However, if a specific `tb-query`
version produced a number that ends up in `results.md` (especially
`correlation` output), record the version alongside the number so the
analysis itself stays reproducible.

### Templates

Concrete markdown templates used by both scripts live in `references/templates/`:

- `hyper-experiments.md` — project marker
- `experiments.md` — root operational ledger
- `families-index.md` — cross-family strategy index (rendered to `experiments/families/index.md`)
- `family-index.md` — per-family strategy index (rendered to `experiments/families/<family>/index.md`)
- `experiment-index.md` — per-experiment `index.md`
- `plan.md`, `run.md`, `results.md`, `hypotheses.md` — the required experiment files
- `artifacts-agents.md`, `artifacts-memory.md` — rendered to `artifacts/AGENTS.md` and `artifacts/memory.md`
- `manifest.md` — rendered to `data/manifest.md`

Templates use `{{var}}` substitution. Edit them in place to customize the scaffolded output for a given project.

---

## Core principles

1. **Every experiment must be legible as a counterfactual**
   - The child must declare what changed relative to the parent.
   - The child must declare what stayed invariant.

2. **Checkpoint inheritance is first-class**
   - Hyper-experiments should usually branch from meaningful checkpoints rather than restart from scratch when the question is local to an established training regime.

3. **Experiments are lineage objects**
   - Each experiment belongs to a family.
   - Each experiment may have descendants.
   - Parent/child relationships must be recorded explicitly.

4. **Every experiment must define a measurement plan**
   - Metrics are not optional.
   - Continue/stop/branch criteria are not optional.

5. **Every experiment produces hypotheses**
   - The point of a run is not only a curve, but an explanatory update to the research space.

6. **Every experiment updates the research ledger**
   - Findings must be written back into the experiment tree and root experiment index.

7. **Chain of custody is preserved at all times**
   - A launched experiment must reproduce the same result every time it is re-run, forever.
   - Shared code, shared scripts, and external state must be vendored into the experiment before launch so that updates to `tools/` never silently invalidate a historical experiment.
   - See [`references/chain-of-custody.md`](references/chain-of-custody.md) for the full six-rule policy.

---

## Definitions

### Project
The overall research program.

### Experiment family
A line of inquiry sharing a common question or mechanism.

Examples:
- q_schedule
- attention_sparsity
- hyperbolic_kv_pruning
- graph_embedding_losses

### Experiment
A concrete run configuration with:
- identity,
- intent,
- lineage,
- change set,
- command,
- measurement plan,
- decision policy,
- artifacts,
- results,
- hypotheses.

### Parent experiment
The experiment from which the current experiment conceptually descends.

### Parent checkpoint
The checkpoint artifact from which the current experiment begins execution.

### Counterfactual child experiment
A child experiment that differs from its parent by a declared bounded set of changes.

### Invariants
Declared properties that must remain fixed so the counterfactual remains interpretable.

### Observation
A measured result, trend, anomaly, or qualitative note from the run.

### Hypothesis
An explanatory claim induced from observations.

### Decision
The judgment made at a poll or at the end of the run:
- continue,
- stop,
- checkpoint-and-branch,
- archive.

---

## Required experiment object model

Every experiment must be representable by the following conceptual schema:

```yaml
experiment:
  id: exp-XXXX
  family: family_name
  title: short_title
  status: planned | running | stopped | completed | archived

  research_question: >
    What are we trying to learn?

  lineage:
    parent_experiment: exp-YYYY | null
    parent_checkpoint: checkpoint_name | null
    ancestor_baseline: exp-ZZZZ | null

  counterfactual:
    change_set:
      - key: old_value -> new_value
    invariants:
      - invariant_1
      - invariant_2

  mechanism:
    expected_effect: >
      Why this change might matter mechanistically.

  implementation:
    command: >
      Exact command to run
    code_changes:
      - file: path
        modification: description
        reason: description

  measurement_plan:
    metrics:
      - metric: train/loss
        why: primary optimization signal
        expected_direction: down
      - metric: val/loss
        why: generalization signal
        expected_direction: down

  decision_policy:
    continue_if:
      - condition
    stop_if:
      - condition
    branch_if:
      - condition

  outputs:
    experiment_dir: path
    tensorboard_logdir: path
    checkpoints_dir: path
```

---

## Counterfactual rule

An experiment is only valid if it clearly states:

1. **What changed**
2. **What stayed fixed**
3. **What checkpoint or ancestor it is compared against**
4. **Why the change is being tested**

Bad example:

* "Try another run with some tweaks"

Good example:

* "Branch from `exp-0007` at checkpoint `ckpt-step-12000`; lower learning rate from `3e-4` to `1e-4`; keep dataset, tokenizer, architecture, seed policy, and eval suite fixed; test whether post-structure-formation low LR preserves sparsity and improves validation stability."

---

## Required directory structure

The experiment tree should be organized like this:

```text
hyper-experiments.md
tools/
  python_exp/
    pyproject.toml
    src/
      python_exp/
        __init__.py
experiments/
  experiments.md
  families/
    index.md
    <family_name>/
      index.md
      <experiment_id>-<slug>/
        index.md
        plan.md
        run.md
        results.md
        hypotheses.md
        code/
          pyproject.toml
          run_experiment.py
          run_config.json
          check_regressions.py
        logs/
        tensorboard/
        checkpoints/
        artifacts/
          AGENTS.md
          memory.md
        data/
          manifest.md
          generation-scripts/
          generated/
```

`artifacts/` holds agent-facing material (instructions and cross-session
scratch memory) for whichever LLM or agent is operating the experiment.

`data/` holds this experiment's datasets *and* pointers to datasets owned by
other experiments — see "Data manifest and references" below. The `data/`
subtree is always created even if the experiment produces no new data; in
that case the manifest simply references what it inherits.

A family directory may contain many sibling experiments. A child experiment must point back to its parent.

---

## Index layers

Planning and orchestration happen at three layers. Each layer has a
different scope, a different update cadence, and a different reader.
Do not merge them: collapsing any two into one produces a document
that is either too noisy to plan from or too abstract to act on.

### Layer 1 — Operational ledger: `experiments/experiments.md`

Backward-looking. What was run, what is running, what finished, which
checkpoints are strong branching points. One row per experiment. This
is the source of truth for questions like "what is exp-0042's status?"
or "what are our active experiments this week?"

Update cadence: every time an experiment's status changes (launched,
stopped, completed, archived) and every time a checkpoint is promoted
to a strong branching point.

### Layer 2 — Cross-family index: `experiments/families/index.md`

Forward-looking, project-wide strategy. Theories, config
recommendations, and plans that span more than one family.
Meta-observations about the research process itself. The answer to
"what have we learned across the whole project?" and "which family
should we invest in next?"

Update cadence: when a result in one family affects another, when a
cross-family theory crystallizes or falls, when a new family is
proposed.

### Layer 3 — Per-family index: `experiments/families/<family>/index.md`

Forward-looking, scoped to one family. The theory of the family —
what the family currently believes, what configs have proved robust,
which experiments are proposed next, which open questions remain. The
answer to "what should the next experiment in this family look like?"

Update cadence: every time an experiment in the family finishes, every
time a new proposed experiment is born or retired, every time a theory
in the family is strengthened or weakened.

### Distinction from per-experiment files

Per-experiment `plan.md`, `results.md`, and `hypotheses.md` are scoped
to a single experiment and are frozen with the experiment. The index
layers live *above* individual experiments and evolve continuously as
new evidence accumulates. When an experiment's `hypotheses.md` produces
a hypothesis that matters to the family, promote it into the family
index; when it matters across families, promote it into the cross-
family index.

### LLM rule

After updating `results.md` and `hypotheses.md` for a finishing
experiment, the LLM must also:

1. append the one-line finding to the "Experiments in this family"
   table in the family's `index.md`,
2. revisit the family's "Working theories", "Config recommendations",
   and "Proposed future experiments" lists and update each one
   affected by the new result,
3. ask whether any of those updates also belong in the cross-family
   `families/index.md`, and promote them if so.

Updating only `experiments/experiments.md` without touching the two
strategy layers is an incomplete close-out.

---

## Required files per experiment

### `index.md`

The canonical identity and lineage record.

Must include:

* experiment ID,
* family,
* title,
* status,
* parent experiment,
* parent checkpoint,
* parent directory,
* branch provenance (`branched_from`, `branched_at`, list of files copied — `null` when scaffolded from templates rather than branched; see `scripts/branch_experiment.py`),
* research question,
* counterfactual delta,
* invariants,
* command,
* decision policy,
* key signals,
* artifact paths.

### `plan.md`

The experiment design document.

Must include:

* research question,
* expected mechanism,
* code changes,
* measurement plan,
* decision criteria,
* risks,
* comparison targets.

### `run.md`

Append-only run journal.

Must include:

* launch metadata,
* poll-by-poll observations,
* decisions at each poll,
* rationale for continue/stop/branch.

### `results.md`

Summary of actual observations.

Must include:

* primary outcomes,
* secondary outcomes,
* anomalies,
* comparison against parent or sibling,
* whether the intended effect appeared.

### `hypotheses.md`

Post-run explanatory claims.

Must include:

* mechanistic hypotheses,
* empirical hypotheses,
* operational hypotheses,
* recommended next experiments.

### `artifacts/AGENTS.md` and `artifacts/memory.md`

`AGENTS.md` carries this experiment's agent operating instructions: role,
preferred tools/scripts, boundaries, and handoff notes. `memory.md` is the
agent's cross-session scratch pad — facts, gotchas, and pointers that don't
belong in the chronological `run.md` or the post-run `results.md`.

### `code/` — standalone uv project linked to `python_exp`

Each experiment's `code/` directory is its own **uv project** with a
`pyproject.toml` whose project name is `<experiment_id>-<slug>`. It
depends on `python-exp` (the shared library at `tools/python_exp/`)
through `[tool.uv.sources]` as an editable install, using a path relative
to `code/`:

```toml
[project]
dependencies = ["python-exp"]

[tool.uv.sources]
python-exp = { path = "../../../../../tools/python_exp", editable = true }
```

The scaffolder also writes `code/run_experiment.py` exposing a
`run-experiment` console script wired up under `[project.scripts]`, so a
freshly scaffolded experiment is immediately runnable.

The purpose is reproducibility of individual experiments across time:

* going back to a 6-month-old experiment and running
  `uv sync && uv run run-experiment` inside its `code/` must produce a
  working environment without pulling in newer dependency versions chosen
  by a sibling experiment,
* shared library code lives in one place (`tools/python_exp/`) and every
  experiment picks it up as an editable dependency — so improving a
  shared helper does not require copy-edits across experiments,
* if the counterfactual delta includes a dependency change
  (library version bump, new dep), that change is visible in this
  `pyproject.toml` and is part of the declared delta.

Treat `code/pyproject.toml` as part of the experiment's frozen state after
launch, the same way the code snapshot itself is frozen.

### `code/check_regressions.py` — contract assertions against `python_exp`

The scaffolder also writes a `check_regressions.py` module at the root
of `code/`, exposed as a console script `check-regressions`. Its job is
to assert this experiment's contract against `python_exp`: every symbol
imported, every behavioral invariant the experiment relies on.

It complements, rather than replaces, chain-of-custody vendoring:

* **vendoring** makes the frozen experiment reproduce identically
  forever against its own copy of `python_exp`,
* **`check_regressions.py`** tells us whether the experiment's contract
  is still satisfied by the *current* shared library — i.e. whether it
  would be safe to re-vendor this experiment against a newer
  `tools/python_exp/`, or whether a recent shared-library change has
  broken an old experiment's expectations.

When invoked locally (`uv run check-regressions`) it runs against
whatever `python_exp` is installed in this experiment's venv
(vendored if frozen, editable link if still planning). When invoked
by the project-wide runner `scripts/check_regressions.py`, the current
root `tools/python_exp/` is force-installed into the venv first, so the
contract is evaluated against the current shared library regardless of
freeze status.

Keep each experiment's `check_regressions.py` cheap to run (seconds,
not minutes): the project-wide runner invokes every experiment's check
in sequence and is meant to be usable after every non-trivial edit to
`tools/python_exp/`. Do not load checkpoints or large datasets here.

### `code/run_config.json` — parent-aware inheritance

This is the machine-readable configuration consumed by
`run_experiment.py`. Every experiment has one. When a child is
scaffolded, `run_config.json` is *inherited from the parent*, not
rendered fresh: the child starts with every hyperparameter the parent
was running with, and only the name-bearing slots are rewritten to
match the child.

The inheritance algorithm is:

1. Load the `run_config.json` template (which has `{{placeholder}}`
   strings at every name-bearing slot: `experiment_id`, `slug`,
   `family`, `run_name`, `logging.wandb.run_name`, `logging.wandb.tags`,
   and so on).
2. Load the parent's `run_config.json`.
3. Walk the template. Wherever it holds a placeholder string, the
   child's rendered value replaces whatever the parent had. Everywhere
   else, the parent's value is inherited verbatim.
4. Any keys present only in the parent (hyperparameters the operator
   added after the parent was scaffolded) are kept as-is.
5. Any keys present only in the template but not in the parent are
   added to the child with rendered values.

The scaffolder prints a **rename report** after creating the child:

```
run_config.json: inherited from experiments/families/.../code/run_config.json.
  Name-bearing fields updated for this experiment:
    - experiment_id: "exp-0001" -> "exp-0002"
    - run_name: "exp-0001-lower-lr" -> "exp-0002-lr-drop"
    - logging.wandb.run_name: "exp-0001-lower-lr" -> "exp-0002-lr-drop"
  Remaining hyperparameters were inherited verbatim.
  Before launch, cross-check every inherited value against this
  experiment's counterfactual delta and update run_config.json for
  anything that is part of the declared delta.
```

The report doubles as a prompt for the operator / LLM: it enumerates
exactly what was rewritten (so none of those renames slips past review),
and it reminds the reader that *inherited hyperparameters are the
ancestor's choices, not this experiment's counterfactual*. Any
hyperparameter listed in the child's counterfactual delta must be
updated in `run_config.json` before launch, or the experiment is a
clone of its parent rather than a child of it.

Special cases:

* If the child has no parent, the template is rendered fresh.
* If the parent has no `run_config.json` (e.g. it was a first-pass
  experiment scaffolded before this feature existed), the template is
  rendered fresh for the child and the report says so.

After launch, `run_config.json` is **frozen** together with everything
else under `code/` (see chain-of-custody). If a follow-up experiment
needs a different configuration, it should be a new child — not an
edit to a launched experiment's config.

### `data/manifest.md`

The data schema for this experiment. It declares:

* generated datasets produced under `data/generated/`,
* generation scripts under `data/generation-scripts/` that produced them,
* references to datasets and scripts owned by other experiments.

All reference paths in `manifest.md` are resolved **relative to the
hyper-experiments project root** (the directory containing
`hyper-experiments.md`). This makes references stable across families and
across experiments, and avoids duplicating data on disk.

---

## Data manifest and references

Each experiment owns the datasets it generates, and points at everything
else. Downstream experiments do not copy ancestor data — they reference it
through `data/manifest.md`. This keeps data ownership single-sourced and
keeps the experiment tree cheap to branch.

### Ownership rule

An experiment **owns** a dataset when that dataset was physically produced
by a script under its own `data/generation-scripts/` and written to its own
`data/generated/`. An experiment **references** a dataset when it reads
data that another experiment owns.

### Reference resolution

Every path in a `References` section of a `manifest.md` is interpreted
relative to the project root (the directory containing
`hyper-experiments.md`). For example:

```
experiments/families/q_schedule/exp-0003-lr-drop/data/generated/train.parquet
```

Tooling and agents should walk up from the current experiment to find the
project root (the same walk the scaffolding scripts use) and resolve the
reference from there. This works whether the referenced experiment lives in
the same family or a different one.

### When to reference vs. regenerate

Reference when:

* the ancestor dataset is fixed and the child's counterfactual does not
  touch data generation,
* reproducing the ancestor's pipeline would be expensive.

Regenerate (own a fresh dataset) when:

* the counterfactual delta includes the data pipeline itself
  (tokenizer change, filtering change, new sampling distribution),
* the ancestor's dataset is no longer considered valid.

### Script inheritance

Generation scripts can also be referenced from the manifest. A child
experiment that wants to rerun the same pipeline under a tweaked config
should reference the parent's script rather than copying it, and record
the config delta in its `plan.md`.

---

## Shared tools

`<root>/tools/` holds tooling that is **shared across experiments** and
**not specific to any one experiment's counterfactual**. It contains:

* `tools/python_exp/` — a standalone Python package, the canonical home
  for shared functions and modules imported by experiments,
* any other shared assets (jars, external binaries, bash/CLI wrappers,
  dataset inspection utilities, etc.).

### `tools/python_exp` — the shared Python library

`tools/python_exp/` is itself a uv/setuptools project:

```
tools/python_exp/
  pyproject.toml    # project name: "python-exp"
  src/
    python_exp/     # import name
      __init__.py
```

Every experiment's `code/pyproject.toml` depends on `python-exp` via an
editable `[tool.uv.sources]` path. Concretely: when an experiment runs
`uv sync`, uv installs `tools/python_exp/` in editable mode into the
experiment's virtual environment, so `import python_exp` resolves to the
currently-checked-out shared code.

Put shared functions here as soon as more than one experiment needs them.
Prefer adding to `python_exp` over vendoring helpers into an individual
experiment's `code/`.

### What belongs in `tools/` but **not** in `python_exp`

* non-Python assets (jars, binaries, shell scripts, Dockerfiles),
* Python tools that should stay isolated from the shared library
  (e.g. a heavyweight eval suite with conflicting deps) — those can
  live in their own subproject under `tools/<name>/` with their own
  `pyproject.toml`.

### What does **not** belong in `tools/` at all

* an experiment's own generation pipeline — that belongs in
  `<experiment>/data/generation-scripts/`,
* the code snapshot being trained — that belongs in `<experiment>/code/`,
* one-off analysis scripts tied to a single experiment.

### Reference resolution

Paths pointing into `tools/` from inside an experiment (from
`manifest.md`, `run.md`, `plan.md`, or `index.md`) are resolved relative
to the hyper-experiments project root, the same way dataset references
are. Example:

```
tools/eval/run_probe_suite.py --checkpoint ...
```

### LLM rule

When the operator introduces shared Python functionality, put it in
`tools/python_exp/src/python_exp/` — never vendor a copy into an
experiment's `code/`. For non-Python shared tooling, drop it under
`tools/` from the start rather than inside the experiment that first
needed it. Moving a tool out of an experiment later breaks references in
that experiment's `manifest.md` and `run.md`, and breaks `uv sync` for
any experiment whose `[tool.uv.sources]` paths change.

---

## Running an experiment

From the hyper-experiments project root:

```bash
uv sync  --project experiments/families/<family>/<exp-id>-<slug>/code
uv run   --project experiments/families/<family>/<exp-id>-<slug>/code run-experiment
```

Or from inside the experiment's `code/` directory:

```bash
uv sync
uv run run-experiment
```

The experiment's pyproject declares an editable dependency on
`tools/python_exp/` via `[tool.uv.sources]`, so `run-experiment` and any
shared imports resolve to the currently-checked-out shared library
without a separate install step.

---

## TensorBoard logging

Experiments log observations as TensorBoard event files under
`<experiment>/tensorboard/`. Those event files are the single source of
truth for run metrics — poll inspection via `tb-query`, post-run
analysis, and counterfactual comparison against a parent all read from
them — so writing them correctly and consistently matters more than
which framework produced the numbers.

### Library choice

Each experiment's `code/pyproject.toml` pins:

```toml
dependencies = [
  "python-exp",
  "torch==2.11.0",
  "tensorboard>=2.17,<3",
]
```

- `tensorboard` pins the on-disk event file format. This is what
  `tb-query` and any shared analysis helpers read, so the writer and
  reader need a consistent version.
- `torch.utils.tensorboard.SummaryWriter` is the default writer,
  wired up in the scaffolded `run_experiment.py`. Its API
  (`add_scalar` / `add_histogram` / `add_text`) is identical to
  `tensorboardX.SummaryWriter`, so experiments that do not depend on
  torch can swap `torch` for `tensorboardX>=2.6.2` in both the
  dependency list and the import line without changing any call
  sites.
- Do not mix writer families (e.g. `tensorflow.summary` in one
  sibling, `torch.utils.tensorboard` in another) inside a family.
  Drift in dtype handling, step indexing, and tag namespacing makes
  parent/child comparisons quietly unreliable.

### Writer setup

The scaffolded `code/run_experiment.py` reads the log directory from
`run_config.json` and opens a `SummaryWriter`:

```python
from torch.utils.tensorboard import SummaryWriter

def make_writer(config: dict) -> SummaryWriter:
    logdir = (Path(__file__).parent / config["paths"]["tensorboard"]).resolve()
    logdir.mkdir(parents=True, exist_ok=True)
    tb_cfg = config.get("logging", {}).get("tensorboard", {})
    return SummaryWriter(
        logdir=str(logdir),
        flush_secs=tb_cfg.get("flush_secs", 30),
        max_queue=tb_cfg.get("max_queue", 100),
    )
```

`config["paths"]["tensorboard"]` defaults to `../tensorboard`, which
resolves to `<experiment>/tensorboard/` — exactly where
`tb-query find "$EXP/tensorboard"` expects event files. Do not
override this path per experiment; the directory name is part of the
skill's contract with `tb-query` and with the expected experiment
layout. If a run produces multiple event streams (e.g. train vs. eval),
use subdirectories *under* `tensorboard/` (`tensorboard/train/`,
`tensorboard/eval/`) rather than moving the root.

### Tag naming

Tag names across siblings are what make `tb-query query`-based
parent/child diffs meaningful. A child that logs `training_loss` while
its parent logged `train/loss` is not comparable without translation.

Use the tag names declared under "Standard metric categories" verbatim
(`train/loss`, `val/loss`, `grad_norm`, `activation_entropy/layer_4`,
etc.). For per-layer or per-head metrics, use the `/` hierarchy
(`grad_norm_by_layer/layer_0`, `head_selectivity/layer_4_head_3`) so
`tb-query tags --filter grad_norm_by_layer` groups them cleanly.

If a new tag is needed that is not already in "Standard metric
categories", add it there (PR to the skill, not just to one
experiment) so future siblings log it under the same name.

### Flush cadence and polling

`flush_secs=30` fits the default 3–4 minute polling cadence: scalars
land on disk and become visible to `tb-query` within seconds of being
logged, and the writer does not hold enough data in memory to lose
meaningful state on a hard crash.

If the experiment writes scalars at sub-second cadence, raise
`max_queue` rather than lowering `flush_secs` — flushing too often
fragments event files and slows `tb-query find` on long runs. Conversely,
for very long background jobs where polling is infrequent, raising
`flush_secs` to a few minutes is fine so long as crash recovery is not
a concern.

### Live dashboard (optional)

For visual inspection during a run, start a local TensorBoard server
against the experiment's log directory:

```bash
uv run --project experiments/families/<family>/<exp-id>-<slug>/code \
    tensorboard --logdir experiments/families/<family>/<exp-id>-<slug>/tensorboard
```

The LLM should default to `tb-query` instead of the dashboard (see
"Polling protocol") — but the dashboard is the right tool when a
human is eyeballing training dynamics that are hard to summarize as
scalars (loss landscape shape, histogram drift, image samples).

### Chain of custody

`tensorboard` and `tensorboardX` are Python dependencies of each
experiment's `code/` and are therefore captured by `uv.lock` inside the
experiment's vendored environment at launch time. Re-running a frozen
experiment reinstalls the exact pinned versions, so the event files
produced on re-run match the ones produced at launch. This is the
reason the pins live in `code/pyproject.toml` rather than in
`tools/python_exp/` — the writer is part of the measured system,
whereas `tb-query` (a pure reader of already-written files) is not.

---

## Root operational ledger

The file `experiments/experiments.md` is the project-level operational
ledger — Layer 1 of the three-layer index model (see "Index layers"
above). It is backward-looking and authoritative for the *state* of
experiments. Forward-looking strategy (theories, config recommendations,
proposed experiments) lives in `experiments/families/index.md` and
`experiments/families/<family>/index.md`, not here.

`experiments.md` must include:

### Experimental protocol

The operating protocol for all experiments.

### Families

A list of experiment families — names and one-line characterizations.
The strategic state of each family lives in its own `index.md`.

### Active experiments

A table with:

* id,
* family,
* parent,
* status,
* question,
* command,
* directory.

### Completed experiments

A table with:

* id,
* result,
* main finding,
* next action.

### Best parent checkpoints

A table with:

* checkpoint,
* experiment,
* reason it is a strong branching point.

### Meta-hypotheses across families

A running summary of reusable conclusions from the full experiment
graph. This overlaps with the cross-family index — treat this section
as the curated, ledger-grade short list (findings strong enough to make
planning decisions from), and let the cross-family index hold the
working, forward-looking version.

---

## Chain of custody

A launched experiment must reproduce the same result every time it is
re-run — including six months later when a new mechanistic
interpretability tool is applied to its checkpoints. The scaffolded
project is ergonomic (shared library, editable install, data references
across experiments), but that ergonomics is a **liability** for old
experiments: if `tools/python_exp/` or an ancestor's generation script
is updated after an experiment has been launched, re-running that
experiment silently measures a different system.

The full policy lives at `references/chain-of-custody.md`. The short
version:

1. **Self-containment.** Every launched experiment must be reproducible
   from only its own `code/`, `data/`, and `checkpoints/`, plus any
   frozen ancestor data it explicitly references.

2. **Vendor shared code before launch.** Before marking the experiment
   `running`, copy `tools/python_exp/` into
   `<experiment>/code/vendored/python_exp/` and rewrite
   `code/pyproject.toml`:

   ```toml
   [tool.uv.sources]
   python-exp = { path = "./vendored/python_exp" }
   ```

   Drop the `editable = true` flag. Do the same for any other shared
   tool (binary, jar, CLI) the experiment calls directly.

3. **Vendor shared generation scripts.** If the manifest references a
   generation script owned by another experiment, copy it into this
   experiment's `data/generation-scripts/` and rewrite the manifest
   entry. Referencing another experiment's **generated data** (output,
   not script) is allowed only if that ancestor is itself frozen.

4. **Freeze means frozen.** After launch, `code/`, `data/generation-
   scripts/`, `data/generated/`, and existing checkpoints do not
   change. Corrections are expressed as child experiments, not
   edits.

5. **Shared tools evolve freely for future experiments.** Updates to
   `tools/python_exp/` benefit every experiment launched after the
   update. Experiments launched before the update are untouched
   because they vendored the old version.

6. **Record the freeze.** Fill in the `Freeze` block in `run.md` at
   launch time — what was vendored, when, what SHAs, any deviation from
   the shared version. Without this block the chain of custody cannot be
   audited.

### LLM rule

When asked to launch an experiment, the LLM must refuse to proceed until
`code/vendored/` is populated, `[tool.uv.sources]` points inside the
experiment, every manifest script reference is local, and the `Freeze`
block in `run.md` has been filled in. "Editable link works on my
machine" is not a valid reason to skip the freeze.

---

## Git discipline

Chain of custody keeps the **contents of an experiment directory**
stable over time. Git keeps the **history of the research tree as a
whole** stable over time — ledger updates, family-index edits,
cross-family theory revisions, shared-library evolution. They are
complementary, and both are required: a project can have perfectly
frozen experiments but no audit trail for the decisions that shaped
them, or a pristine git log but mutating experiment directories. Neither
alone is sufficient.

### Mandatory commit points

Every experiment requires at least **two commits**, one at launch and
one at finish:

#### 1. Pre-launch commit — "freeze committed"

After the freeze procedure (step 6 of the standard workflow) and before
the first `run-experiment` invocation:

```bash
git add experiments/families/<family>/<exp-id>-<slug>/
git commit -m "[<exp-id>] freeze: scaffold + vendored tools"
```

This snapshot is the **reproducible-on-disk state** the launch is
measured against. The commit SHA goes into `run.md`'s Launch block as
`code snapshot`. If the experiment needs to be re-run six months later
and chain of custody held, `git checkout <sha>` restores the exact tree
that produced the original numbers.

#### 2. Post-finish commit — "ledger + strategy updated"

After step 11 (update ledger and strategy indexes):

```bash
git add experiments/experiments.md \
        experiments/families/index.md \
        experiments/families/<family>/index.md \
        experiments/families/<family>/<exp-id>-<slug>/results.md \
        experiments/families/<family>/<exp-id>-<slug>/hypotheses.md \
        experiments/families/<family>/<exp-id>-<slug>/run.md
git commit -m "[<exp-id>] complete: <one-line finding>"
```

This commit captures the write-back of findings into the research tree:
the ledger row, the family theory update, the cross-family promotion (if
any). Without it, a future reader can see the frozen experiment but not
how the project's understanding moved because of it.

### Optional intermediate commits

Commit intermediate state when it is useful to preserve a particular
moment in the experiment's history — for example:

* after a mid-run poll decision to checkpoint-and-branch (so the
  branching point is visible in `git log --all`),
* after promoting a checkpoint to "best parent" in
  `experiments.md`,
* after a significant edit to `tools/python_exp/` that you want to
  ship alongside the experiment that motivated it (commit the tooling
  edit **separately** from the experiment's own commits — different
  scope, different message).

Intermediate commits are never a substitute for the two mandatory ones.

### Commit message convention

Prefix every experiment-scoped commit with the experiment id in
brackets: `[exp-0042] ...`. This makes `git log --grep='\[exp-0042\]'`
reproduce the full history of a single experiment in one line.

Reserved verbs:

* `scaffold` — created by `new_experiment.py` or `branch_experiment.py`,
* `freeze` — vendored + ready to launch,
* `poll N: <decision>` — a mid-run checkpoint,
* `complete` — finished, ledger + strategy indexes updated,
* `archive` — moved to archived status (late cleanup; uncommon).

Cross-family or project-wide changes (shared library edits, new family
bootstrap, ledger schema changes) carry their own scope prefix
(`[tools]`, `[ledger]`, `[family:<name>]`) so they do not pollute the
per-experiment log.

### Relationship to chain of custody

A git commit is **not** a substitute for vendoring. A frozen experiment
must still be self-contained on disk: re-running it should not require
re-reading the git log. But the commit history is what makes the
evolution of the **project** — which ideas were tried, which worked,
which were abandoned — legible months or years later, in a way that the
per-experiment files alone cannot capture.

### LLM rule

When asked to launch an experiment, the LLM must also refuse to proceed
unless the freeze commit has been made (or will be made as the final
step before launch). When asked to finish an experiment, the LLM must
include the post-finish commit as part of the close-out, not leave it
for the operator to remember.

---

## Disk hygiene

ML experiments are disk-expensive: checkpoints and TensorBoard event
files accumulate quickly, and a launch that fails mid-training because
the volume filled up is both a wasted run and an active chain-of-
custody risk (a half-written checkpoint is worse than no checkpoint at
all — the experiment cannot be re-run cleanly, and the missing late-
stage state is not visible in the frozen artifact).

Treat disk the way you treat git: check it on a rhythm, not only when
it breaks.

### Pre-launch disk check — mandatory

Before every launch, run:

```bash
python scripts/check_disk.py --needed-gb <expected-footprint-plus-margin>
```

`<expected-footprint-plus-margin>` is the operator's honest estimate of
how much the upcoming run will write to disk (checkpoints over the
full training budget, TensorBoard scalars at the chosen flush cadence,
any generated data the run will produce) plus a safety margin — at
least 20% on top, more if the volume is shared with other users.

The script exits non-zero if free space is below the stated need. The
standard workflow (step 8) treats a non-zero exit as a hard refusal to
launch: fix the disk situation first, then re-run the check.

### What to prune — tiered by chain-of-custody risk

When the pre-launch check fails, or as routine hygiene, prune by
tier — always starting with the safest one. `check_disk.py` prints the
candidates in each tier and the paths/commands to act on.

**Tier 1 — safe.** `planned` experiments with stray content under
`checkpoints/`, `tensorboard/`, or `data/generated/`. These are the
remains of a smoke-run or an aborted draft; the experiment has not
launched yet, so nothing in the tree is frozen. Deletion is safe and
does not require any documentation.

**Tier 2 — safe if cold-archived.** `archived` experiments'
checkpoint trees. Archived experiments are unlikely to be branched
from again, so moving their checkpoints to cold storage reclaims space
without invalidating the historical measurement. But **move, do not
delete**: cold storage means the bits still exist somewhere
retrievable, and the move must be recorded in the experiment's
`run.md` under a `Cold Storage` block naming the new location and the
timestamp. Future operators must be able to rehydrate the checkpoint
tree if a new interpretability tool demands it.

**Tier 3 — requires chain-of-custody waiver.** `running`, `stopped`,
or `completed` experiments' checkpoint trees. Pruning these violates
chain-of-custody Rule 4 ("existing checkpoints are immutable").
Acceptable only as an explicit, documented deviation: the operator
adds a `Chain-of-custody deviation` block to `run.md` naming what was
pruned, why, and what reproducibility the experiment loses as a
consequence. Prefer branching a fresh experiment over pruning an old
one.

Do not prune Tier 3 silently. A checkpoint that disappears without a
deviation record is indistinguishable from a corrupted or lost one,
and the experiment's reproducibility story is permanently damaged.

### What check_disk cannot see

The script looks only at filesystem sizes and per-experiment `Status:`
lines. It does **not** know which checkpoints appear in
`experiments.md`'s "Best parent checkpoints" table, nor which are
referenced by other experiments' `data/manifest.md` as frozen ancestor
artifacts. Before acting on any Tier 2 or Tier 3 proposal, cross-check
the candidate against:

* `experiments/experiments.md` — Best parent checkpoints table,
* every experiment's `data/manifest.md` — referenced frozen-ancestor
  datasets and checkpoints.

If the candidate appears in either, do not prune.

### LLM rule

When asked to launch an experiment, the LLM must:

1. run `scripts/check_disk.py --needed-gb <estimate>` before the launch
   command,
2. refuse to proceed if the script exits non-zero,
3. propose Tier 1 → Tier 2 → Tier 3 pruning candidates from the
   script's output, in that order, with the chain-of-custody
   implications stated for each,
4. wait for the operator to act on the proposal before retrying the
   disk check.

The LLM must not delete or move anything itself without explicit
operator approval for the specific path.

---

## Standard workflow

When asked to run an experiment, follow this workflow exactly.

### 1. Define or select the parent

Identify:

* parent experiment,
* parent checkpoint if one exists,
* relevant ancestor baseline.

If the question is local to a known training regime, prefer branching from an existing checkpoint.

### 2. Define the counterfactual delta

Declare:

* exact change set,
* invariants,
* why this is a meaningful comparison.

Keep the change set bounded. Avoid changing many variables unless the purpose is explicitly exploratory.

### 3. Identify implementation changes and command

Specify:

* the files to modify,
* the modifications required,
* the exact command to run.

### 4. Define the measurement plan

Identify:

* required metrics,
* any new TensorBoard signals that must be added,
* expected direction of movement,
* what comparisons matter.

### 5. Materialize the experiment

Create a new experiment directory.
Copy the relevant code snapshot into `code/`.
Write:

* `index.md`
* `plan.md`
* `run.md`
* `results.md`
* `hypotheses.md`

The child `index.md` must point to its parent.

### 6. Freeze (chain of custody)

Before launching, vendor every piece of shared state the experiment
depends on:

* copy `tools/python_exp/` into `<experiment>/code/vendored/python_exp/`
  and rewrite `[tool.uv.sources]` in `code/pyproject.toml` to point at
  `./vendored/python_exp` without `editable = true`,
* copy any shared non-Python tool (binary, jar, CLI) the experiment
  will invoke into the experiment's own tree,
* copy any generation script referenced from another experiment into
  `data/generation-scripts/` and rewrite `data/manifest.md`,
* run `uv sync && uv run run-experiment` inside `code/` to confirm the
  frozen experiment is self-reproducible,
* fill in the `Freeze` block in `run.md` (paths, SHAs, timestamp).

Do not proceed to step 7 until the freeze block is filled in.

### 7. Commit the frozen scaffold

Before the first `run-experiment` invocation, commit the frozen
experiment directory so the exact on-disk state that is about to be
launched is captured in git:

```bash
git add experiments/families/<family>/<exp-id>-<slug>/
git commit -m "[<exp-id>] freeze: scaffold + vendored tools"
```

Record the resulting commit SHA in `run.md`'s Launch block as
`code snapshot`. See "Git discipline" above for the full policy.

Do not proceed to step 8 until the freeze commit lands.

### 8. Run the experiment

First, the pre-launch disk gate (see "Disk hygiene" above):

```bash
python scripts/check_disk.py --needed-gb <expected-footprint-plus-margin>
```

If the script exits non-zero, do not launch. Prune Tier 1 / Tier 2
candidates (and Tier 3 only with a documented waiver), then re-run the
check. The LLM must refuse to proceed while the gate is red.

Then launch the command and record:

* timestamp,
* host,
* command,
* git commit or code snapshot identity (from the freeze commit in
  step 7),
* parent checkpoint used,
* `check_disk.py` output at launch time — paste the "Free" line into
  `run.md`'s Launch block so the starting disk state is part of the
  audit trail.

### 9. Poll the experiment

Poll on a fixed cadence.

At each poll:

* inspect TensorBoard metrics,
* compare against decision criteria,
* compare against parent or sibling trajectories where relevant,
* decide whether to continue, stop, or branch.

Record each poll in `run.md`.

### 10. Finish the experiment

When the run is done or stopped:

* summarize the results,
* generate hypotheses,
* determine whether the original expectation was supported, weakened, or contradicted.

### 11. Update the ledger and strategy indexes

Update all three index layers (see "Index layers" above):

* the child experiment directory (`results.md`, `hypotheses.md`),
* the parent experiment if descendant notes are relevant,
* `experiments/experiments.md` — append the completed row, update best
  checkpoints if applicable,
* `experiments/families/<family>/index.md` — append the one-line
  finding, update working theories, config recommendations, proposed
  future experiments, and open questions,
* `experiments/families/index.md` — only when the new result affects
  cross-family theories or recommendations.

Include in `experiments.md`:

* command run,
* result summary,
* hypotheses,
* recommended next experiments,
* pointer to experiment directory and TensorBoard log.

### 12. Commit the results

Close the experiment with a single commit that bundles the write-back
into the research tree:

```bash
git add experiments/experiments.md \
        experiments/families/index.md \
        experiments/families/<family>/index.md \
        experiments/families/<family>/<exp-id>-<slug>/results.md \
        experiments/families/<family>/<exp-id>-<slug>/hypotheses.md \
        experiments/families/<family>/<exp-id>-<slug>/run.md
git commit -m "[<exp-id>] complete: <one-line finding>"
```

See "Git discipline" above. The LLM must not leave this commit for the
operator to remember — it is part of finishing the experiment, not an
optional cleanup.

### 13. Promote promising checkpoints

If the experiment produced a useful regime, mark its checkpoint as a
strong future parent candidate. If this adds a row to
`experiments.md`'s "Best parent checkpoints" table after step 12,
commit that edit separately: `[<exp-id>] promote checkpoint`.

---

## Polling protocol

Each experiment must define a polling cadence. Default: every 3 to 4 minutes unless a different cadence is more appropriate.

Use `tb-query` (see "Tooling" above) to pull the metrics below directly
from the experiment's TensorBoard event files rather than eyeballing a
live dashboard — its JSON output is easier to diff against the parent's
signals and easier for the LLM to reason about between polls.

At each poll, inspect:

1. **Primary optimization metrics**

   * train/loss
   * val/loss
   * task-specific score

2. **Stability metrics**

   * grad_norm
   * layerwise grad/activation norms
   * NaN indicators
   * optimizer anomalies

3. **Mechanistic metrics**

   * sparsity
   * entropy
   * effective rank
   * drift
   * q parameters
   * structural probes

4. **Operational metrics**

   * throughput
   * step time
   * memory use

At the end of each poll, explicitly record one of:

* continue,
* early stop,
* checkpoint-and-branch,
* abort.

Do not merely describe metrics. Make a decision.

---

## Decision policy

Every experiment must define:

### Continue criteria

Examples:

* validation trend improves,
* no instability spikes,
* structural signal moves in predicted direction,
* compute efficiency remains acceptable.

### Stop criteria

Examples:

* divergence,
* persistent degradation over multiple polls,
* collapse of intended mechanism,
* redundant with a sibling run,
* exhausted budget with weak signal.

### Branch criteria

Examples:

* promising intermediate regime detected,
* instability appears local and correctable,
* one hyperparameter appears especially sensitive,
* a specific checkpoint should be forked into multiple children.

---

## Standard metric categories

Each experiment should log both task metrics and mechanistic metrics whenever possible.

### Core optimization signals

* `train/loss`
* `val/loss`
* `train/perplexity`
* `lr`
* `grad_norm`
* `weight_norm`
* `update_norm`
* `tokens_per_second`
* `step_time_ms`

### Stability signals

* `grad_norm_by_layer/*`
* `activation_norm_by_layer/*`
* `nan_count`
* `loss_spike_indicator`
* `optimizer_state_norm/*`

### Generalization signals

* `heldout_eval/*`
* `ood_eval/*`
* `probe_accuracy/*`
* `fewshot_probe/*`

### Structure and mechanism signals

* `activation_entropy/*`
* `attention_sparsity/*`
* `head_selectivity/*`
* `effective_rank/*`
* `sv_spectrum/*`
* `representation_drift/*`
* `cluster_agreement/*`
* `routing_entropy/*`
* `residual_energy_ratio/*`
* `q_value/*`

### Counterfactual comparison signals

When possible, compute comparisons against parent or sibling experiments:

* `delta_val_loss_vs_parent`
* `delta_ood_score_vs_parent`
* `delta_sparsity_vs_parent`
* `improvement_per_compute`
* `improvement_per_step`

If exact derived metrics do not yet exist in code, manually compute or narrate them in results until automation is available.

---

## Required hypothesis types

Every finished experiment must produce at least three types of hypotheses.

### Mechanistic hypothesis

Why the change affected internal behavior.

Example:

* Lowering learning rate after checkpoint 12k preserved sparse head specialization by reducing late destructive updates.

### Empirical hypothesis

What will likely happen in similar future runs.

Example:

* In this family, phase-dependent LR reduction is more promising than using a uniformly low LR from step 0.

### Operational hypothesis

How the experiment process itself should change.

Example:

* Future branches should fork from the onset of representation stabilization rather than rerunning full training.

---

## Templates

Concrete markdown templates for every required file live in `references/templates/` and are used by `scripts/new_experiment.py` and `scripts/init_project.py`:

- `hyper-experiments.md` — project marker placed at the repo root
- `experiments.md` — operational ledger at `<root>/experiments/`
- `families-index.md` — cross-family strategy index at `<root>/experiments/families/index.md`
- `family-index.md` — per-family strategy index at `<root>/experiments/families/<family>/index.md`
- `experiment-index.md` — rendered to each experiment's `index.md`
- `plan.md`, `run.md`, `results.md`, `hypotheses.md` — per-experiment files
- `artifacts-agents.md` → `artifacts/AGENTS.md`
- `artifacts-memory.md` → `artifacts/memory.md`
- `manifest.md` → `data/manifest.md`
- `code-pyproject.toml` → `code/pyproject.toml`
- `code-run-experiment.py` → `code/run_experiment.py`
- `code-run-config.json` → `code/run_config.json` (with parent-aware inheritance; see below)
- `code-check-regressions.py` → `code/check_regressions.py`
- `tools-python-exp-pyproject.toml` → `tools/python_exp/pyproject.toml` (written by `init_project.py`)
- `tools-python-exp-init.py` → `tools/python_exp/src/python_exp/__init__.py` (written by `init_project.py`)

See the "Required files per experiment" section above for the content each scaffolded stub must grow into before launch.

Supported `{{var}}` substitutions: `experiment_id`, `slug`, `title`, `family`, `status`, `created_at`, `research_question`, `parent_experiment`, `parent_checkpoint`, `parent_directory`, `ancestor_baseline`, `counterfactual_delta`, `invariants`, `command`, `branched_from`, `branched_at`, `branch_copied_files`, `project_name`, `description`.

Not every template uses every variable; templates not touched by a given
variable pass it through untouched.

To customize the scaffolded output for a project, edit the template files in place. To extend the `{{var}}` set, update `scripts/_lib.py` and the relevant CLI args in `scripts/new_experiment.py`.

---

## How to treat hyper-experiments

A hyper-experiment is not a separate kind of object. It is simply a child experiment whose purpose is to explore a local change around an existing parent checkpoint.

Examples:

* same experiment, lower LR,
* same experiment, different q schedule,
* same experiment, different regularizer weight,
* same experiment, different projection head,
* same experiment, different eval probe.

The key requirement is that the hyper-experiment must explicitly declare:

* the parent checkpoint,
* the bounded change set,
* the preserved invariants.

---

## Checkpoint policy

Prefer checkpoint branching when:

* the question concerns late-stage behavior,
* the relevant regime already exists,
* the difference is localized,
* restarting from scratch would waste compute or muddy the comparison.

Prefer fresh baselines when:

* the full training trajectory is part of the question,
* the changed parameter affects early representation formation,
* the parent checkpoint is too specialized to be a fair ancestor.

Useful checkpoints should be promoted in `experiments.md` under best parent checkpoints.

---

## LLM operating rules

When using this skill, the LLM must:

1. refuse to treat an experiment as valid until parentage, delta, invariants, and measurement plan are clear,
2. prefer bounded counterfactuals over vague multi-change runs,
3. prefer checkpoint branching for local questions,
4. always specify the command,
5. always specify the metrics to harvest,
6. always record poll-by-poll decisions,
7. always write back results and hypotheses,
8. always update the root ledger.

The LLM must not:

* silently change multiple important variables without declaring them,
* run experiments without a comparison target,
* omit decision criteria,
* omit lineage.

---

## First implementation guidance

When automation is still minimal, the experimenter may perform some steps manually, but the structure must remain the same.

At minimum, the LLM should still:

* create the natural-language experiment spec,
* define the measurement plan,
* specify code edits,
* define decision criteria,
* maintain lineage documents,
* generate post-run hypotheses.

This allows the research process to start before the full infrastructure is built.

---

## Example

````md
# Experiment Spec

## Identity
- Experiment ID: exp-0002-lr-drop-from-exp-0001-ckpt12000
- Family: q_schedule
- Title: lower lr after structure formation
- Status: planned

## Research question
- Does lowering LR after checkpoint 12k preserve useful sparse structure and improve validation stability?

## Parentage
- Parent experiment: exp-0001-baseline
- Parent checkpoint: ckpt-step-12000
- Ancestor baseline: exp-0001-baseline

## Counterfactual delta
- learning_rate: 3e-4 -> 1e-4

## Invariants
- dataset unchanged
- architecture unchanged
- tokenizer unchanged
- eval suite unchanged
- seed policy unchanged

## Expected mechanism
- Lower LR after structure formation may reduce destructive late-stage updates while preserving specialized structure.

## Command
```bash
python train.py --config configs/exp-0002.yaml --resume checkpoints/exp-0001/ckpt-step-12000.pt
```

## Code changes

* file: train.py
  modification: add TensorBoard logs for representation_drift and effective_rank
  reason: compare child behavior against parent beyond task loss

## Signals to log

* metric: val/loss
  why: primary generalization signal
  expected direction: down
* metric: attention_sparsity/head_*
  why: test whether sparse structure is preserved
  expected direction: stable or improved
* metric: representation_drift/*
  why: detect destructive late-stage movement
  expected direction: reduced

## Continue criteria

* validation trend improves over parent continuation
* no instability spikes
* structure metrics remain healthy

## Stop criteria

* worse than parent continuation across 3 polls
* divergence or structural collapse

## Branch criteria

* if sparsity improves but validation stalls, branch on regularizer weight

## Polling notes

* cadence: every 4 minutes
* inspect loss, sparsity, drift, throughput, and stability

## End-of-run questions

* Did lower LR help late-stage behavior?
* Did it preserve specialized structure?
* Is LR the right control variable, or should q schedule be branched next?
````

---

## Final rule

The purpose of this skill is not merely to run experiments. The purpose is to build an evolving, explicit, legible **graph of counterfactual knowledge** over model behavior.

Every experiment should leave behind:
- a reproducible artifact,
- a lineage position,
- a measured result,
- and a sharper theory.
