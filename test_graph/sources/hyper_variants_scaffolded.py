# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk", "pyyaml>=6.0"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Scaffold fresh default and OpenEvolve experiments from current templates."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from testgraphsdk import NodeResult, NodeSpec, node


CLAUDE_SONNET_MODEL = "CLAUDE_claude-sonnet-4-6"


@dataclass(frozen=True)
class Variant:
    key: str
    name: str
    family: str
    title: str
    command: str


VARIANTS = (
    Variant(
        key="default",
        name="default",
        family="observability_default",
        title="Default observability smoke",
        command="uv run run-experiment",
    ),
    Variant(
        key="evolve",
        name="evolve",
        family="observability_evolve",
        title="Evolve Claude observability smoke",
        command="uv run run-openevolve",
    ),
    Variant(
        key="agentic",
        name="openevolve-agentic-fitness",
        family="observability_agentic",
        title="Agentic fitness Claude observability smoke",
        command="uv run run-openevolve",
    ),
)

SPEC = (
    NodeSpec("hyper.variants.scaffolded")
    .kind("fixture")
    .depends_on("hyper.repo.scaffolded")
    .tags("hyper-experiments", "openevolve", "claude", "fixture")
    .timeout("5m")
    .side_effects("fs:tmp")
    .output("defaultExperimentDir", "string")
    .output("defaultCodeDir", "string")
    .output("defaultServiceName", "string")
    .output("evolveExperimentDir", "string")
    .output("evolveCodeDir", "string")
    .output("evolveServiceName", "string")
    .output("agenticExperimentDir", "string")
    .output("agenticCodeDir", "string")
    .output("agenticServiceName", "string")
    .output("modelPriority", "string")
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _seed_program() -> str:
    return """from __future__ import annotations


# EVOLVE-BLOCK-START
def solve() -> float:
    return 1.0
# EVOLVE-BLOCK-END


def run() -> dict:
    return {"score": float(solve())}


if __name__ == "__main__":
    print(run())
"""


def _scaffold_variant(
    *,
    skill_root: Path,
    repo_root: Path,
    variant: Variant,
    log_path: Path,
) -> tuple[subprocess.CompletedProcess[str], Path | None]:
    proc = subprocess.run(
        [
            sys.executable,
            str(skill_root / "scripts" / "new_experiment.py"),
            "--experiments-root",
            str(repo_root),
            "--family",
            variant.family,
            "--title",
            variant.title,
            "--question",
            f"Does the current {variant.name} template emit correlated telemetry?",
            "--delta",
            "validation: current template under inherited Test Graph trace",
            "--invariant",
            "fresh scaffold with one bounded run",
            "--command",
            variant.command,
            "--variant",
            variant.name,
            "--type",
            "root",
        ],
        cwd=skill_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "HYPER_EXPERIMENTS_SKILL_HOME": str(skill_root)},
    )
    log_path.write_text(proc.stdout)
    matches = sorted(
        (repo_root / "experiments" / "families" / variant.family).glob("exp-*")
    )
    return proc, matches[0] if len(matches) == 1 else None


def _configure_llm_variant(exp_dir: Path, *, agentic: bool) -> None:
    code_dir = exp_dir / "code"
    (code_dir / "initial_program.py").write_text(_seed_program())

    run_config_path = code_dir / "run_config.json"
    run_config = json.loads(run_config_path.read_text())
    run_config["openevolve"]["iterations"] = 1
    run_config_path.write_text(json.dumps(run_config, indent=2) + "\n")

    config_path = code_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["max_iterations"] = 1
    config["checkpoint_interval"] = 1
    config["llm"]["models"] = [
        {"name": CLAUDE_SONNET_MODEL, "weight": 1.0}
    ]
    for key in (
        "primary_model",
        "primary_model_weight",
        "secondary_model",
        "secondary_model_weight",
    ):
        config["llm"].pop(key, None)
    config["llm"]["retries"] = 0
    config["llm"]["timeout"] = int(
        os.environ.get("TEST_GRAPH_OPENEVOLVE_TIMEOUT", "300")
    )
    config["evaluator"]["parallel_evaluations"] = 1
    if agentic:
        agentic_config = config["fitness"]["agentic"]
        agentic_config["model"] = CLAUDE_SONNET_MODEL
        agentic_config["research_rerank_interval"] = 1
        agentic_config["research_rerank_min_pending"] = 1
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))


@node(SPEC)
def main(ctx):
    skill_root = _repo_root()
    repo_root_raw = ctx.get("hyper.repo.scaffolded", "repoRoot")
    if not repo_root_raw:
        return NodeResult.fail("hyper.variants.scaffolded", "missing repoRoot context")
    repo_root = Path(repo_root_raw)

    result = NodeResult.pass_("hyper.variants.scaffolded")
    successful = True
    for variant in VARIANTS:
        log_path = ctx.report_dir / f"hyper_{variant.key}_scaffolded.log"
        proc, exp_dir = _scaffold_variant(
            skill_root=skill_root,
            repo_root=repo_root,
            variant=variant,
            log_path=log_path,
        )
        scaffolded = proc.returncode == 0 and exp_dir is not None
        successful = successful and scaffolded
        result.assertion(f"{variant.key}_new_experiment_exit_zero", proc.returncode == 0)
        result.assertion(f"{variant.key}_experiment_dir_exists", exp_dir is not None)
        result.artifact(f"{variant.key}-new-experiment-log", str(log_path))
        if not scaffolded or exp_dir is None:
            continue

        if variant.name != "default":
            _configure_llm_variant(
                exp_dir,
                agentic=variant.name == "openevolve-agentic-fitness",
            )

        code_dir = exp_dir / "code"
        run_config_path = code_dir / "run_config.json"
        run_config = json.loads(run_config_path.read_text())
        service_name = str(run_config["observability"]["service_name"])
        variant_matches = run_config.get("variant") == variant.name
        successful = successful and variant_matches
        result.assertion(f"{variant.key}_variant_matches", variant_matches)
        result.assertion(
            f"{variant.key}_trace_artifact_configured",
            bool(run_config.get("paths", {}).get("trace_artifact")),
        )
        result.artifact(f"{variant.key}-run-config", str(run_config_path))
        result.publish(f"{variant.key}ExperimentDir", str(exp_dir))
        result.publish(f"{variant.key}CodeDir", str(code_dir))
        result.publish(f"{variant.key}ServiceName", service_name)

        if variant.name != "default":
            config_path = code_dir / "config.yaml"
            config = yaml.safe_load(config_path.read_text())
            models = [
                entry.get("name")
                for entry in config.get("llm", {}).get("models", [])
            ]
            exact_model = models == [CLAUDE_SONNET_MODEL]
            one_iteration = (
                run_config["openevolve"]["iterations"] == 1
                and config.get("max_iterations") == 1
            )
            successful = successful and exact_model and one_iteration
            result.assertion(f"{variant.key}_uses_exact_claude_model", exact_model)
            result.assertion(f"{variant.key}_runs_one_iteration", one_iteration)
            if variant.name == "openevolve-agentic-fitness":
                agentic_config = config.get("fitness", {}).get("agentic", {})
                agentic_model = agentic_config.get("model") == CLAUDE_SONNET_MODEL
                agentic_one_iteration = (
                    agentic_config.get("research_rerank_interval") == 1
                    and agentic_config.get("research_rerank_min_pending") == 1
                )
                successful = successful and agentic_model and agentic_one_iteration
                result.assertion("agentic_fitness_uses_exact_claude_model", agentic_model)
                result.assertion(
                    "agentic_fitness_reranks_first_iteration",
                    agentic_one_iteration,
                )
            result.artifact(f"{variant.key}-openevolve-config", str(config_path))

    result.publish("modelPriority", CLAUDE_SONNET_MODEL)
    if not successful:
        result.failure_message = "one or more current-template fixtures were invalid"
    return result


if __name__ == "__main__":
    main()
