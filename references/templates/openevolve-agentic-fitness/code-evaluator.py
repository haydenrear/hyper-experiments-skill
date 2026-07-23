"""Fitness evaluator for {{experiment_id}} — {{title}}.

`evaluate(program_path)` is called by openevolve once per candidate
program. It must:

  1. Load the candidate at `program_path` (it has the same shape as
     `initial_program.py`, with the EVOLVE-BLOCK regions mutated).
  2. Exercise it on the experiment's task.
  3. Return a metrics dict (or `EvaluationResult` for richer feedback).

`combined_score` (or whatever metric is configured under
`evaluator.cascade_thresholds` in `config.yaml`) is what openevolve
optimizes against — every other metric is recorded for analysis but
does not drive selection unless the config wires it in via
`feature_dimensions`.

`evaluate_stage1(program_path)` is the cheap pre-filter. Cascade
evaluation runs stage1 first; only programs that clear the threshold
proceed to the full `evaluate()`. Returning `combined_score: 0.0` from
stage1 is the standard way to short-circuit a clearly-broken candidate
without paying for a full evaluation.

Construction guidance:
  * Wrap any direct call to the candidate in a timeout — a bad mutation
    can hang forever.
  * Convert all returned numbers to plain `float`. NaN / inf must be
    detected and converted to a low score, not propagated.
  * Use the `artifacts` channel for stderr, profiling output, or LLM-
    judge feedback. Openevolve includes those in the next prompt.
  * Keep stage1 cheap (single-trial smoke test). Reserve expensive work
    for `evaluate()`.
"""
from __future__ import annotations

import importlib.util
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from pathlib import Path

from openevolve.evaluation_result import EvaluationResult
from python_exp.observability import (
    ExperimentObservability,
    configure_experiment_observability,
)

CODE_DIR = Path(__file__).resolve().parent
_OBSERVABILITY: ExperimentObservability | None = None


def _observability() -> ExperimentObservability:
    global _OBSERVABILITY
    if _OBSERVABILITY is None:
        config = json.loads((CODE_DIR / "run_config.json").read_text())
        _OBSERVABILITY = configure_experiment_observability(
            config,
            code_dir=CODE_DIR,
        )
    return _OBSERVABILITY


def _load(program_path: str):
    spec = importlib.util.spec_from_file_location("candidate", program_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_with_timeout(fn, timeout_s: float = 10.0):
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        return fut.result(timeout=timeout_s)


def _safe_float(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def evaluate(program_path: str) -> EvaluationResult:
    """Full evaluation. Replace the body with this experiment's task."""
    _observability().record_evaluation(stage="full")
    try:
        candidate = _load(program_path)

        if not hasattr(candidate, "run"):
            return EvaluationResult(
                metrics={"combined_score": 0.0, "error": "missing run()"},
                artifacts={
                    "error_type": "MissingFunction",
                    "error_message": "candidate program is missing required `run()` function",
                    "suggestion": "ensure run() is defined OUTSIDE the EVOLVE-BLOCK markers",
                },
            )

        # TODO: replace this stub with the real task.
        # Example: aggregate across N trials, compute combined_score.
        try:
            raw = _run_with_timeout(candidate.run, timeout_s=10.0)
        except FutTimeout:
            return EvaluationResult(
                metrics={"combined_score": 0.0, "error": "timeout"},
                artifacts={
                    "error_type": "TimeoutError",
                    "error_message": "candidate.run() exceeded 10s",
                    "suggestion": "add early termination, reduce iterations, or check for infinite loops",
                },
            )

        score = _safe_float(raw if not isinstance(raw, dict) else raw.get("score", 0.0))
        return EvaluationResult(
            metrics={"combined_score": score},
            artifacts={"raw_output": str(raw)[:500]},
        )

    except Exception as e:
        return EvaluationResult(
            metrics={"combined_score": 0.0, "error": str(e)},
            artifacts={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "full_traceback": traceback.format_exc(),
                "suggestion": "check for syntax errors or missing imports in the generated code",
            },
        )


def evaluate_stage1(program_path: str) -> EvaluationResult:
    """Cheap pre-filter — confirm the candidate parses and run() exists.
    Cascade evaluation drops candidates that fail this stage before they
    reach the expensive `evaluate()`."""
    _observability().record_evaluation(stage="stage1")
    try:
        candidate = _load(program_path)
        if not hasattr(candidate, "run"):
            return EvaluationResult(
                metrics={"runs_successfully": 0.0, "combined_score": 0.0},
                artifacts={
                    "error_type": "MissingFunction",
                    "error_message": "stage1: candidate is missing run()",
                    "suggestion": "ensure run() exists outside EVOLVE-BLOCK markers",
                },
            )
        return EvaluationResult(
            metrics={"runs_successfully": 1.0, "combined_score": 0.5},
            artifacts={"stage1_result": "imports cleanly and run() is defined"},
        )
    except Exception as e:
        return EvaluationResult(
            metrics={"runs_successfully": 0.0, "combined_score": 0.0},
            artifacts={
                "error_type": type(e).__name__,
                "error_message": f"stage1: {e}",
                "full_traceback": traceback.format_exc(),
            },
        )


def evaluate_stage2(program_path: str) -> EvaluationResult:
    """Full evaluation reused for stage2 of the cascade."""
    return evaluate(program_path)
