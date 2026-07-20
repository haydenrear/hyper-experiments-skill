"""Run the best program produced by OpenEvolve for this experiment.

This is the deployment-oriented entry point. It does not import or run
OpenEvolve; by default it executes:

    <experiment>/logs/openevolve_output/best/best_program.py

Pass an explicit path to run a checkpoint-pinned best program instead:

    uv run run-best-program ../logs/openevolve_output/checkpoints/checkpoint_50/best_program.py
"""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

from python_exp.observability import configure_experiment_observability

CODE_DIR = Path(__file__).resolve().parent
RUN_CONFIG_PATH = CODE_DIR / "run_config.json"


def _load_run_config() -> dict:
    with RUN_CONFIG_PATH.open() as f:
        return json.load(f)


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (CODE_DIR / path).resolve()


def _default_best_program(run_config: dict) -> Path:
    output_dir = _resolve(run_config["paths"]["openevolve_output"])
    return output_dir / "best" / "best_program.py"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "program",
        nargs="?",
        help="Best-program path to run. Defaults to logs/openevolve_output/best/best_program.py.",
    )
    ap.add_argument(
        "--print-path",
        action="store_true",
        help="Print the resolved program path before running it.",
    )
    args = ap.parse_args(argv)

    run_config = _load_run_config()
    observability = configure_experiment_observability(
        run_config,
        code_dir=CODE_DIR,
    )
    try:
        if observability.trace_id is not None:
            print(f"Trace ID: {observability.trace_id}")
            print(f"Trace artifact: {observability.trace_artifact}")

        program = (
            _resolve(args.program)
            if args.program
            else _default_best_program(run_config)
        )
        if not program.exists():
            print(
                f"error: best program not found at {program}\n"
                "       Run `uv run run-openevolve` first, or pass a "
                "checkpoint-local best_program.py path.",
                file=sys.stderr,
            )
            return 1
        if args.print_path:
            print(program)

        observability.record_iteration(stage="best-program-dispatch")
        sys.path.insert(0, str(program.parent))
        sys.path.insert(0, str(CODE_DIR))
        runpy.run_path(str(program), run_name="__main__")
        return 0
    finally:
        observability.flush(
            timeout_millis=run_config.get("observability", {}).get(
                "flush_timeout_millis", 5_000
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
