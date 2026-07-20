"""Regression checks for {{experiment_id}} — {{title}} (evolve variant).

Same role as the default-variant check_regressions.py, but extended to
verify that the openevolve API surface this experiment relies on still
exists. The vendored `python_exp` guarantees reproducibility of the
frozen run; this file answers "does the CURRENT shared library + the
CURRENT openevolve still satisfy this experiment's contract?"

Run locally:

    uv run check-regressions

Return 0 on success, non-zero on failure.
"""
from __future__ import annotations

import sys

import openevolve_capacity
import python_exp
from python_exp import observability as experiment_observability


def check_imports() -> list[str]:
    """Contract: the symbols this experiment imports from `python_exp`
    and `openevolve` must exist and be callable."""
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

    if not hasattr(openevolve_capacity, "install"):
        problems.append("openevolve_capacity.install is missing")

    if not callable(
        getattr(experiment_observability, "configure_experiment_observability", None)
    ):
        problems.append(
            "python_exp.observability.configure_experiment_observability is missing"
        )
    if not hasattr(experiment_observability, "ExperimentObservability"):
        problems.append("python_exp.observability.ExperimentObservability is missing")

    try:
        import openevolve  # noqa: F401
        from openevolve import OpenEvolve  # noqa: F401
        from openevolve.config import load_config  # noqa: F401
        from openevolve.evaluation_result import EvaluationResult  # noqa: F401
    except Exception as e:
        problems.append(f"openevolve API import failed: {type(e).__name__}: {e}")

    # TODO: add an entry for every additional symbol or submodule from
    # `python_exp` or `openevolve` that this experiment's
    # `run_experiment.py`, `initial_program.py`, or `evaluator.py` imports.
    return problems


def check_behavior() -> list[str]:
    """Contract: numerical or behavioral invariants this experiment
    relies on.

    Good candidates for an evolve experiment:
    * the seed `initial_program.py` parses, imports, and runs without
      requiring an LLM,
    * the evaluator returns a metrics dict with the expected keys when
      handed a known-good program,
    * the openevolve config file in this dir loads and validates.

    Bad candidates:
    * anything that makes a real LLM call — keep these checks fast and
      offline so the project-wide runner stays usable.
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
