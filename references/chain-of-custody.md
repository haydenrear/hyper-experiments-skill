# Chain of custody

The purpose of this document is to define what "chain of custody" means for
a hyper-experiments project and exactly what an operator or LLM must do to
preserve it.

## Principle

> **Every experiment, once launched, must reproduce the same result every
> time it is re-run, forever.**

This is not an aesthetic preference. Experiments are re-run when a new
mechanistic interpretability tool, probe, or evaluation becomes available
and we want to apply it to an old training regime. If re-running a 6-month-
old experiment silently pulls in a newer version of a shared utility, a
newer tokenizer, a newer dataset filter, or a newer loss helper, the new
observations cannot be trusted as measurements of the original experiment.

Corollary: the default ergonomics of a working project (shared libraries,
editable installs, referenced data) create an *active* risk of breaking
chain of custody. Protecting it requires explicit action at launch time
and strict discipline afterward.

---

## The six rules

### Rule 1 — Self-containment

Every launched experiment must be reproducible from only:

* its own `code/`,
* its own `data/` (including any ancestor data it has chosen to vendor),
* its own `checkpoints/`,
* the referenced ancestor data that it explicitly declares — **only if**
  that ancestor is itself frozen (see Rule 3).

### Rule 2 — Vendor shared code at scaffold time

`scripts/new_experiment.py` and `scripts/branch_experiment.py` vendor
the shared `python_exp` library automatically:

- **new_experiment.py** copies `tools/python_exp/` into the new
  experiment's `code/vendored/python_exp/` and regex-rewrites
  `code/pyproject.toml`'s `[tool.uv.sources]` line to point at
  `./vendored/python_exp` (without `editable = true`).
- **branch_experiment.py** deep-copies the parent's `code/` tree
  (which already includes the parent's `vendored/python_exp/`), so the
  child inherits the *parent's* frozen library — not whatever
  `tools/python_exp/` is at branch time. The child's pyproject is
  verified to still point at `./vendored/python_exp` and
  regex-repaired if necessary.

Both scripts print a "Vendoring provenance" block to stdout naming the
source path, source git SHA (if under git), destination path, and the
exact pyproject.toml line that was rewritten (file, line number, old,
new) so the operator (or LLM) can verify nothing unrelated was touched.
If vendoring fails, the half-scaffolded experiment directory is rolled
back and the script exits non-zero — there is no "scaffolded but
un-vendored" intermediate state.

Record the vendoring details (source path, source git SHA, destination
path) in `run.md` under the "Freeze" section. The values to copy in
are the ones the script already printed.

The same expectation applies to any **other** shared tool under
`tools/` that the experiment calls directly (binaries, jars, CLIs):
copy the artifact into the experiment's own tree before launch and
record it in the Freeze block. Auto-vendoring currently covers
`python_exp` only; other tools remain a manual step.

### Rule 3 — Vendor shared generation scripts

If this experiment's `data/manifest.md` references a **generation script**
owned by another experiment, copy that script into this experiment's own
`data/generation-scripts/` before launch, and rewrite the manifest entry
to point at the local copy. Record the source (experiment id, original
path, git SHA if available) in a provenance comment inside the copied
script.

Referencing another experiment's **generated data** (the output of a
script, not the script itself) is allowed *only if* the referenced
ancestor is itself in a frozen status (`running`, `completed`,
`archived`). Referencing data owned by a `planned` experiment is
forbidden — that experiment has not yet committed to its data pipeline.

### Rule 4 — Freeze means frozen

Once an experiment is `running`, `completed`, or `archived`:

* `code/` is append-only for logs that happen to live there; the source
  snapshot, `pyproject.toml`, and `run_config.json` do not change,
* `data/generation-scripts/` does not change,
* `data/generated/` does not change,
* `checkpoints/` only receives new checkpoints from the same run —
  existing checkpoints are immutable.

`run_config.json` is part of the frozen state specifically because it
encodes the hyperparameters the experiment was actually running with:
changing it post-launch turns the historical measurement into a claim
about a configuration that never actually ran.

If new information arises that would require editing one of these,
**create a child experiment** (a counterfactual whose delta is precisely
"use the corrected code / fixed data / different artifact") instead of
mutating the existing one. The original experiment remains a valid
historical measurement, even if it turns out to have been buggy.

### Rule 5 — Shared tools evolve freely — for future experiments

`tools/python_exp/` and other assets under `tools/` are allowed, and
expected, to evolve. Improvements there benefit every **future**
experiment that vendors the improved version at its own launch time.
Past experiments that vendored earlier versions are unaffected. This is
the point of vendoring.

When editing `tools/python_exp/`, run
`python scripts/check_regressions.py` from the project root before
committing. That script invokes every experiment's
`code/check_regressions.py` against the CURRENT shared library — which
tells you:

* whether your edit would break any existing experiment's contract if
  that experiment were re-vendored (the safe-to-re-vendor check),
* which experiments have a contract loose enough that they do not
  notice the change (the can-always-re-vendor case).

Neither result affects the frozen experiments themselves — those
remain pinned to their vendored copy — but it tells you whether the
evolution of `tools/` has diverged from any past experiment's
expectations, which is a prerequisite for any re-run against current
tooling.

### Rule 6 — Record the vendoring

Every experiment's `run.md` must carry a "Freeze" block that names:

* what shared assets were vendored (paths, sizes, SHAs where available),
* when the vendoring happened,
* what command was used (or a link to a script),
* any intentional divergence from the shared `tools/` version at time of
  freeze.

Without this block, the chain of custody is not auditable: a future
operator cannot distinguish "this experiment was frozen against a known
version" from "this experiment was never frozen and has been silently
drifting with `tools/`".

---

## Recipe: re-vendoring an experiment manually

`new_experiment.py` and `branch_experiment.py` already vendor at scaffold
time. You only need this recipe if you are repairing an experiment
scaffolded under the legacy manual-freeze workflow, or re-vendoring
against a newer `tools/python_exp/`:

```bash
EXP=experiments/families/<family>/<exp-id>-<slug>

# 1. Vendor shared library
rm -rf "$EXP/code/vendored/python_exp"
cp -r tools/python_exp "$EXP/code/vendored/python_exp"

# 2. Ensure [tool.uv.sources] in $EXP/code/pyproject.toml reads:
#      python-exp = { path = "./vendored/python_exp" }
#    (no `editable = true`).

# 3. Resync and smoke-run
( cd "$EXP/code" && uv sync && uv run run-experiment )

# 4. Optional: record git SHA if under version control
git -C tools/python_exp rev-parse HEAD > "$EXP/code/vendored/python_exp.SHA"

# 5. Append a Freeze block to $EXP/run.md (see run.md template).
```

---

## LLM checklist

When an LLM is asked to launch an experiment, it must refuse to proceed
until:

1. `code/vendored/python_exp/` exists and is populated (auto-vendored at
   scaffold time by `new_experiment.py` / `branch_experiment.py`; if
   missing, the experiment was scaffolded under the legacy manual-freeze
   workflow and must be repaired with the recipe above),
2. `code/pyproject.toml`'s `[tool.uv.sources]` points at the vendored
   copy, not the root `tools/python_exp` path,
3. every generation-script reference in `data/manifest.md` either points
   inside this experiment or has been replaced with a vendored local
   copy,
4. the freeze block in `run.md` has been filled in with the current
   timestamp and (where applicable) the upstream git SHA recorded in
   the scaffolder's vendoring-provenance output.

"The editable link works fine on my machine" is not an acceptable reason
to skip any of the above. Chain of custody is a property of the archived
experiment, not of the current workstation.
