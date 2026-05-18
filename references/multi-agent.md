# Multi-Agent Operation

Hyper-experiments scale by assigning agents to directories, not by letting every
agent edit every file.

## Ownership Topology

Use a directory tree topology:

- **Project orchestrator agent** owns the project root and global shared files:
  `hyper-experiments.md`, `global-hypothesis.md`,
  `experiments/experiments.md`, `experiments/families/index.md`,
  `experiments/baselines/index.md`, and shared `tools/` changes.
- **Family orchestrator agent** owns one `experiments/families/<family>/`
  directory and its parent files: the family `index.md` and
  `baselines/index.md`.
- **Experiment agent** owns exactly one
  `experiments/families/<family>/<exp-id>-<slug>/` directory during a
  poll/update window.

Any parent directory that can be in contention should have a parent agent above
the child agents. Child agents may propose parent-file updates, but the parent
agent applies them. This is the correctness rule: the orchestrator is the only
agent that edits parent files such as `global-hypothesis.md`,
`experiments/experiments.md`, `experiments/families/index.md`, and family
`index.md` files.

## Parallelism Boundary

Safe to run concurrently:

- polling different experiment directories,
- editing files inside different experiment directories,
- running experiment-local `code/run_experiment.py` processes that write only to
  their own `logs/`, `tensorboard/`, `checkpoints/`, and `data/generated/`,
- reading shared ledgers and indexes.

Contended and parent-owned:

- allocating global `exp-NNNN` ids,
- creating a new family directory and first family index files,
- branching or deep-copying an experiment,
- moving rows in `experiments/experiments.md`,
- editing `global-hypothesis.md`,
- editing `experiments/families/index.md`,
- editing `experiments/families/<family>/index.md`,
- editing baseline indexes under `experiments/baselines/` or
  `experiments/families/<family>/baselines/`,
- changing shared `tools/` code used by future experiments.

## Project Locks

The shared scaffolding scripts use a git-backed project lock named
`scaffold-project-state` while they allocate experiment ids, create family
directories/indexes, and create the final experiment directory.

The lock CLI is:

```bash
python <hyper-experiments-skill>/scripts/project_lock.py status --root .
python <hyper-experiments-skill>/scripts/project_lock.py run --root . --name shared-ledger -- <command>
python <hyper-experiments-skill>/scripts/project_lock.py acquire --root . --name shared-ledger
python <hyper-experiments-skill>/scripts/project_lock.py release --root . --name shared-ledger --token <token>
```

Use `run` for normal critical sections. Use `acquire` / `release` only when a
human or parent agent needs to hold a lock across multiple commands. `acquire`
prints the owner token; `release` refuses to delete the lock unless that token
matches. `--force` is reserved for cleanup after confirming the owner process
died.

Lock flags exposed by the scaffolders and CLI:

- `--lock-timeout <seconds>` waits a bounded time, then fails with retry
  guidance.
- `--no-wait-lock` / `--fail-if-locked` makes one attempt and fails
  immediately if another owner holds the lock.
- `--lock-stale-after <seconds>` allows stealing a lock whose owner metadata is
  older than the threshold. Use this conservatively.

The lock is stored as a git ref. All contending agents must use the same git
repository/ref store for it to serialize correctly. If agents run in separate
clones on separate machines, put them behind a shared repository/remote locking
discipline before treating the lock as cluster-wide.

## Retry Contract

Lock failures are retryable unless the error says the project is not inside a
git worktree.

Agent behavior:

- Do not spin forever.
- If a command fails because the lock is held, report the holder metadata and
  retry later or ask the parent/orchestrator to schedule the mutation.
- If a command reports an existing experiment id, retry the whole scaffold or
  branch command so it can allocate the next id under a fresh lock.
- Never manually edit around a lock failure by writing parent files directly.

## Finish Workflow

When an experiment finishes, the experiment agent updates only files inside its
experiment directory: `results.md`, `hypotheses.md`, `run.md`, and its own
`index.md` status.

Then it sends a concise close-out proposal to the family or project
orchestrator containing:

- one-line finding,
- parent/child comparison,
- checkpoint promotion recommendation,
- family-index updates,
- cross-family/global-hypothesis implications,
- exact files it believes need parent-level edits.

The parent/orchestrator agent applies the parent-file changes under the relevant
project lock and makes the post-finish commit.

## Polling Scale

Use the experiment directory as the unit of polling ownership. One agent owns a
specific experiment during a poll/update window; another agent should not poll
and edit that same experiment until ownership is released.

As a planning estimate: with a 5-minute polling cadence and a 1-minute maximum
poll duration, one model/machine can manage roughly 5 actively polled
experiments. Scale beyond that by assigning more experiment agents, while
keeping parent-file mutations serialized through parent/orchestrator agents.
