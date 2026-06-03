# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Run the best program produced by the OpenEvolve smoke run."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from testgraphsdk import NodeResult, NodeSpec, node


SPEC = (
    NodeSpec("openevolve.best_program.runs")
    .kind("assertion")
    .depends_on("openevolve.experiment.scaffolded")
    .depends_on("openevolve.gemini.short_run")
    .tags("openevolve", "deploy", "best-program")
    .timeout("5m")
    .side_effects("filesystem:reads-fixture", "process:runs-best-program")
    .output("bestProgramPath", "string")
)


@node(SPEC)
def main(ctx):
    outcome = ctx.get("openevolve.gemini.short_run", "outcome")
    exp_raw = ctx.get("openevolve.experiment.scaffolded", "experimentDir")
    code_raw = ctx.get("openevolve.experiment.scaffolded", "codeDir")
    if not exp_raw or not code_raw:
        return NodeResult.fail("openevolve.best_program.runs", "missing experiment context")

    exp_dir = Path(exp_raw)
    code_dir = Path(code_raw)
    best_program = exp_dir / "logs" / "openevolve_output" / "best" / "best_program.py"
    run_log = ctx.report_dir / "openevolve_best_program_runs.log"

    if outcome != "success":
        return (
            NodeResult.pass_("openevolve.best_program.runs")
            .assertion("short_run_success", False)
            .assertion("best_program_run_skipped", True)
            .artifact("run-log", str(run_log))
            .publish("bestProgramPath", str(best_program))
            .log(f"skipped best-program run because short_run outcome={outcome!r}")
        )

    if not best_program.exists():
        return (
            NodeResult.fail("openevolve.best_program.runs", f"missing best program at {best_program}")
            .assertion("short_run_success", True)
            .assertion("best_program_exists", False)
            .publish("bestProgramPath", str(best_program))
        )

    started = time.time()
    with run_log.open("wb") as log:
        proc = subprocess.Popen(
            ["uv", "run", "run-best-program", "--print-path"],
            cwd=code_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            exit_code = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                exit_code = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait()

    elapsed = time.time() - started
    run_text = run_log.read_text(errors="replace") if run_log.exists() else ""
    passed = exit_code == 0 and str(best_program) in run_text
    return (
        (NodeResult.pass_("openevolve.best_program.runs") if passed else NodeResult.fail(
            "openevolve.best_program.runs",
            f"run-best-program failed exit={exit_code}: {run_text}",
        ))
        .assertion("short_run_success", True)
        .assertion("best_program_exists", best_program.exists())
        .assertion("run_best_program_exit_zero", exit_code == 0)
        .assertion("run_best_program_printed_path", str(best_program) in run_text)
        .metric("run_seconds", round(elapsed, 3))
        .artifact("run-log", str(run_log))
        .publish("bestProgramPath", str(best_program))
    )


if __name__ == "__main__":
    main()
