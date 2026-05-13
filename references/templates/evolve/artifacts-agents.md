# Agent instructions — {{experiment_id}} (evolve variant)

Operating instructions for any LLM or agent working inside this experiment's
directory. This experiment uses the **evolve** variant: an OpenEvolve loop
drives the search inside `code/`. The hyper-experiments protocol still
applies (counterfactual delta, invariants, measurement plan, decision
criteria) — the mechanism that produces the evidence is just an
evolutionary run rather than a single training run.

## Role
What this agent is expected to do inside this experiment (e.g. run the
openevolve loop, poll it, evaluate it, propose children with a different
config / prompt / seed).

## Preferred tools and scripts
- `uv run run-experiment` — launches the openevolve loop using
  `code/config.yaml`, `code/initial_program.py`, and `code/evaluator.py`.
- `OPENEVOLVE_SMOKE=1 uv run run-experiment` — validates scaffolding
  without making any LLM calls. Use this before launch and after every
  config edit.
- `uv run check-regressions` — verifies the openevolve API and the
  vendored `python_exp` still satisfy this experiment's contract.
- `uv run openevolve-db status` — prints this experiment's database
  path and the latest checkpoint. `uv run openevolve-db
  latest-checkpoint` prints the absolute path of the
  highest-numbered checkpoint (used when branching).
- TODO — which evolution checkpoints to inspect; how to compare best
  programs across siblings (path: `<exp>/logs/openevolve_output/`).

## Preflight before launch

1. **Experiment-local ACP server must be running.** The default `config.yaml` points
   `llm.api_base` at `http://localhost:8000/v1`, which is the
   OpenAI-compatible HTTP server provided by the
   **`acp-cdc-ai-python`** skill (a transitive skill_reference of
   hyper-experiments). Start one server for this experiment with the
   skill's launcher — never hand-launch the inner Python entry point:
   ```bash
   # Run from this experiment's root directory.
   mkdir -p data/acp-openai-server/process
   "$SKILL_MANAGER_HOME/skills/acp-cdc-ai-python/scripts/start-server.py" \
       --project-root . \
       --host 127.0.0.1 \
       --log-dir data/acp-openai-server/jsonl \
       > data/acp-openai-server/process/stdout.log \
       2> data/acp-openai-server/process/stderr.log &
   ```
   The launcher writes this experiment's `.acp-server/server.json`;
   `run_experiment.py` probes that file, points the local OpenEvolve
   config at the recorded host/port, and refuses to launch the
   evolutionary loop if the server is missing or its pid is dead. ACP
   conversation JSONL traces belong in `data/acp-openai-server/jsonl/`;
   server stdout/stderr belong in `data/acp-openai-server/process/`.
   See SKILL.md > "Prerequisite: the ACP-backed OpenAI-compatible
   server" for the full rationale (chain-of-custody, why the model
   string carries the `CLAUDE_*` prefix, how to re-point at a paid
   provider).
2. **Database policy.** This experiment's openevolve database lives
   at `logs/openevolve_output/` and is isolated from every other
   experiment's database. `run_config.json`'s
   `openevolve.checkpoint_resume` determines the starting state:
   `null` = fresh database (scaffolded experiments); a path under a
   parent's `logs/openevolve_output/checkpoint_N` = resume from the
   parent's MAP-Elites state (branched experiments default to this,
   unless the operator passed `--new-openevolve-database`). Confirm
   this choice is intentional during the inherited-config audit
   before the freeze commit.

## Boundaries
- Do **not** invoke `python` or `python3` directly inside this experiment —
  always run entry points via `uv run <console-script>`. Bare Python
  bypasses `code/uv.lock`, ignores `[tool.uv.sources]`, and resolves
  `python_exp` against whatever happens to be on `PYTHONPATH`, silently
  breaking chain of custody.
- Do **not** edit `index.md`'s Parent section after launch — lineage is frozen.
- Do **not** edit `code/` (including `config.yaml`, `initial_program.py`,
  `evaluator.py`) after launch. The openevolve database commits to a
  specific seed + evaluator + config; mutating any of them mid-run
  silently corrupts the lineage of every program in the database. If a
  change is needed, create a child experiment.
- Do **not** weaken the mutation-agent output contract in
  `code/config.yaml` or `code/prompt-templates/diff_user.txt`.
  ACP-backed coding agents must return only OpenEvolve diff blocks
  matching `diff_pattern`. They must not call write/edit/patch/shell
  tools, create `main.py`, or create alternate source files.
- Do **not** edit `code/` or `data/generation-scripts/` after launch. If a
  change is needed, create a child experiment. See
  `references/chain-of-custody.md`.
- Do **not** launch this experiment until it has been frozen: `tools/python_exp`
  vendored into `code/vendored/`, `[tool.uv.sources]` pointing inside this
  experiment, the openevolve version pinned in `pyproject.toml`, and the
  `Freeze` block in `run.md` filled in.
- Do **not** commit `OPENAI_API_KEY` (or any LLM provider credential) into
  the repo. The key is read from the environment at run time and must
  stay there. The default `config.yaml` points at a LOCAL
  OpenAI-compatible server on `http://localhost:8000/v1`; the local
  server typically ignores the key, and `run_experiment.py` defaults
  it to a sentinel for that path. When you switch `api_base` to a
  paid provider, export a real key — never inline it.
- TODO — anything else this experiment considers off-limits.

## Conventions
- Append to `run.md` for every poll, decision, or anomaly. Note the
  iteration number and the best `combined_score` at each poll.
- The openevolve checkpoint number IS the experiment's poll cadence —
  one entry in `run.md` per checkpoint is a sane default.
- Write post-run conclusions to `results.md` and `hypotheses.md`.
- Update the root `experiments/experiments.md` ledger when status changes.

## Handoff notes
Short-form notes for the next agent picking up this experiment: where in
the openevolve checkpoint sequence the run is, what the current best
program looks like, what hypothesis the next config tweak would test.
