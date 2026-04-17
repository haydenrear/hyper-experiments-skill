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
- `<root>/experiments/experiments.md` — the global research ledger,
- `<root>/experiments/families/` — empty, populated by `new_experiment.py`.

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

Creates `experiments/families/<family>/<exp-NNNN>-<slug>/` containing `index.md`, `plan.md`, `run.md`, `results.md`, `hypotheses.md`, and empty `code/`, `logs/`, `tensorboard/`, `checkpoints/`, `artifacts/` subdirectories. Also creates `experiments/families/<family>/index.md` on first use of a new family.

The script enforces the lineage object model but does *not* fill in decision criteria, key signals, or the measurement plan — those require human judgment. After scaffolding, complete `plan.md` and `index.md`, then add a row to `experiments/experiments.md` under "Active experiments".

### Templates

Concrete markdown templates used by both scripts live in `references/templates/`:

- `hyper-experiments.md` — project marker
- `experiments.md` — root research ledger
- `family-index.md` — per-family index
- `experiment-index.md` — per-experiment `index.md`
- `plan.md`, `run.md`, `results.md`, `hypotheses.md` — the required experiment files

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
experiments/
  experiments.md
  families/
    <family_name>/
      index.md
      <experiment_id>-<slug>/
        index.md
        plan.md
        run.md
        results.md
        hypotheses.md
        code/
        logs/
        tensorboard/
        checkpoints/
        artifacts/
```

A family directory may contain many sibling experiments. A child experiment must point back to its parent.

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

---

## Root experiment ledger

The file `experiments/experiments.md` is the global research ledger.

It must include:

### Experimental protocol

The operating protocol for all experiments.

### Families

A list of experiment families.

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

A running summary of reusable conclusions from the full experiment graph.

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

### 6. Run the experiment

Launch the command and record:

* timestamp,
* host,
* command,
* git commit or code snapshot identity,
* parent checkpoint used.

### 7. Poll the experiment

Poll on a fixed cadence.

At each poll:

* inspect TensorBoard metrics,
* compare against decision criteria,
* compare against parent or sibling trajectories where relevant,
* decide whether to continue, stop, or branch.

Record each poll in `run.md`.

### 8. Finish the experiment

When the run is done or stopped:

* summarize the results,
* generate hypotheses,
* determine whether the original expectation was supported, weakened, or contradicted.

### 9. Update the ledger

Update:

* the child experiment directory,
* the parent experiment if descendant notes are relevant,
* the root `experiments.md`.

Include:

* command run,
* result summary,
* hypotheses,
* recommended next experiments,
* pointer to experiment directory and TensorBoard log.

### 10. Promote promising checkpoints

If the experiment produced a useful regime, mark its checkpoint as a strong future parent candidate.

---

## Polling protocol

Each experiment must define a polling cadence. Default: every 3 to 4 minutes unless a different cadence is more appropriate.

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
- `experiments.md` — global research ledger at `<root>/experiments/`
- `family-index.md` — per-family index
- `experiment-index.md` — rendered to each experiment's `index.md`
- `plan.md`, `run.md`, `results.md`, `hypotheses.md` — per-experiment files

See the "Required files per experiment" section above for the content each scaffolded stub must grow into before launch.

Supported `{{var}}` substitutions: `experiment_id`, `slug`, `title`, `family`, `status`, `created_at`, `research_question`, `parent_experiment`, `parent_checkpoint`, `parent_directory`, `ancestor_baseline`, `counterfactual_delta`, `invariants`, `command`, `project_name`, `description`.

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
