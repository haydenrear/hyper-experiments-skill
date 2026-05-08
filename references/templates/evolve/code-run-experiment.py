"""Entry point for {{experiment_id}} — {{title}} (evolve variant).

Drives an OpenEvolve evolutionary search for this experiment. The seed
program lives in `initial_program.py` (with EVOLVE-BLOCK markers around
the regions the LLM is allowed to mutate); the fitness function lives
in `evaluator.py` (`evaluate(program_path)` returning a metrics dict or
an `openevolve.evaluation_result.EvaluationResult`); the openevolve
configuration lives in `config.yaml`.

Run from the hyper-experiments project root:

    uv sync --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code
    uv run --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code run-experiment

Or from inside this code directory:

    uv sync
    uv run run-experiment

Required environment:

    OPENAI_API_KEY=...  # used regardless of the actual provider
                        # (set api_base in config.yaml for non-OpenAI).
                        # The default config.yaml points at a LOCAL
                        # OpenAI-compatible server on
                        # `http://localhost:8000/v1` and the local
                        # server typically ignores the key — this
                        # script defaults the key to a sentinel value
                        # when it's unset so the local path runs out
                        # of the box. Override with a real key when
                        # `api_base` points at a paid provider.

`run_baselines()` runs before the evolutionary search and is a no-op by
default — see `run_experiment.py` (default variant) and SKILL.md for the
when/how. For an evolve experiment, a "baseline" usually means the seed
program's score before evolution; openevolve records that automatically
in the database, so this hook only needs to be filled in for cross-
experiment comparisons.

SMOKE MODE: setting `OPENEVOLVE_SMOKE=1` short-circuits before any LLM
calls — it loads the config, validates that initial_program.py and
evaluator.py exist, and exits 0. Used by the scaffolder's `--smoke`
flag to verify reproducibility without spending API credits.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from python_exp import hello

CODE_DIR = Path(__file__).parent
RUN_CONFIG_PATH = CODE_DIR / "run_config.json"

# Default API base for the local OpenAI-compatible server. Used only as
# a heuristic to decide whether a missing `OPENAI_API_KEY` should be
# defaulted to a sentinel: when the configured api_base points at
# localhost the key is ignored by the server, so a missing key is a
# soft-default rather than an error. Real (paid) providers still
# require the user to export a real key.
LOCAL_API_BASE_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


def load_run_config() -> dict:
    with RUN_CONFIG_PATH.open() as f:
        return json.load(f)


def _resolve(path_str: str) -> Path:
    """Resolve a path from run_config.json relative to this code/ dir."""
    return (CODE_DIR / path_str).resolve()


def run_baselines(config: dict) -> None:
    """Produce baselines specific to this experiment.

    For evolve experiments this is usually a no-op: openevolve's database
    records the seed program's evaluation as iteration 0, which is the
    natural intra-experiment baseline. Fill this in only when you need a
    cross-experiment baseline that isn't already cached under
    ``experiments/baselines/`` or ``experiments/families/<family>/baselines/``.
    """
    print("run_baselines: skipped (evolve seed is the intra-experiment baseline; "
          "fill in only for cross-experiment baselines).")


def _smoke_check(oe_cfg: dict) -> int:
    """Validate scaffolding without making any LLM calls."""
    initial = _resolve(oe_cfg["initial_program"])
    evaluator = _resolve(oe_cfg["evaluator"])
    config_file = _resolve(oe_cfg["config_file"])
    missing = [str(p) for p in (initial, evaluator, config_file) if not p.exists()]
    if missing:
        print("smoke: missing required files:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    print(f"smoke: initial_program={initial}")
    print(f"smoke: evaluator={evaluator}")
    print(f"smoke: config_file={config_file}")
    print("smoke: OK (no LLM calls made)")
    return 0


def _ensure_api_key_for_local(api_base: str | None) -> None:
    """Default `OPENAI_API_KEY` to a sentinel when api_base points at a
    local server and no key is set. Local OpenAI-compatible servers
    (vLLM, Ollama, custom proxies) typically ignore the key but the
    OpenAI SDK rejects an empty string before the request is sent."""
    if os.environ.get("OPENAI_API_KEY"):
        return
    if not api_base:
        return
    if any(host in api_base for host in LOCAL_API_BASE_HOSTS):
        os.environ["OPENAI_API_KEY"] = "local-no-auth-required"
        print("openevolve: api_base looks local — defaulted "
              "OPENAI_API_KEY=local-no-auth-required (override with a "
              "real key when pointing at a paid provider).")


async def _run_evolution(run_config: dict) -> int:
    # Imported lazily so the smoke path doesn't pay the openevolve import
    # cost (and so a missing openevolve install only fails the real run).
    from openevolve import OpenEvolve
    from openevolve.config import load_config

    oe_cfg = run_config["openevolve"]
    config_path = _resolve(oe_cfg["config_file"])
    initial_path = _resolve(oe_cfg["initial_program"])
    evaluator_path = _resolve(oe_cfg["evaluator"])
    output_dir = _resolve(run_config["paths"]["openevolve_output"])
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(str(config_path))
    _ensure_api_key_for_local(getattr(cfg.llm, "api_base", None))
    iterations = oe_cfg.get("iterations") or cfg.max_iterations
    target_score = oe_cfg.get("target_score")
    checkpoint = oe_cfg.get("checkpoint_resume")

    print(f"openevolve: initial_program={initial_path}")
    print(f"openevolve: evaluator={evaluator_path}")
    print(f"openevolve: config={config_path}")
    print(f"openevolve: output_dir={output_dir}")
    print(f"openevolve: iterations={iterations} target_score={target_score}")

    oe = OpenEvolve(
        initial_program_path=str(initial_path),
        evaluation_file=str(evaluator_path),
        config=cfg,
        output_dir=str(output_dir),
    )
    if checkpoint:
        ckpt = _resolve(checkpoint)
        if not ckpt.exists():
            print(f"error: checkpoint {ckpt} not found", file=sys.stderr)
            return 1
        print(f"openevolve: resuming from {ckpt}")
        oe.database.load(str(ckpt))

    best = await oe.run(
        iterations=iterations,
        target_score=target_score,
        checkpoint_path=str(_resolve(checkpoint)) if checkpoint else None,
    )

    print()
    print("openevolve: evolution complete.")
    print("best metrics:")
    for k, v in best.metrics.items():
        print(f"  {k}: {v}")
    return 0


def main() -> int:
    run_config = load_run_config()
    print(f"Run config: {run_config['run_name']} (family={run_config['family']}, variant=evolve)")
    print(hello())

    run_baselines(run_config)

    if os.environ.get("OPENEVOLVE_SMOKE"):
        return _smoke_check(run_config["openevolve"])

    return asyncio.run(_run_evolution(run_config))


if __name__ == "__main__":
    raise SystemExit(main())
