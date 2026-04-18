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

No experiment may depend on `tools/python_exp/`, a sibling experiment's
`code/`, or any external state not captured in the above.

### Rule 2 — Vendor shared code before launch

The scaffold wires every experiment's `code/pyproject.toml` to the shared
library via an editable link:

```toml
[tool.uv.sources]
python-exp = { path = "../../../../../tools/python_exp", editable = true }
```

This link is a **development convenience, not a reproducibility contract**.
Before the experiment transitions from `planned` to `running`, the
operator (or LLM, when launching on the operator's behalf) **must**:

1. Copy the contents of `tools/python_exp/` into
   `<experiment>/code/vendored/python_exp/`.
2. Rewrite `code/pyproject.toml` to point at the vendored copy, dropping
   the editable flag:

   ```toml
   [tool.uv.sources]
   python-exp = { path = "./vendored/python_exp" }
   ```

3. Run `uv sync` inside `code/` and verify `run-experiment` still works.
4. Record the vendoring in `run.md` under the "Freeze" section, including
   the git commit SHA of `tools/python_exp/` at the time of the copy (if
   the project is under git).

The same procedure applies to any **other** shared tool under `tools/`
that the experiment calls directly (binaries, jars, CLIs): copy the
artifact into the experiment's own tree before launch.

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
  snapshot and `pyproject.toml` do not change,
* `data/generation-scripts/` does not change,
* `data/generated/` does not change,
* `checkpoints/` only receives new checkpoints from the same run —
  existing checkpoints are immutable.

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

## Recipe: freezing an experiment manually

From the project root, with the current experiment at
`experiments/families/<family>/<exp-id>-<slug>/`:

```bash
EXP=experiments/families/<family>/<exp-id>-<slug>

# 1. Vendor shared library
mkdir -p "$EXP/code/vendored"
cp -r tools/python_exp "$EXP/code/vendored/python_exp"

# 2. Rewrite [tool.uv.sources] in $EXP/code/pyproject.toml:
#      python-exp = { path = "./vendored/python_exp" }

# 3. Resync and smoke-run
( cd "$EXP/code" && uv sync && uv run run-experiment )

# 4. Optional: record git SHA if under version control
git -C tools/python_exp rev-parse HEAD > "$EXP/code/vendored/python_exp.SHA"

# 5. Append a Freeze block to $EXP/run.md (see run.md template).
```

A follow-up ticket may automate this as `scripts/freeze_experiment.py`.
Until then, performing these steps manually is part of the launch
checklist and must not be skipped.

---

## LLM checklist

When an LLM is asked to launch an experiment, it must refuse to proceed
until:

1. `code/vendored/python_exp/` exists and is populated,
2. `code/pyproject.toml`'s `[tool.uv.sources]` points at the vendored
   copy, not the root `tools/python_exp` path,
3. every generation-script reference in `data/manifest.md` either points
   inside this experiment or has been replaced with a vendored local
   copy,
4. the freeze block in `run.md` has been filled in with the current
   timestamp and (where applicable) the upstream git SHA.

"The editable link works fine on my machine" is not an acceptable reason
to skip any of the above. Chain of custody is a property of the archived
experiment, not of the current workstation.
