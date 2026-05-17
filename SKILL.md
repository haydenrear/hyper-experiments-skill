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

## Installation & runtime dependencies

This skill is **installable via skill-manager**, which handles both
the CLI dependency (`tb-query`) and the MCP server dependency
(`runpod`) declared in `skill-manager.toml`.

### Recommended install

```bash
RUNPOD_API_KEY=<your-runpod-api-key> skill-manager install hyper-experiments
```

The `RUNPOD_API_KEY=...` prefix is what lets skill-manager auto-deploy
the runpod MCP server at install time — see "Runpod MCP server" below
for the mechanics. If you don't have a RunPod account or don't plan
to use the runpod MCP tools, omit the prefix; the install still
succeeds but runpod is registered without being deployed (you can
deploy it later via `deploy_mcp_server` once a key is available).

### `tb-query` CLI dependency

`tb-query` is the polling-protocol default for inspecting TensorBoard
event files (see "Polling protocol"). The skill declares it as a
`pip:` CLI dep in `skill-manager.toml`, so on
`skill-manager install hyper-experiments`:

- skill-manager bundles `uv` under `$SKILL_MANAGER_HOME/pm/uv/` if
  it isn't already there, then uses it to install `tb-query` into a
  per-skill prefix.
- The binary is symlinked to
  `$SKILL_MANAGER_HOME/bin/cli/tb-query`. Add that directory to your
  PATH or invoke `tb-query` by its absolute path — see
  `<skill-manager-skill>/scripts/env.sh` for the recommended
  PATH-conflict-free pattern.

If you're not using skill-manager and want `tb-query` directly:

```bash
pip install 'tb-query>=2025.11'
# or, with uv:
uv tool install tb-query
```

### Runpod MCP server

The `runpod` MCP server (`@runpod/mcp-server` from npm) ships every
tool in the RunPod REST API as an MCP-callable tool —
`runpod/list-endpoints`, `runpod/get-pod`, etc. See
[`tools/mcp.md`](tools/mcp.md) for the full surface and call
patterns.

**Required environment variable**: `RUNPOD_API_KEY`. Get one from
https://www.runpod.io/console/user/settings.

**How the key reaches the subprocess** — install-time env-init:

1. The skill manifest declares `RUNPOD_API_KEY` as a required+secret
   field in `[[mcp_dependencies]].init_schema`. The actual value is
   never committed.
2. `skill-manager install` scans each MCP dep's `init_schema` against
   the install process's environment. When `RUNPOD_API_KEY` is
   present, it folds into the registration's
   `initialization_params` and counts toward the auto-deploy
   decision.
3. The gateway's `_materialize_client_config` injects values that
   match `init_schema` field names into the spawned subprocess's
   env. So `npx -y @runpod/mcp-server@latest` runs with
   `RUNPOD_API_KEY` set, even though the gateway process itself
   doesn't carry the value.

Practical consequence: prefix the install command with the key
(`RUNPOD_API_KEY=... skill-manager install hyper-experiments`) and
runpod auto-deploys. No follow-up `deploy_mcp_server` call needed.

If runpod is registered but not yet deployed (key wasn't set at
install time, or you want to point the same install at a different
account), call `deploy_mcp_server` via the virtual MCP gateway with
`initialization={"RUNPOD_API_KEY": "..."}`.

### The virtual MCP gateway (what agents see)

Agents installed under this skill don't see runpod directly —
skill-manager fronts every downstream MCP server behind a single
**virtual MCP gateway** entry. Discovery and invocation go through
the gateway's virtual tools (`browse_mcp_servers`,
`browse_active_tools`, `describe_tool`, `invoke_tool`, …). See
[`tools/mcp.md`](tools/mcp.md) for the full agent-facing call
pattern.

---

## Tooling

Two scaffolding scripts ship with this skill.

### `scripts/init_project.py` — bootstrap a new hyper-experiments project

Lays down the root marker, ledger, and directory scaffold in an existing or new repo.

```bash
python scripts/init_project.py \
    --root /path/to/repo \
    --project-name "my-project" \
    --description "one-line description" \
    --variant default              # or `evolve`; sets the project's default
                                   # for new experiments. See "Variants" below.
```

Creates:
- `<root>/hyper-experiments.md` — the project marker; used by all other tooling to auto-detect project root,
- `<root>/experiments/experiments.md` — the operational research ledger (backward-looking: active/completed runs, best checkpoints),
- `<root>/experiments/families/` — populated by `new_experiment.py`,
- `<root>/experiments/families/index.md` — cross-family planning index (forward-looking: theories, recommendations, and plans spanning multiple families; see "Index layers" below),
- `<root>/experiments/baselines/` — cross-family baseline cache (see "Baselines" below),
- `<root>/experiments/baselines/index.md` — append-only listing of cross-family baselines and what produced them,
- `<root>/tools/` — shared cross-experiment tooling (see "Shared tools" below),
- `<root>/tools/python_exp/` — a standalone Python package named `python-exp` (importable as `python_exp`); `new_experiment.py` vendors a snapshot of this into each experiment's `code/vendored/python_exp/` at scaffold time, and `branch_experiment.py` inherits the parent's vendored snapshot. Experiments never depend on `tools/python_exp/` directly.

Run this once when starting a new hyper-experiments project. If the user says "set up a hyper-experiments project here", run this script.

`init_project.py` also drops three project-local scripts:

- `<root>/scripts/new_experiment.py` — wrapper around the skill's `new_experiment.py`,
- `<root>/scripts/branch_experiment.py` — wrapper around the skill's `branch_experiment.py`,
- `<root>/scripts/run_experiments.py` — self-contained project orchestrator with a
  `run_baselines()` hook (see "Baselines" below).

The two wrappers locate the installed skill (via
`$HYPER_EXPERIMENTS_SKILL_HOME` for a dev checkout, otherwise
`$SKILL_MANAGER_HOME/skills/hyper-experiments`, defaulting to
`~/.skill-manager/skills/hyper-experiments`) and delegate to its
`scripts/new_experiment.py:main()` / `scripts/branch_experiment.py:main()`.
Each wrapper has two marked sections in `main()`:

- `# add prep code (before)` — runs before the skill script (validate
  argv, seed defaults, mutate `sys.argv` to inject flags),
- `# add templating code (after)` — runs after the skill script (render
  extra files into the new experiment dir, append to project indexes,
  fire notifications).

Edit those sections in the project to layer in opinionated behavior; do
not mirror the skill's logic in the wrappers. Throughout the rest of
this document, when SKILL.md says "run `python scripts/new_experiment.py`"
inside a hyper-experiments project, the wrapper is what's actually being
invoked, and it forwards to the skill.

`run_experiments.py` is **not** a wrapper — it is a self-contained
template the project edits in place. Its purpose is to host two hook
functions, `run_baselines()` and `run_experiments()`, both of which
are skip-by-default stubs. The skill does not own this file's logic;
fill in the body to match how this project schedules runs.

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
    --command "python train.py --config configs/exp-0002.yaml --resume ..." \
    # --variant evolve              # optional; defaults to the project's
                                    # variant from hyper-experiments.md.
                                    # See "Variants" below.
```

Creates `experiments/families/<family>/<exp-NNNN>-<slug>/` containing:

- top-level files: `index.md`, `plan.md`, `run.md`, `results.md`, `hypotheses.md`,
- empty subdirs: `logs/`, `tensorboard/`, `checkpoints/`,
- `code/` — standalone **uv project** with a `pyproject.toml` named `<exp-id>-<slug>`; drop the experiment's code snapshot in here and run `uv sync` to reproduce its environment,
- `artifacts/` — `AGENTS.md` (agent instructions) + `memory.md` (cross-session scratch memory),
- `data/` — `manifest.md` (dataset schema with references), `generation-scripts/`, `generated/`.

Also creates, on first use of a new family:
- `experiments/families/<family>/index.md` — the family strategy index,
- `experiments/families/<family>/baselines/index.md` — the family baseline cache (see "Baselines" below).

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

Copied from the source:

- `code/` tree in full (including `vendored/` if the source was already frozen),
  with source experiment ids retargeted to the child in copied text files,
- `data/generation-scripts/`, with source experiment ids retargeted in
  copied text files,
- `data/manifest.md`, with source experiment ids retargeted,
- `code/run_config.json` — copied from the source so every hyperparameter
  is inherited byte-for-byte, then retargeted by the same plain text
  search/replace as the rest of the copied tree.

Rewritten in place in the copied tree:

- `code/pyproject.toml` `name` and `description` fields (the project
  name must match `<exp-id>-<slug>`).

Generated fresh from templates, with the child's identity and a
populated **Branch provenance** block:

- `index.md`, `plan.md`, `run.md`, `results.md`, `hypotheses.md`,
- `artifacts/AGENTS.md`, `artifacts/memory.md`.

Left empty:

- `logs/`, `tensorboard/`, `checkpoints/`, `data/generated/`.

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

`tb-query` (source: https://github.com/Alir3z4/tb-query, on PyPI as
`tb-query`) is the default lens for inspecting an experiment's
TensorBoard event files during polling and post-run analysis. It
emits JSON, so its output is consumable both by humans and by the
LLM operating the experiment loop — prefer it over spinning up a
full `tensorboard` server when a single numeric answer will do.

**Where it lives** depends on how you got the skill:

- Installed via `skill-manager install hyper-experiments` →
  `$SKILL_MANAGER_HOME/bin/cli/tb-query` (skill-manager bundles uv
  and installs into a per-skill prefix; symlinks into `bin/cli/`).
  Use `<skill-manager-skill>/scripts/env.sh --skills hyper-experiments`
  for the absolute path that avoids PATH conflicts.
- Installed directly with `pip install tb-query` or
  `uv tool install tb-query` → wherever your Python tool dir puts
  it (e.g. `/usr/local/bin/tb-query` or `~/.local/bin/tb-query`).

See "Installation & runtime dependencies" near the top of this
file for the full skill-manager install story.

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
- `baselines-index.md` — cross-family baseline cache index (rendered to `experiments/baselines/index.md`)
- `family-baselines-index.md` — per-family baseline cache index (rendered to `experiments/families/<family>/baselines/index.md`)
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

8. **Isolate before you scale**
   - When approaching anything non-trivial — a new mechanism, a suspected bug, an unfamiliar interaction — start from a **minimum reproducible example** where the behavior you care about can be verified or ruled out cheaply.
   - From that anchor, climb a **complexity ladder**: each rung adds one piece of complexity toward the real target system.
   - When a rung breaks, the failure is isolated to whatever that rung introduced — you do not have to debug the whole stack.
   - See "Isolation and the complexity ladder" below.

9. **Every experiment lives in a chain of reasoning anchored in a known-working root**
   - Each experiment is either a `root` (an empirically-viable starting point with no anchor) or an `iteration` (built on a parent that is itself a root or a surviving iteration).
   - Every iteration declares a primary hypothesis (why the delta should work, framed in terms of the project's global hypothesis) plus pre-declared falsifiers.
   - The chain is walkable in both directions: walk up to find empirically viable ground after a failure, to localize causes, and to invalidate descendants when an ancestor is later ruled out.
   - This is distinct from chain of *custody* (artifact reproducibility): chain of custody guarantees the numbers reproduce; chain of reasoning guarantees the numbers are interpretable as evidence.
   - See "Chain of reasoning" below.

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

### Global hypothesis
The single project-level falsifiable claim every experiment in the
project is, ultimately, trying to test. Lives in
`<project-root>/global-hypothesis.md`. There is exactly one per
project; families do not have their own.

### Root experiment
An empirically-viable starting point. Has no anchor — it *is* the
anchor for downstream iterations. The first experiment in a project
must be a root; the first experiment of a new family typically is.

### Iteration experiment
Every experiment that is not a root. Built on an anchor (a root, or
another iteration whose primary hypothesis is currently `surviving`),
with a one-line delta, a primary hypothesis, and pre-declared
falsifiers.

### Anchor
The empirically-viable parent an iteration is built on.

### Primary hypothesis
The one-sentence claim an iteration tests, framed as a contribution
toward (or against) the global hypothesis. Distinct from the
mechanistic / empirical / operational sub-hypotheses also recorded in
`hypotheses.md`. Carries a status:
`proposed | under-test | surviving | ruled-out`.

### Falsifier
A pre-declared observation that, if cleanly produced by the run, rules
the primary hypothesis out. A hypothesis without falsifiers cannot be
honestly tested.

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
  type: root | iteration
  status: planned | running | stopped | completed | archived

  research_question: >
    What are we trying to learn?

  lineage:
    parent_experiment: exp-YYYY | null
    parent_checkpoint: checkpoint_name | null
    ancestor_baseline: exp-ZZZZ | null

  reasoning:
    global_hypothesis_ref: <project-root>/global-hypothesis.md
    anchor:
      experiment: exp-YYYY | null      # null only if type=root
      evidence: >
        Specific measured outcome of the anchor that grounds this iteration.
    iteration_delta_oneline: >
      One-line description of the change being tested vs. the anchor.
    primary_hypothesis: >
      Why the delta should work, framed in terms of the global hypothesis.
    falsifiers:
      - observation_that_would_rule_this_out
    hypothesis_status: proposed | under-test | surviving | ruled-out

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

## Chain of reasoning

The counterfactual rule above describes the shape of a single
experiment. The chain of reasoning describes how experiments connect:
every experiment is one link, terminating at the **global hypothesis**
above and at one or more **root experiments** below. Distinct from
chain of *custody* (`references/chain-of-custody.md`) — custody
guarantees the numbers reproduce, reasoning guarantees the numbers are
interpretable as evidence.

### Global hypothesis (per project)

Exactly one global hypothesis per project, in
`<project-root>/global-hypothesis.md` — the falsifiable claim the
whole project is testing (e.g. "configuration shape C is the most
optimal under metric M subject to constraints"). It declares its own
falsifiers up front; we start a project by trying to *falsify* the
global hypothesis, not to confirm it. Families do not have their own
global hypothesis — silently forking it mid-project is goalpost-moving;
declare a new project instead.

### Root vs iteration

Every experiment has a type:

- **Root** — an empirically-viable starting point. Has no anchor; it
  *is* the anchor for downstream iterations. The first experiment in a
  project must be a root, and the first experiment of each new family
  typically is. A root is not speculative — its `hypotheses.md`
  documents what the version is empirically known to do, not what we
  hope it will do. A family may *re-root* if a fundamentally new
  working baseline is established (e.g. a different architecture
  proven viable); the new root is declared explicitly with its own
  evidence, not back-fitted from a failed iteration.
- **Iteration** — every other experiment. Anchored on a parent that
  is itself either a root or an iteration whose primary hypothesis is
  currently `surviving`.

A "let me just see what happens" run is not an iteration; it is a
request to declare a new root with honest "evidence: none, this is a
probe" framing. That is allowed — exploration is allowed — but it must
be done explicitly so the chain is honest about what it is standing on.

### What every iteration declares

1. **Anchor** — pointer to the parent + the *specific measured
   outcome* of the parent that grounds this iteration. "exp-0007
   reached val/loss 0.42 at step 12000 with sparsity preserved" is an
   anchor. "exp-0007 was good" is not.
2. **Iteration** — one-line description of the delta vs. the anchor.
   Same content as the counterfactual change set, said as a single
   sentence.
3. **Primary hypothesis** — one sentence: why this delta should work,
   and how the answer contributes toward (or against) the global
   hypothesis.
4. **Falsifiers** — observations that would rule the primary
   hypothesis out. Declared *before* launch. A hypothesis without
   falsifiers cannot move from `under-test` to `ruled-out`, which
   means it cannot be honestly tested.

These live in the iteration's `hypotheses.md` (live status doc) and
are mirrored in `plan.md`'s "Chain of reasoning" header (pre-launch
declaration).

### Hypothesis lifecycle

A primary hypothesis moves through:

- `proposed` — declared, not yet launched,
- `under-test` — running, results not yet final,
- `surviving` — finished; falsifiers were checked, none triggered,
- `ruled-out` — finished; one or more falsifiers triggered.

Only `surviving` hypotheses are valid anchors for downstream
iterations. A root is `surviving` by construction; if its anchor
evidence is later contradicted, downgrade to `ruled-out` and flag
descendants.

### Walking up the chain

The chain is walkable, and walking it is a standard operating move:

- **For justification (forward)** — to launch an iteration, walk up
  from its anchor to confirm the chain terminates at a root and every
  intermediate link is `surviving`. If any link is `proposed`,
  `under-test`, or `ruled-out`, the iteration is standing on shaky
  ground and the right move is to re-anchor before launching, not to
  proceed.
- **To find ground after a failure** — when an iteration's primary
  hypothesis is `ruled-out`, walk up the anchor chain to the nearest
  `surviving` ancestor (often the root) and branch a new iteration
  from there with what was learned. Do not patch a falsified anchor
  in place.
- **To trace causes** — a failure at depth N tells you something about
  the chain `root → A → B → ... → N`. The diagnostic question is
  *which link introduced the failure mode*; walking up while comparing
  measurements localizes it.
- **For backward invalidation** — if iteration A is later downgraded
  from `surviving` to `ruled-out`, every descendant that anchored on A
  is now standing on invalid ground and must be flagged for
  re-anchoring (typically onto A's parent). The chain isn't only for
  forward justification; it carries invalidation backward too.

### Relationship to the complexity ladder

The complexity ladder (next section) is one shape of chain of reasoning:
rung 0 is a root, each higher rung is an iteration whose delta adds one
piece of complexity. Other chains (parameter sweeps, architecture
variations, schedule variations) follow the same root + iteration +
falsifier discipline with different deltas.

LLM-side enforcement of this discipline lives in "LLM operating rules"
near the bottom of this document.

---

## Isolation and the complexity ladder

The single highest-leverage experimentation move is **isolation**: take
something you believe works (or believe is broken) a particular way,
strip it down to a minimum reproducible example where that behavior can
be verified or ruled out cheaply, and only then start adding complexity
back in. Without an anchor at the bottom of the stack, every failure at
the top is ambiguous — you cannot tell whether the new variable broke
the thing or whether the thing was already broken at the previous level.

Most apparent dead-ends in this project are not "the idea didn't work."
They are "we tried the idea inside a system big enough to hide several
unrelated failures, and we cannot tell which one we are looking at."
The complexity ladder is the discipline that prevents this.

### The minimum reproducible example (rung 0)

Rung 0 is the simplest possible experiment that still expresses the
behavior under investigation. It is **not** a smaller version of the
real run; it is a system small enough that the answer is unambiguous.

Properties a good rung 0 has:

* **Cheap.** A single rung-0 cycle (configure → run → observe →
  decide) should fit inside a poll cadence — minutes, not hours. If
  rung 0 takes a full training run to evaluate, it is too big.
* **Local.** It exercises one mechanism, one data shape, one model
  size, one optimizer, one signal. Everything not under test is set
  to whatever value is least likely to interact with the question.
* **Observable.** The signal that confirms or denies the behavior
  must be readable directly — a printed scalar, a single
  `tb-query stats` line, a unit test exit code. Don't gate rung 0
  on derived metrics that themselves require a working stack.
* **Anchored to a known truth.** Rung 0 verifies *something already
  believed true* — a paper's reported result on a toy task, an
  identity (e.g. zero loss on memorized data), a published
  benchmark, or a reference implementation's output. This is what
  makes it an *anchor*: if rung 0 disagrees with the known truth,
  the framework around the experiment is wrong, not the hypothesis.

The first finding from rung 0 is binary: "the anchor reproduces" or
"the anchor does not reproduce." Until rung 0 reproduces, no higher
rung is interpretable, and the right move is always to fix rung 0
rather than push upward.

### Climbing the ladder

Once rung 0 is green, each subsequent rung introduces **one** piece
of complexity from the gap between rung 0 and the real target system.
Each rung is itself an experiment in this skill's sense: parent =
the previous rung, counterfactual delta = the one piece newly added,
invariants = everything inherited verbatim from the previous rung.

Typical rung-to-rung deltas (project-dependent):

* rung 0 → rung 1: switch from a synthetic toy dataset to a small
  real-data slice, keeping the model and optimizer fixed,
* rung 1 → rung 2: scale the model from "tiny" to "small," keeping
  the data and optimizer fixed,
* rung 2 → rung 3: introduce the optimizer / schedule used in the
  real run, keeping data and model fixed,
* rung 3 → rung N: add the remaining complexity (full data, full
  model, full training budget) one element at a time.

The ladder is **directional**, not exhaustive. Start at rung 0; only
climb to rung N+1 when rung N has produced a clean, interpretable
result. Skipping rungs is the failure mode — it reintroduces the
ambiguity that motivated the ladder in the first place.

### When a rung breaks

If rung N reproduces and rung N+1 does not, the cause is — by
construction — whatever was added between them. This is the entire
payoff of the ladder, and it should be honored:

* **Do not jump back to rung 0** to "rebuild from scratch." The
  isolation already points at the offending delta; debug at rung
  N+1, with rung N as the working reference.
* **Do not climb further.** Higher rungs will only compound the
  ambiguity. Stop, fix, and re-verify rung N+1 before continuing.
* **Record the break in the rung's `results.md`** even if the
  resolution is small: the value of the ladder is the audit trail
  it leaves, not just the eventual green run.

If rung N has been green for a long time and rung N+1 keeps failing
in unrelated ways, suspect that rung N is silently wrong (the anchor
has drifted) and re-verify rung N against its own anchor before
debugging rung N+1 further.

### Mapping the ladder to the experiment tree

Each rung is a concrete experiment under
`experiments/families/<family>/`. The ladder lives in the parent
chain — rung 0 is the family's first experiment, rung 1's parent is
rung 0, and so on. Use `branch_experiment.py` (not
`new_experiment.py`) to create rung N+1 once rung N is launched and
green: the new rung starts from rung N's exact code state, with the
single counterfactual delta layered on top.

The family's `index.md` is the right place to record the ladder
itself — what each rung is supposed to verify, which rungs are
green, where the ladder currently is. A family with a well-curated
ladder section reads, at a glance, as a story of "here is what we
have ruled in, here is what we have ruled out, here is the next
thing we are isolating."

### When *not* to climb a ladder

The ladder is overhead. Skip it when:

* the question is genuinely a tweak inside a regime that has
  already been ladder-validated (a new LR value, a new seed) —
  branch directly from the relevant checkpoint instead,
* the change is mechanical and contained (rename, refactor, log a
  new metric) — chain of custody and a single child experiment are
  enough,
* the cost of the full target run is itself within a poll cadence
  — there is no rung 0 cheaper than the real thing, so the real
  thing *is* rung 0.

The ladder is for when you are crossing a gap of belief: "I think
this mechanism does X" or "I think this bug is in subsystem Y." If
you are not crossing such a gap, do not pay the ladder's cost.

### LLM rule

When a user describes a non-trivial experiment, a suspected
mechanism, or an unfamiliar interaction, the LLM must:

1. ask whether a rung 0 — a minimum reproducible example anchored
   to a known truth — exists or has been built,
2. if not, propose the rung 0 *before* proposing the target
   experiment, and frame the target experiment as a rung-N
   descendant of it,
3. when planning the target, enumerate the intermediate rungs
   (data, model size, optimizer, schedule, full budget) and call
   out which ones the project has already validated and which are
   open,
4. if a result at a high rung is being interpreted, verify that
   the rungs below it are themselves green — do not let an
   ambiguous high-rung result drive a decision on top of an
   un-verified stack.

---

## Required directory structure

The experiment tree should be organized like this:

```text
hyper-experiments.md
scripts/
  new_experiment.py
  branch_experiment.py
  run_experiments.py        # project orchestrator with run_baselines() hook
tools/
  python_exp/
    pyproject.toml
    src/
      python_exp/
        __init__.py
experiments/
  experiments.md
  baselines/                # cross-family baseline cache
    index.md
  families/
    index.md
    <family_name>/
      index.md
      baselines/            # per-family baseline cache
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
checkpoints are strong branching points. One row per experiment, with
the row's *table membership* (Active vs Completed) as the coarse
project-level status signal.

The fine-grained operational status (`planned | running | stopped |
completed | archived`) lives in **one place only**: each experiment's
own `index.md` `Status:` field. The project ledger and family index
do not carry a `status` column — duplicating it invites drift.
`scripts/check_disk.py` reads status from per-experiment `index.md`.

Update cadence:

* When an experiment's operational state changes (launched, stopped,
  completed, archived): update **only** that experiment's `index.md`
  `Status:` field.
* When an experiment finishes: move its row from Active to Completed in
  `experiments.md` (table membership is the project-level status cut).
* When a checkpoint is promoted to a strong branching point: update
  `experiments.md`'s "Best parent checkpoints" table.

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

### `code/` — standalone uv project with vendored `python_exp`

Each experiment's `code/` directory is its own **uv project** with a
`pyproject.toml` whose project name is `<experiment_id>-<slug>`. It
depends on `python-exp` resolved against this experiment's own frozen
copy at `code/vendored/python_exp/`:

```toml
[project]
dependencies = ["python-exp"]

[tool.uv.sources]
python-exp = { path = "./vendored/python_exp" }
```

The vendored copy is populated at scaffold time (see "Chain of custody
> Rule 2"): `new_experiment.py` copies from `tools/python_exp/`,
`branch_experiment.py` inherits the parent's vendored copy via the
deep-copy of `code/`. Experiments are self-contained from the moment
they are created — there is no "still planning, editable link to
shared tools" intermediate state.

The scaffolder also writes `code/run_experiment.py` exposing a
`run-experiment` console script wired up under `[project.scripts]`, so a
freshly scaffolded experiment is immediately runnable.

The purpose is reproducibility of individual experiments across time:

* going back to a 6-month-old experiment and running
  `uv sync && uv run run-experiment` inside its `code/` must produce a
  working environment without pulling in newer dependency versions chosen
  by a sibling experiment,
* shared library code lives in one place (`tools/python_exp/`) but is
  shared *along the lineage chain* — siblings inherit the same
  `python_exp` snapshot via their common branched parent, and updates
  to `tools/python_exp/` benefit only future scaffolds (not past ones,
  by design),
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

When invoked locally (`uv run check-regressions`) it runs against the
`python_exp` vendored at this experiment's `code/vendored/python_exp/`
— the snapshot taken at scaffold time. When invoked by the
project-wide runner `scripts/check_regressions.py`, the current root
`tools/python_exp/` is force-installed into the venv first, so the
contract is evaluated against the current shared library regardless of
the experiment's vendored snapshot.

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

The scaffolder prints a **search/replace report** after creating a
branched child. In copied text files, including JSON treated as text,
`branch_experiment.py` applies this ordered replacement:

1. `exp-0049-old-slug` -> `exp-0050-new-slug`
2. `exp-0049` -> `exp-0050`
3. `old-slug` -> `new-slug`

Generated lineage files (`index.md`, `plan.md`, `run.md`, and branch
provenance) are rendered fresh and are not swept, so they can still say
the child was branched from `exp-0049`.

```
run_config.json: copied from experiments/families/.../code/run_config.json and swept as text.

Search/replace report:
  - code/run_config.json:
      id+slug: 'exp-0001-lower-lr' -> 'exp-0002-lr-drop' (2 replacements)
      id: 'exp-0001' -> 'exp-0002' (4 replacements)
      slug: 'lower-lr' -> 'lr-drop' (1 replacement)
  - code/run_experiment.py:
      id: 'exp-0001' -> 'exp-0002' (1 replacement)

  Inherited verbatim — audit each (keep | override | delete):
    - learning_rate                     0.0003
    - weight_decay                      0.1
    - logging.tensorboard.flush_secs    30
    - hyperparameters.warmup_steps      500
    ...

  Next: write your decisions into plan.md's '## Inherited config audit'
  block before the freeze commit. Hyperparameters listed in the
  counterfactual delta must be overridden in run_config.json now —
  inherited values are the SOURCE's choices, not this experiment's.
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

#### Inherited config audit — the housekeeping ritual

Inheritance is the right default — it keeps the parent's working
hyperparameters in scope and makes the child's counterfactual delta
the only thing the operator has to reason about. But it has a known
failure mode: parent-specific cruft accumulates silently across
generations, and the next agent who reads the config has to spelunk
through every field to figure out which ones are load-bearing and
which were inherited from a five-generations-ago ancestor for a reason
no one remembers. **The config becomes a sink.**

The fix is *attention, not auto-prune*. Neither `new_experiment.py`
nor `branch_experiment.py` deletes inherited fields — deletion is too
dangerous, because a "weird" inherited param often turns out to be
load-bearing in a way the child's operator does not yet appreciate.
Instead, the scaffolders surface audit blocks in their prompt return,
and the operator (or the LLM acting on their behalf) treats those
blocks as **work to do before the freeze commit**, not
informational noise:

1. **Identity rewrites applied** — every name-bearing field the
   script updated automatically. For `branch_experiment.py`, this is a
   plain text search/replace over copied files, and the report lists
   each file plus the replacement counts. If a retargeted copied string
   was intentionally parent-facing, restore it explicitly and record why.
2. **Source identity strings applied** — copied arbitrary strings that
   contain the source's `exp-NNNN`, source slug, or
   `exp-NNNN-source-slug` identity are retargeted automatically. The
   point is that plain strings like `exp-0049` are not missed.
3. **Inherited verbatim — audit each (keep | override | delete)** —
   every key the child took from the parent without any rewrite. The
   operator decides per key:
   - **keep** — the value still applies to this experiment,
   - **override** — this hyperparameter is part of the counterfactual
     delta and the new value goes in now,
   - **delete** — the parent had this for a parent-specific reason
     that does not apply here; remove the key so the config does not
     carry forward dead weight.

The audit is recorded inline in the child's `plan.md` under an
`## Inherited config audit` block — a short table of `key → decision
→ rationale`. The block is part of the experiment's frozen state, so
six months later a reader can see not just what hyperparameters the
experiment ran with, but which ones the operator *deliberately* kept
versus inherited without thought.

The freeze gate is what makes this stick: an experiment may not be
launched until the audit block is filled in for every entry the
scaffolder surfaced. Skipping the audit and committing a config full
of unexamined parent cruft is a chain-of-custody failure for the same
reason a missing freeze block is — the artifact no longer documents
what was actually intended to be measured.

##### LLM rule

When the LLM runs `new_experiment.py` or `branch_experiment.py`, it
must:

1. read the audit blocks in the prompt return as a *task list*, not
   informational output,
2. for each search/replace entry, confirm the copied reference should
   be child-facing; if a copied reference should remain parent-facing,
   restore it explicitly and record why,
3. for each "Inherited verbatim" key, propose `keep | override |
   delete` with a one-line rationale, and apply the decision to
   `run_config.json` directly,
4. write the resulting decisions into `plan.md`'s `## Inherited
   config audit` block before proposing the freeze commit,
5. refuse to proceed to launch while any audit entry is unresolved.

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

Every experiment's `code/pyproject.toml` depends on `python-exp` via a
`[tool.uv.sources]` path pointing at the experiment's own vendored
copy (`./vendored/python_exp`). When an experiment runs `uv sync`, uv
installs that vendored copy into the experiment's virtual environment,
so `import python_exp` resolves to the snapshot taken at scaffold time
— not whatever `tools/python_exp/` happens to be now. Edits to
`tools/python_exp/` benefit only experiments scaffolded *after* the
edit; existing experiments must be re-vendored to pick them up.

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

## Baselines

Baselines are reusable comparison points — a reference model's
evaluation, a constant predictor's score, a vanilla fine-tune's loss
curve, the metrics frozen out of an ancestor checkpoint. They are
**expensive to compute and cheap to reuse**, so the project caches
them once and references them many times.

The single most important rule about baselines:

> **A baseline that has already been computed should be reused, not
> re-run.** Every `run_baselines()` hook in this skill defaults to
> *skip* by design — leaving it as a no-op is the path of least
> resistance, which keeps baseline regeneration deliberate and pushes
> the project toward running as few baselines as possible.

### Three scopes, with a promotion path

Baselines live at three scopes, ordered by reuse priority:

1. **Cross-family** — `<root>/experiments/baselines/`.
   Created by `init_project.py`. Anything filed here is valid for
   experiments in any family.
2. **Per-family** — `<root>/experiments/families/<family>/baselines/`.
   Created by `new_experiment.py` / `branch_experiment.py` the first
   time a family is touched. Valid for any experiment in that family.
3. **Per-experiment** — produced by an individual experiment's
   `code/run_experiment.py` `run_baselines()` hook (see below). Lives
   inside the experiment's own tree.

A baseline is **promoted** as need rises: it starts inside an
experiment, moves to its family's `baselines/` once a sibling needs
it, and moves to `experiments/baselines/` once a second family needs
it. A baseline is **demoted** out of a scope only when no remaining
experiment at that scope references it.

Each scope has an `index.md` whose contract is the same: append-only,
one entry per baseline, every entry naming what it measures, what
produced it (experiment id or external pipeline), the produced-at
timestamp + commit SHA, the artifact paths, and which experiments use
it.

### `run_baselines()` hook — two layers

Both runners — the project-wide `scripts/run_experiments.py` and each
experiment's `code/run_experiment.py` — expose a `run_baselines()`
function that defaults to skip:

- **Project layer** (`<root>/scripts/run_experiments.py`,
  `run_baselines(root)`) — produces *shared* baselines that multiple
  experiments will compare against. Fill in to (re)compute a baseline
  that does not already exist under `experiments/baselines/` or
  `experiments/families/<family>/baselines/`.
- **Experiment layer** (`<exp>/code/run_experiment.py`,
  `run_baselines(config)`) — produces baselines specific to a single
  experiment. Fill in only when the experiment genuinely needs a
  baseline that does not yet exist at any scope.

Both layers print a "skipped" message when not filled in. That message
is the signal that everything downstream is reusing cached baselines —
do not silence it without a reason.

### Chain-of-custody

A baseline's artifacts are immutable once any experiment references
them. If the underlying computation needs to change, file a *new*
baseline (with a distinct name) and supersede the old entry in the
relevant `index.md` — never edit a baseline in place. This is the
same principle as chain-of-custody for experiment checkpoints: a
referenced artifact may be promoted or retired, but never silently
mutated.

### LLM rule

Before adding a fresh baseline computation to any `run_baselines()`
function, the LLM must:

1. read the cross-family `experiments/baselines/index.md`,
2. read the relevant family's `experiments/families/<family>/baselines/index.md`,
3. only propose adding a new baseline if neither index already lists
   one that satisfies the experiment's comparison need,
4. when a new baseline is justified, propose it at the *highest*
   scope a second consumer is plausible at — produce-once-reuse-many
   beats produce-many-times.

### Baseline cache — content-addressed lookup (design sketch)

> Status: **design sketch, not yet implemented.** This subsection
> describes the mechanism so a future implementation has a fixed
> contract to land against, and so the LLM can reason about
> baselines as cache-addressable artifacts rather than free-text
> entries that may or may not already exist.

The append-only `index.md` files described above are the audit
trail; reading them is what an LLM must do today. But discipline
alone fails across many prompts — an LLM working inside a single
experiment's `run_baselines()` is exactly the place where "did we
already compute this?" gets forgotten, and the baseline silently
gets re-run. The cure is to make the question mechanical: hash the
*identity inputs* of a baseline computation, look up the hash in
known cache locations, and only fall through to computation on a
miss.

#### `baselines.config` — the input spec

Each `run_baselines()` call site declares one or more
`baselines.config` entries. A single entry has the shape:

```jsonc
{
  "name": "vanilla-lm-1.3b-on-c4-128k-tokens",      // human-readable label
  "produces": ["val_loss", "val_perplexity"],       // metrics this baseline yields
  "inputs": {
    "model_id":         "tiny-llama-1.3b",          // identity field
    "model_revision":   "abc123",                   // identity field
    "dataset_id":       "c4@v1.2",                  // identity field
    "data_slice":       {"split": "validation",
                         "max_samples": 128000},    // identity field
    "seed_list":        [0, 1, 2],                  // identity field
    "repeats":          3,                          // identity field
    "eval_suite":       "lm_perplexity@v3",         // identity field
    "vendored_code_sha":"<sha of frozen python_exp>", // identity field
  },
  "metadata": {                                     // NOT in the hash
    "produced_at":      null,
    "produced_by":      null,
    "host":             null,
    "walltime_seconds": null,
    "notes":            ""
  }
}
```

The fields under `inputs` are the **identity fields** that
participate in the hash. Fields under `metadata` are produced at
compute time and never affect the cache key.

The schema is intentionally minimal. A project that needs more
identity fields (e.g. a tokenizer revision, a quantization mode)
adds them under `inputs` *and* documents them in the project's
`<root>/baselines.config.md` so the schema stays explicit.

#### Hash protocol

The cache key for an entry is:

```
key = sha256(canonical_json(entry["inputs"]))
```

`canonical_json` is JSON with sorted dict keys, no whitespace, and
deterministic number formatting. The `name` field is *not* in the
key — two entries with different names but identical inputs collide
into the same cache entry, which is the correct behavior (one
computation, multiple labels).

Identity-vs-metadata is the load-bearing decision. Keep the
identity set small enough that small editorial changes don't
invalidate the cache (don't put `uv.lock` in identity), and large
enough that two semantically different baselines never share a key
(do put `vendored_code_sha` in identity, so a `python_exp` change
that altered the eval invalidates the cache).

When a project genuinely needs to widen the identity set (e.g. a
new dimension of variability becomes meaningful), bump a
`schema_version` field under `inputs` rather than retroactively
extending the hash silently. Old cache entries with a different
schema version simply won't match and will be recomputed at the new
schema — no false hits.

#### Lookup protocol

Given a `baselines.config` entry with computed key `H`, the lookup
walks scopes from broadest to narrowest (the same scope ordering
already used by the human-readable indexes):

1. `<root>/experiments/baselines/cache/<H>/`
2. `<root>/experiments/families/<family>/baselines/cache/<H>/`
3. `<exp>/data/baselines/cache/<H>/`

The first hit wins. The cache directory contains:

```
<scope>/baselines/cache/<H>/
  config.json     — the original entry (inputs + metadata, including produced-at)
  metrics.json    — the produced scalars
  artifacts/      — any larger artifact files this baseline emitted
```

A hit means the consumer references the cache entry from its
`data/manifest.md` (project-root-relative path, the same convention
as ancestor data references) — never copies. A miss falls through
to computation.

#### Store protocol

When `run_baselines()` produces a fresh baseline:

1. compute the metrics and artifacts,
2. write `config.json` (with metadata populated), `metrics.json`,
   and any artifact files into `<chosen-scope>/baselines/cache/<H>/`,
3. append a one-line entry to that scope's `index.md` recording
   the key `H`, the `name`, the produced-by experiment id, the
   produced-at timestamp, the artifact paths, and the consumer
   that triggered the compute.

The chosen scope follows the same "highest scope a second consumer
is plausible at" rule as the existing index-only flow.

Once written, a cache entry is **immutable** (chain-of-custody Rule
4). Recomputation under the same key is a programming error —
either the implementation drifted or the inputs are not actually
identifying. Tooling should refuse to overwrite an existing
`<H>/` directory and print the existing entry's metadata so the
operator can investigate the divergence.

#### LLM rule (cache-aware)

When the LLM is asked to run a baseline (project-layer or
experiment-layer `run_baselines()`), it must:

1. construct the `baselines.config` entry for the requested
   computation,
2. compute the cache key `H`,
3. walk the three scopes in order; on a hit, write a reference
   into the consumer's `data/manifest.md` and stop — do not
   recompute,
4. on a miss, surface the miss explicitly ("no cache entry for
   <H> at any scope; will compute at <scope>") so the operator
   can confirm the compute is intentional,
5. on compute, write the artifact tree at `<chosen-scope>/cache/<H>/`
   and append the corresponding `index.md` row.

A cache hit must always be preferred over recomputation. The cost
of a false miss (one extra compute) is finite; the cost of a false
hit (silently consuming a stale baseline) is a chain-of-custody
violation, which is why the schema-version bump is the only way to
widen identity.

---

## Running an experiment

**Always use `uv`. Never invoke `python` (or `python3`) directly
inside an experiment.** This is the single most common onboarding
mistake — a new operator sees `code/run_experiment.py` and reaches
for `python run_experiment.py`, which is wrong every time.

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

The experiment's pyproject declares an editable (or, post-freeze,
vendored) dependency on `tools/python_exp/` via `[tool.uv.sources]`,
so `run-experiment` and any shared imports resolve to the
currently-checked-out shared library without a separate install
step.

### Why bare `python` is wrong

`uv` is not a stylistic preference — it is what makes the experiment
*the experiment we measured*. Bypassing it silently changes the
measured system in ways that break chain of custody and produce
unreproducible runs:

* **Wrong interpreter.** `python` resolves to whatever is first on
  `PATH` — system Python, conda, pyenv shim, the previous
  experiment's leftover venv. `uv run` always uses the interpreter
  pinned in `code/.python-version` / `pyproject.toml`'s
  `requires-python`, so the run that lands on disk uses the version
  the experiment was scaffolded against.
* **Wrong dependency tree.** `python run_experiment.py` will resolve
  imports against whatever happens to be installed in the current
  shell, ignoring `code/uv.lock`. After freeze, the lockfile is part
  of the chain of custody (Rule 5: the experiment must reproduce six
  months later); a bare-Python invocation reads from the user's
  ambient environment instead and the resulting numbers are not the
  experiment's numbers.
* **Wrong `python_exp` resolution.** `[tool.uv.sources]` is honored
  only by `uv`. Bare `python` finds whatever `python_exp` happens to
  be importable from `PYTHONPATH`, which silently mixes the current
  `tools/python_exp/` (or, worse, an unrelated install of
  `python-exp`) with the experiment's frozen state.
* **No reproducible install step.** A future re-run by another
  operator (or by the same operator six months later) starts with
  `uv sync` to materialize the locked environment. There is no
  equivalent for "the python I happened to have on PATH"; the run
  is irreproducible by construction.

If `uv` is missing on the host, **install `uv`**, do not fall back
to `python`. Reproducing the experiment with the wrong tooling is
strictly worse than not running it.

### Console scripts, not file paths

Always invoke entry points by their `[project.scripts]` console name
(`run-experiment`, `check-regressions`), not by file path:

```bash
# Right
uv run run-experiment
uv run check-regressions

# Wrong — both bypass the console-script wiring and may bypass uv:
python code/run_experiment.py
uv run python code/run_experiment.py
```

The console-script form is what the scaffolder wires up in
`code/pyproject.toml`; running by file path skips the entry-point
declaration and may silently miss setup that the entry point performs
(argument parsing, logging configuration, the `__main__` guard).

### LLM rule

When asked to run, poll, or re-run an experiment, the LLM must:

1. invoke commands as `uv run <console-script>` (or
   `uv run --project <code-dir> <console-script>`) — never as
   `python <file>` or `python3 <file>`,
2. refuse to substitute bare Python even if `uv` reports a missing
   environment — propose `uv sync` first,
3. when an operator's transcript shows them about to invoke
   `python run_experiment.py`, intercept and explain the failure
   modes above before running anything.

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
* question,
* command,
* directory.

(No `status` column — table membership = active. Per-experiment
operational status lives in each experiment's `index.md`.)

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

2. **Vendor shared code at scaffold time.** `new_experiment.py` and
   `branch_experiment.py` vendor `python_exp` automatically:
   `new_experiment.py` copies from `tools/python_exp/`,
   `branch_experiment.py` inherits the parent's vendored copy via the
   deep-copy of `code/`. Both regex-rewrite `[tool.uv.sources]` to
   point at `./vendored/python_exp` (no `editable = true`) and print a
   "Vendoring provenance" block (source path + SHA, dest path,
   pyproject line/old/new) so the operator can verify nothing
   unrelated was touched. If vendoring fails, the half-scaffolded
   experiment dir is rolled back. Other shared tools (binaries, jars,
   CLIs) still need to be vendored manually before launch — auto-
   vendoring covers `python_exp` only.

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
   launch time — what was vendored, when, what SHAs, any deviation
   from the shared version. The values to record are the ones
   `new_experiment.py` / `branch_experiment.py` already printed in
   their "Vendoring provenance" block. Without this block the chain of
   custody cannot be audited.

### LLM rule

When asked to launch an experiment, the LLM must refuse to proceed until
`code/vendored/python_exp/` is populated, `[tool.uv.sources]` points
inside the experiment (`./vendored/python_exp`, no `editable = true`),
every manifest script reference is local, and the `Freeze` block in
`run.md` has been filled in. For experiments scaffolded by the current
tooling all four are true at scaffold time; for legacy experiments
scaffolded under the manual-freeze workflow, run the recipe in
`references/chain-of-custody.md` to repair.

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
* what comparisons matter,
* which **baselines** the experiment will compare against — read
  `experiments/baselines/index.md` and the family's
  `experiments/families/<family>/baselines/index.md` first; reference
  an existing baseline rather than producing a new one whenever
  possible (see "Baselines" above).

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

`python_exp` was vendored automatically by `new_experiment.py` /
`branch_experiment.py` at scaffold time (see "Chain of custody >
Rule 2"). The smoke test (`uv sync && uv run run-experiment` inside
`code/`) is also run automatically when the scaffolder is invoked with
`--smoke`; on success the scaffolder wipes the artifacts the smoke
produced (`.venv`, `__pycache__`, `tensorboard/*`, `logs/*`) so the
freeze commit stays clean. On failure the artifacts are left in place
for inspection. What remains to do at launch:

* copy any shared non-Python tool (binary, jar, CLI) the experiment
  will invoke into the experiment's own tree,
* copy any generation script referenced from another experiment into
  `data/generation-scripts/` and rewrite `data/manifest.md`,
* fill in the `Freeze` block in `run.md` (paths, SHAs, timestamp) —
  the values for the `python_exp` rows are the ones the scaffolder
  already printed in its "Vendoring provenance" block.

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

* the child experiment directory (`results.md`, `hypotheses.md`, and
  the experiment's `index.md` `Status:` field — the canonical home for
  operational status; do not mirror it elsewhere),
* the parent experiment if descendant notes are relevant,
* `experiments/experiments.md` — move the row from Active to Completed
  (table membership is the project-level status cut), update best
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
- `baselines-index.md` — cross-family baselines index at `<root>/experiments/baselines/index.md` (written by `init_project.py`)
- `family-baselines-index.md` — per-family baselines index at `<root>/experiments/families/<family>/baselines/index.md` (written by `new_experiment.py` / `branch_experiment.py` on first use of a family)
- `experiment-index.md` — rendered to each experiment's `index.md`
- `plan.md`, `run.md`, `results.md`, `hypotheses.md` — per-experiment files
- `artifacts-agents.md` → `artifacts/AGENTS.md`
- `artifacts-memory.md` → `artifacts/memory.md`
- `manifest.md` → `data/manifest.md`
- `default/code-pyproject.toml` → `code/pyproject.toml` (default variant)
- `default/code-run-experiment.py` → `code/run_experiment.py` (carries the per-experiment `run_baselines()` hook)
- `default/code-run-config.json` → `code/run_config.json` (with parent-aware inheritance; see below)
- `default/code-check-regressions.py` → `code/check_regressions.py`
- `evolve/code-pyproject.toml` → `code/pyproject.toml` (evolve variant — depends on `openevolve`)
- `evolve/code-run-experiment.py` → `code/run_experiment.py` (drives the openevolve loop)
- `evolve/code-run-config.json` → `code/run_config.json` (carries `openevolve.*` block)
- `evolve/code-check-regressions.py` → `code/check_regressions.py` (asserts the openevolve API)
- `evolve/code-initial-program.py` → `code/initial_program.py` (seed with EVOLVE-BLOCK markers)
- `evolve/code-evaluator.py` → `code/evaluator.py` (the openevolve fitness function)
- `evolve/code-config.yaml` → `code/config.yaml` (openevolve config)
- `evolve/code-openevolve-capacity.py` → `code/openevolve_capacity.py` (model-capacity cooldown memory + priority failover)
- `evolve/code-openevolve-db.py` → `code/openevolve_db.py` (database inspector; `uv run openevolve-db status|latest-checkpoint|list`)
- `evolve/code-prompt-templates-diff_user.txt` → `code/prompt-templates/diff_user.txt` (strict diff-only mutation prompt)
- `evolve/artifacts-agents.md` → `artifacts/AGENTS.md` (variant-specific override)
- `tools-python-exp-pyproject.toml` → `tools/python_exp/pyproject.toml` (written by `init_project.py`)
- `tools-python-exp-init.py` → `tools/python_exp/src/python_exp/__init__.py` (written by `init_project.py`)
- `project-scripts-new-experiment.py` → `<root>/scripts/new_experiment.py` (project-local wrapper, written by `init_project.py`)
- `project-scripts-branch-experiment.py` → `<root>/scripts/branch_experiment.py` (project-local wrapper, written by `init_project.py`)
- `project-scripts-run-experiments.py` → `<root>/scripts/run_experiments.py` (self-contained orchestrator with the project-level `run_baselines()` hook, written by `init_project.py`)

See the "Required files per experiment" section above for the content each scaffolded stub must grow into before launch.

Supported `{{var}}` substitutions: `experiment_id`, `slug`, `title`, `family`, `variant`, `status`, `created_at`, `research_question`, `parent_experiment`, `parent_checkpoint`, `parent_directory`, `ancestor_baseline`, `counterfactual_delta`, `invariants`, `command`, `branched_from`, `branched_at`, `branch_copied_files`, `project_name`, `description`.

Not every template uses every variable; templates not touched by a given
variable pass it through untouched.

To customize the scaffolded output for a project, edit the template files in place. To extend the `{{var}}` set, update `scripts/_lib.py` and the relevant CLI args in `scripts/new_experiment.py`.

---

## Variants

The skill supports multiple **variants** of the experiment scaffold. A
variant only changes the contents of the per-experiment `code/`
directory (and a small handful of variant-aware overrides for files
like `artifacts/AGENTS.md`); everything else — the lineage object
model, the chain-of-reasoning protocol, the freeze procedure, the
indexes — is identical across variants.

The two variants today:

| Variant   | Purpose                                                                 | Distinct files in `code/`                                                                |
|-----------|-------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| `default` | Conventional ML run (PyTorch + tensorboard + custom train loop).        | `pyproject.toml`, `run_experiment.py`, `run_config.json`, `check_regressions.py`.        |
| `evolve`  | OpenEvolve evolutionary loop (LLM mutates a seed program iteratively).  | All of the above plus `initial_program.py`, `evaluator.py`, `config.yaml`, `openevolve_db.py`. `pyproject.toml` depends on `openevolve` instead of `torch`, registers an `openevolve-db` console script, and the default `config.yaml`'s `llm.api_base` expects the `acp-cdc-ai-python` skill's local OpenAI-compatible server to be running. |

**Where the variant is stored:**

- Project default — `<root>/hyper-experiments.md`'s `Variant:` line. Set
  by `init_project.py --variant {default|evolve}` (default `default`).
  `new_experiment.py` reads this when no `--variant` is passed.
- Per-experiment — `code/run_config.json`'s `"variant"` field. Surfaced
  in `index.md` for visibility. Branched experiments inherit this from
  their source automatically (the deep-copy carries it).

**Choosing a variant on a new experiment:**

```bash
python scripts/new_experiment.py \
    --variant evolve \
    --family kernel_search \
    --title "evolve Metal attention kernel" \
    --type root
```

Omit `--variant` to use the project default.

**Branching across variants** is intentionally not supported — branching
deep-copies the parent's `code/`, and a default→evolve transition
(or vice versa) would produce a child whose code mixes the two
mechanisms. Use `new_experiment.py --variant <other>` to start a fresh
scaffold in the other variant.

### Evolve-variant essentials

Read the openevolve README for the full picture; the points that matter
for hyper-experiments:

- **Seed** (`code/initial_program.py`): the program the LLM mutates.
  Mark mutable regions with `# EVOLVE-BLOCK-START` / `# EVOLVE-BLOCK-END`.
  Imports of `python_exp` and the non-evolving outer wrapper live
  OUTSIDE the markers (the LLM can delete anything inside).
- **Evaluator** (`code/evaluator.py`): `evaluate(program_path)` returns
  an `EvaluationResult(metrics={"combined_score": ..., ...},
  artifacts={...})`. `evaluate_stage1` is the cheap pre-filter for
  cascade evaluation.
- **OpenEvolve config** (`code/config.yaml`): LLM ensemble, prompt
  system message, MAP-Elites database parameters, evaluator
  thresholds. The system message is the most important knob — iterate
  on it explicitly and treat changes as their own counterfactual delta.
  Evolve experiments also ship `code/prompt-templates/diff_user.txt`,
  which overrides OpenEvolve's default diff prompt with a strict
  "return only diff blocks; do not use write tools" contract for
  ACP-backed coding agents while keeping OpenEvolve's native
  `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` marker format.
  Keep the output contract and marker format intact when customizing
  the experiment prompt.
- **Model-capacity failover** (`code/openevolve_capacity.py`): the
  `llm.models` list in `code/config.yaml` is treated as priority
  order. If a model returns an ACP/Google-style quota message like
  "capacity ... reset after 15h2m49s", the runner records
  `<experiment>/data/openevolve_model_capacity.json`, skips that model
  until the parsed reset time, and tries the next configured model. If
  every model is cooling down, workers sleep until the earliest reset.
  It also appends events to
  `<experiment>/data/openevolve_model_capacity_events.jsonl`, including
  the model, the exhaustion time, the raw error, and the UTC time when
  the model becomes viable again. If the provider omits an explicit
  reset duration, the runner uses `OPENEVOLVE_MODEL_COOLDOWN_DEFAULT_SECONDS`
  (default: 24 hours) as the fallback cooldown. Test graphs can set
  `OPENEVOLVE_MODEL_COOLDOWN_ON_ALL_UNAVAILABLE=raise` to record the
  cooldown and stop instead of sleeping until the next viable model.
- **Run config** (`code/run_config.json`): hyper-experiments-side state
  (paths, parent identity, `openevolve.config_file` /
  `openevolve.initial_program` / `openevolve.evaluator` /
  `openevolve.iterations` / `openevolve.checkpoint_resume`).
- **Smoke** (`OPENEVOLVE_SMOKE=1 uv run run-experiment`): validates
  scaffold without making any LLM call. The scaffolder's `--smoke`
  flag sets this automatically for evolve experiments.
- **Required env**: `OPENAI_API_KEY` (used regardless of provider; the
  default local ACP server usually ignores it, and `run_experiment.py`
  fills a sentinel when unset). Never commit real provider keys.

#### Prerequisite: the ACP-backed OpenAI-compatible server

The default `code/config.yaml` points `llm.api_base` at
`http://localhost:8000/v1` and names `GEMINI_*` models. That endpoint
is **not OpenAI** — it is the local OpenAI-compatible HTTP server
provided by the **`acp-cdc-ai-python`** skill, which proxies
chat-completion requests onto an Agent Client Protocol (ACP) wrapper
around the selected backend CLI. The model prefix selects the route:
`GEMINI_*` uses `gemini --acp`, `CLAUDE_*` uses `claude code`,
`OPEN_AI_*` uses `codex`, and `OLLAMA_*` uses local Ollama via the
Claude ACP wrapper.

The default Gemini priority list intentionally avoids Pro models and
matches the currently available Gemini CLI flash/lite choices:

- `GEMINI_gemini-3-flash-preview`
- `GEMINI_gemini-3.1-flash-lite-preview`
- `GEMINI_gemini-2.5-flash`
- `GEMINI_gemini-2.5-flash-lite`

`run_experiment.py` probes the local server's `/v1/models` endpoint
before starting OpenEvolve, prints the configured priority list and the
server-advertised model ids, and exits with a clear error if
`config.yaml` names a model the ACP server does not advertise.

This skill declares `acp-cdc-ai-python` as a `skill_references` entry
in `skill-manager.toml`, so installing hyper-experiments via
skill-manager pulls it transitively. Before launching ANY evolve
experiment that uses the default `api_base`, start a fresh server for
that specific experiment via the skill's CLI (do NOT hand-launch the
underlying Python entry point — the launcher resolves `uv`, runs
`uv sync --extra server`, picks a free port, and writes a server-info
file the experiment can probe):

```bash
# Run from the project root (the dir containing hyper-experiments.md).
EXP_DIR="experiments/families/<family>/<exp-NNNN>-<slug>"
mkdir -p "$EXP_DIR/data/acp-openai-server/process"
"$SKILL_MANAGER_HOME/skills/acp-cdc-ai-python/scripts/start-server.py" \
    --project-root "$EXP_DIR" \
    --host 127.0.0.1 \
    --log-dir data/acp-openai-server/jsonl \
    > "$EXP_DIR/data/acp-openai-server/process/stdout.log" \
    2> "$EXP_DIR/data/acp-openai-server/process/stderr.log" &
```

The launcher writes `<experiment>/.acp-server/server.json` with the
live `host`, `port`, and `pid`. `code/run_experiment.py` probes this
file before importing openevolve, rewrites the local `api_base` to the
recorded port for the in-process OpenEvolve config, and exits with a
helpful error if the marker is missing or stale — keeping
`OPENAI_API_KEY` set to the local sentinel is not enough on its own;
the server must actually be up. The ACP conversation JSONL traces live
under `<experiment>/data/acp-openai-server/jsonl/`; the server
process's stdout/stderr live under
`<experiment>/data/acp-openai-server/process/`. Keep these
experiment-local so every OpenEvolve run carries its own LLM trace and
server diagnostics.

Re-point `llm.api_base` to a real OpenAI/Anthropic/Gemini endpoint
when you want to bypass the local ACP layer; then a real
`OPENAI_API_KEY` is required and the ACP server is not. The local
path is the default because it routes every evolve experiment through
the same chain-of-custody-safe wrapper and keeps API spend on the
operator's existing CLI subscription rather than per-token billing.

#### OpenEvolve database — one per experiment, shareable on branch

OpenEvolve persists its MAP-Elites search state to disk (the "database":
population, archive, per-island state, candidate programs and their
metrics). The database lives under
`<exp>/logs/openevolve_output/` — pointed at by
`paths.openevolve_output` in `run_config.json`. Each experiment's
database is isolated to its own directory by construction:

- **`new_experiment.py` (--variant evolve)** — the new experiment
  gets its **own empty database**. `openevolve.checkpoint_resume` is
  `null`; the openevolve loop starts fresh, scores the seed program
  as iteration 0, and writes checkpoints into the experiment's own
  `logs/openevolve_output/` at `checkpoint_interval` (see
  `config.yaml`). Never point a fresh experiment's
  `paths.openevolve_output` at another experiment's directory —
  concurrent writes silently corrupt both databases.
- **`branch_experiment.py`** — the child **inherits the parent's
  database by default**: the script discovers the parent's latest
  `checkpoint_N` directory under
  `<parent>/logs/openevolve_output/` and writes that path into the
  child's `run_config.json` as `openevolve.checkpoint_resume`. On
  launch, the child loads the parent's MAP-Elites state and continues
  the search from there, writing new checkpoints into its own
  `logs/openevolve_output/`. The two databases stay physically
  separate; "inherits" means "starts seeded from", not "shares the
  same files".
- **`branch_experiment.py --new-openevolve-database`** — opt out of
  the inheritance: `checkpoint_resume` is left `null` and the child
  starts a fresh database, the same way `new_experiment.py` does.
  Use this when the counterfactual delta invalidates the parent's
  search state (e.g. swapping `initial_program.py`, changing the
  evaluator contract, or restructuring `config.yaml`'s database
  block) — resuming under those conditions silently mixes states
  that came from different fitness landscapes.

The skill ships a small `openevolve-db` CLI inside every evolve
experiment's `code/` (via `code/openevolve_db.py`, registered as a
console script in `code/pyproject.toml`):

```bash
# Inside an experiment's code/ directory:
uv run openevolve-db status              # database path + latest checkpoint
uv run openevolve-db latest-checkpoint   # absolute path to highest-numbered ckpt
uv run openevolve-db list                # all checkpoints in order
```

`branch_experiment.py` uses the same discovery logic to find the
parent's latest checkpoint at branch time. The CLI is also how an
agent should answer "where is this experiment's database?" without
spelunking the directory tree.

### Counterfactual deltas in an evolve experiment

The "delta vs. parent" can land in any of these places — all of them
are legitimate counterfactual subjects:

| Where the delta lives                      | Example                                       |
|--------------------------------------------|-----------------------------------------------|
| `config.yaml` LLM section                  | swap primary model, change ensemble weights   |
| `config.yaml` prompt.system_message        | sharpen role / constraints                    |
| `config.yaml` database section             | larger population, more islands, new feature  |
| `evaluator.py` (fitness function)          | new metric, different cascade threshold       |
| `initial_program.py` seed                  | different starting algorithm                  |
| `run_config.json` openevolve.iterations    | longer / shorter search budget                |
| `run_config.json` openevolve.checkpoint_resume | fresh-vs-inherited MAP-Elites state (branch: default inherit; pass `--new-openevolve-database` to start fresh) |

Whatever changed must be visible in `plan.md`'s "Counterfactual delta"
and audited in the "Inherited config audit" block (when branching) so
the next reader can tell what is deliberate and what is leftover from
the parent.

### Meta-loop framing

Sometimes only one element is being evolved — the "experiment" looks
like a single openevolve run. That's fine; it still fits the
counterfactual model. Document the loop's structure (what is the seed,
what is the contract, what is being scored, where the loop
terminates) in `plan.md`'s 'Implementation' section so the lineage is
legible even when the loop is degenerate.

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
8. always update the root ledger,
9. before running anything non-trivial, confirm a minimum reproducible example exists at the bottom of the ladder, and propose building one if it does not (see "Isolation and the complexity ladder"),
10. always invoke experiment entry points through `uv run <console-script>`; never `python <file>` or `python3 <file>` (see "Running an experiment > Why bare `python` is wrong" — bypassing `uv` silently breaks chain of custody and produces irreproducible runs),
11. refuse to scaffold an iteration until type, anchor + anchor evidence, one-line iteration delta, primary hypothesis, and falsifiers are stated; refuse to declare a root without explicit "what we know works" evidence (see "Chain of reasoning"),
12. before launching an iteration, walk the anchor chain back to a root and confirm every intermediate link is `surviving`; if any link is `proposed`, `under-test`, or `ruled-out`, surface this and ask whether to re-anchor up the chain rather than proceed,
13. push back when the user proposes an experiment that has no chain of reasoning back to a root and the global hypothesis — agreeing with every formulation defeats the discipline.

The LLM must not:

* silently change multiple important variables without declaring them,
* run experiments without a comparison target,
* omit decision criteria,
* omit lineage,
* skip rungs of the complexity ladder when isolation is the right tool, or interpret a high-rung result while lower rungs are still red,
* invoke `python` / `python3` directly inside an experiment, or run an entry point by file path instead of its console-script name,
* fabricate or back-fit a chain of reasoning to make a proposed experiment look anchored when it isn't,
* allow a global hypothesis to silently change mid-project to match results (that is goalpost-moving — declare a new project instead).

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
