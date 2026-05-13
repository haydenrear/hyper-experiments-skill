# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk", "pyyaml>=6.0"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Scaffold one evolve experiment and configure it for a tiny Gemini run."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from testgraphsdk import NodeResult, NodeSpec, node


SPEC = (
    NodeSpec("openevolve.experiment.scaffolded")
    .kind("fixture")
    .depends_on("hyper.repo.scaffolded")
    .tags("openevolve", "gemini", "fixture")
    .timeout("180s")
    .output("experimentDir", "string")
    .output("codeDir", "string")
    .output("modelPriority", "string")
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _model_priority() -> list[str]:
    raw = os.environ.get("TEST_GRAPH_GEMINI_MODELS", "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return ["GEMINI_gemini-2.5-pro", "GEMINI_gemini-2.5-flash"]


@node(SPEC)
def main(ctx):
    skill_root = _repo_root()
    repo_root_raw = ctx.get("hyper.repo.scaffolded", "repoRoot")
    if not repo_root_raw:
        return NodeResult.fail("openevolve.experiment.scaffolded", "missing repoRoot context")
    repo_root = Path(repo_root_raw)

    cmd = [
        sys.executable,
        str(skill_root / "scripts" / "new_experiment.py"),
        "--experiments-root",
        str(repo_root),
        "--family",
        "gemini_smoke",
        "--title",
        "gemini capacity smoke",
        "--question",
        "Can OpenEvolve reach Gemini, or does it record a capacity cooldown?",
        "--delta",
        "test graph short Gemini run",
        "--invariant",
        "generated scaffold only",
        "--command",
        "uv run run-experiment",
        "--variant",
        "evolve",
        "--type",
        "root",
    ]
    proc = subprocess.run(
        cmd,
        cwd=skill_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "HYPER_EXPERIMENTS_SKILL_HOME": str(skill_root)},
    )
    log_path = ctx.report_dir / "openevolve_experiment_scaffolded.log"
    log_path.write_text(proc.stdout)
    if proc.returncode != 0:
        return (
            NodeResult.fail("openevolve.experiment.scaffolded", "new_experiment failed")
            .assertion("new_experiment_exit_zero", False)
            .artifact("new-experiment-log", str(log_path))
        )

    matches = sorted((repo_root / "experiments" / "families" / "gemini_smoke").glob("exp-*"))
    if len(matches) != 1:
        return (
            NodeResult.fail(
                "openevolve.experiment.scaffolded",
                f"expected one experiment dir, found {len(matches)}",
            )
            .artifact("new-experiment-log", str(log_path))
        )

    exp_dir = matches[0]
    code_dir = exp_dir / "code"
    model_priority = _model_priority()

    run_config_path = code_dir / "run_config.json"
    run_config = json.loads(run_config_path.read_text())
    run_config["openevolve"]["iterations"] = int(os.environ.get("TEST_GRAPH_OPENEVOLVE_ITERATIONS", "1"))
    run_config_path.write_text(json.dumps(run_config, indent=2) + "\n")

    config_path = code_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["max_iterations"] = run_config["openevolve"]["iterations"]
    config["checkpoint_interval"] = 1
    config["llm"]["models"] = [{"name": name, "weight": 1.0} for name in model_priority]
    config["llm"].pop("primary_model", None)
    config["llm"].pop("primary_model_weight", None)
    config["llm"].pop("secondary_model", None)
    config["llm"].pop("secondary_model_weight", None)
    config["llm"]["retries"] = 0
    config["llm"]["timeout"] = int(os.environ.get("TEST_GRAPH_OPENEVOLVE_TIMEOUT", "300"))
    config["evaluator"]["parallel_evaluations"] = 1
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))

    result = (
        NodeResult.pass_("openevolve.experiment.scaffolded")
        .assertion("new_experiment_exit_zero", True)
        .assertion("experiment_dir_exists", exp_dir.is_dir())
        .assertion("capacity_helper_exists", (code_dir / "openevolve_capacity.py").exists())
        .assertion("diff_prompt_exists", (code_dir / "prompt-templates" / "diff_user.txt").exists())
        .artifact("new-experiment-log", str(log_path))
        .artifact("run-config", str(run_config_path))
        .artifact("openevolve-config", str(config_path))
        .publish("experimentDir", str(exp_dir))
        .publish("codeDir", str(code_dir))
        .publish("modelPriority", ",".join(model_priority))
    )
    return result


if __name__ == "__main__":
    main()
