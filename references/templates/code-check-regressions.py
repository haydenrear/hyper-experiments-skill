"""Regression checks for {{experiment_id}} — {{title}}.

Fills a specific niche in the chain-of-custody story: the vendored
`python_exp` inside this experiment guarantees *reproducibility* of the
frozen run, but gives no signal about whether the CURRENT shared library
at `tools/python_exp/` still satisfies this experiment's contract. That
matters when:

* re-running this experiment with a newer interpretability tool that
  lives in the current shared library,
* deciding whether it is safe to re-vendor this experiment against a
  newer shared library,
* catching accidental regressions in `tools/python_exp/` before they
  land.

The project-wide runner `scripts/check_regressions.py` invokes this
script in each experiment against the CURRENT `tools/python_exp/`
(force-installed over whatever is vendored), so `main()` below answers:
"does the current shared library still behave the way this experiment
needs it to?"

Run locally:

    uv run check-regressions

Return 0 on success, non-zero on failure. Every failure should be
specific enough for an operator to locate the broken shared symbol.
"""
from __future__ import annotations

import sys

import python_exp


def check_imports() -> list[str]:
    """Contract: the symbols this experiment imports from `python_exp`
    must exist and be callable. Extend this list with every symbol the
    experiment actually uses."""
    problems: list[str] = []

    if not hasattr(python_exp, "hello"):
        problems.append("python_exp.hello is missing")
    else:
        try:
            result = python_exp.hello()
        except Exception as e:
            problems.append(f"python_exp.hello() raised {type(e).__name__}: {e}")
        else:
            if not isinstance(result, str):
                problems.append(
                    f"python_exp.hello() returned non-str: {type(result).__name__}"
                )

    # TODO: add an entry for every symbol or submodule from `python_exp`
    # that this experiment's `run_experiment.py` imports.
    return problems


def check_behavior() -> list[str]:
    """Contract: numerical or behavioral invariants this experiment
    relies on.

    Good candidates:
    * golden-value checks on a fixed input (a tokenizer must return
      the same ids, a metric must return a known value),
    * shape / dtype assertions on a known input,
    * determinism under a fixed seed.

    Bad candidates:
    * anything that loads a large checkpoint or a real dataset — keep
      these checks fast so the project-wide runner stays usable.
    """
    problems: list[str] = []
    # TODO: add behavioral checks specific to {{experiment_id}}.
    return problems


def main() -> int:
    problems = check_imports() + check_behavior()
    if problems:
        print(f"FAIL: {{experiment_id}} regression check", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"OK: {{experiment_id}} regression check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
