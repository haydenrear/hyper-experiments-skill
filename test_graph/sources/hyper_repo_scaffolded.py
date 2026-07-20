# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Scaffold a temporary hyper-experiments repo for current-template checks."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from testgraphsdk import NodeResult, NodeSpec, node


SPEC = (
    NodeSpec("hyper.repo.scaffolded")
    .kind("fixture")
    .tags("openevolve", "fixture")
    .timeout("120s")
    .side_effects("fs:tmp")
    .output("repoRoot", "string")
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@node(SPEC)
def main(ctx):
    skill_root = _repo_root()
    work_dir = ctx.report_dir / "work" / "hyper-experiment-repo"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(skill_root / "scripts" / "init_project.py"),
        "--root",
        str(work_dir),
        "--project-name",
        "test-graph-all-variant-observability",
        "--description",
        "test graph fixture for all-variant observability validation",
        "--variant",
        "default",
    ]
    proc = subprocess.run(
        cmd,
        cwd=skill_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "HYPER_EXPERIMENTS_SKILL_HOME": str(skill_root)},
    )

    log_path = ctx.report_dir / "hyper_repo_scaffolded.log"
    log_path.write_text(proc.stdout)
    ok = proc.returncode == 0 and (work_dir / "hyper-experiments.md").exists()

    result = (
        NodeResult.pass_("hyper.repo.scaffolded")
        .assertion("init_project_exit_zero", proc.returncode == 0)
        .assertion("repo_marker_exists", (work_dir / "hyper-experiments.md").exists())
        .artifact("init-project-log", str(log_path))
        .publish("repoRoot", str(work_dir))
    )
    if not ok:
        result.failure_message = f"init_project failed with exit {proc.returncode}"
    return result


if __name__ == "__main__":
    main()
