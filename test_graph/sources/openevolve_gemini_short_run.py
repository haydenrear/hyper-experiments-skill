# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Run one tiny OpenEvolve/Gemini pass through the ACP OpenAI-compatible server."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from testgraphsdk import NodeResult, NodeSpec, node


CAPACITY_SIGNAL_RE = re.compile(
    r"exhausted your (?:daily quota|capacity) on this model",
    re.IGNORECASE | re.DOTALL,
)

SPEC = (
    NodeSpec("openevolve.gemini.short_run")
    .kind("assertion")
    .depends_on("openevolve.experiment.scaffolded")
    .tags("openevolve", "gemini", "acp", "live")
    .timeout("45m")
    .side_effects("process:starts-acp-server", "network:google-gemini", "filesystem:writes-fixture")
    .output("outcome", "string")
)


def _acp_skill_home() -> Path:
    raw = os.environ.get("ACP_CDC_AI_PYTHON_SKILL_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    sm_home = Path(os.environ.get("SKILL_MANAGER_HOME", str(Path.home() / ".skill-manager")))
    return sm_home / "skills" / "acp-cdc-ai-python"


def _read_server_info(exp_dir: Path) -> dict | None:
    path = exp_dir / ".acp-server" / "server.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_for_server(exp_dir: Path, timeout_s: int = 180) -> dict | None:
    deadline = time.time() + timeout_s
    last_info: dict | None = None
    while time.time() < deadline:
        info = _read_server_info(exp_dir)
        if info:
            last_info = info
            try:
                pid = int(info["pid"])
                host = str(info["host"])
                port = int(info["port"])
            except (KeyError, TypeError, ValueError):
                time.sleep(1)
                continue
            if not _pid_alive(pid):
                time.sleep(1)
                continue
            url = f"http://{host}:{port}/v1/models"
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if 200 <= resp.status < 500:
                        return info
            except (OSError, urllib.error.URLError):
                time.sleep(1)
                continue
        time.sleep(1)
    return last_info


def _terminate(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    for _ in range(20):
        if not _pid_alive(pid):
            return
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _capacity_events(exp_dir: Path) -> list[dict]:
    path = exp_dir / "data" / "openevolve_model_capacity_events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _capacity_state(exp_dir: Path) -> dict:
    path = exp_dir / "data" / "openevolve_model_capacity.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _valid_resume_at(raw: str | None) -> bool:
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt > datetime.now(timezone.utc)


@node(SPEC)
def main(ctx):
    exp_raw = ctx.get("openevolve.experiment.scaffolded", "experimentDir")
    code_raw = ctx.get("openevolve.experiment.scaffolded", "codeDir")
    if not exp_raw or not code_raw:
        return NodeResult.fail("openevolve.gemini.short_run", "missing experiment context")

    exp_dir = Path(exp_raw)
    code_dir = Path(code_raw)
    acp_home = _acp_skill_home()
    start_server = acp_home / "scripts" / "start-server.py"
    if not start_server.exists():
        return NodeResult.fail(
            "openevolve.gemini.short_run",
            f"missing acp-cdc-ai-python launcher at {start_server}",
        )

    process_dir = exp_dir / "data" / "acp-openai-server" / "process"
    process_dir.mkdir(parents=True, exist_ok=True)
    server_stdout = process_dir / "stdout.log"
    server_stderr = process_dir / "stderr.log"
    run_log = ctx.report_dir / "openevolve_gemini_short_run.log"

    server_proc: subprocess.Popen | None = None
    server_pid: int | None = None
    try:
        with server_stdout.open("ab") as out, server_stderr.open("ab") as err:
            server_proc = subprocess.Popen(
                [
                    str(start_server),
                    "--project-root",
                    str(exp_dir),
                    "--host",
                    "127.0.0.1",
                    "--log-dir",
                    "data/acp-openai-server/jsonl",
                ],
                cwd=exp_dir,
                stdout=out,
                stderr=err,
                env=os.environ.copy(),
            )

        info = _wait_for_server(exp_dir)
        if info:
            try:
                server_pid = int(info["pid"])
            except (KeyError, TypeError, ValueError):
                server_pid = server_proc.pid
        if not info or not server_pid or not _pid_alive(server_pid):
            return (
                NodeResult.fail("openevolve.gemini.short_run", "ACP server did not become ready")
                .assertion("acp_server_ready", False)
                .artifact("server-stdout", str(server_stdout))
                .artifact("server-stderr", str(server_stderr))
            )

        timeout_s = int(os.environ.get("TEST_GRAPH_OPENEVOLVE_RUN_TIMEOUT", "600"))
        run_env = {
            **os.environ,
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "local-no-auth-required"),
            "OPENEVOLVE_MODEL_COOLDOWN_ON_ALL_UNAVAILABLE": "raise",
            "OPENEVOLVE_MODEL_COOLDOWN_DEFAULT_SECONDS": os.environ.get(
                "TEST_GRAPH_OPENEVOLVE_DEFAULT_COOLDOWN_SECONDS", "86400"
            ),
        }
        timed_out = False
        started = time.time()
        with run_log.open("wb") as log:
            proc = subprocess.Popen(
                ["uv", "run", "run-experiment"],
                cwd=code_dir,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=run_env,
            )
            try:
                exit_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.terminate()
                try:
                    exit_code = proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    exit_code = proc.wait()

        elapsed = time.time() - started
        run_text = run_log.read_text(errors="replace") if run_log.exists() else ""
        events = _capacity_events(exp_dir)
        state = _capacity_state(exp_dir)
        capacity_events = [e for e in events if e.get("event") == "capacity_exhausted"]
        resume_times = [
            e.get("resume_at") for e in capacity_events if _valid_resume_at(e.get("resume_at"))
        ]
        state_resume_times = [
            entry.get("resume_at")
            for entry in (state.get("models") or {}).values()
            if isinstance(entry, dict) and _valid_resume_at(entry.get("resume_at"))
        ]

        llm_generation_failed = "LLM generation failed" in run_text
        capacity_in_run_log = CAPACITY_SIGNAL_RE.search(run_text) is not None
        success = (
            exit_code == 0
            and "openevolve: evolution complete." in run_text
            and not llm_generation_failed
            and not capacity_in_run_log
        )
        quota_path = bool(capacity_events and (resume_times or state_resume_times))
        accepted = success or quota_path
        outcome = "success" if success else "quota_exhausted" if quota_path else "unexpected_failure"

        result = (
            (NodeResult.pass_("openevolve.gemini.short_run") if accepted else NodeResult.fail(
                "openevolve.gemini.short_run",
                f"expected success or quota exhaustion, got exit={exit_code} timeout={timed_out}",
            ))
            .assertion("acp_server_ready", True)
            .assertion("outcome_success_or_quota", accepted)
            .assertion("success_has_completed_marker", (not success) or "openevolve: evolution complete." in run_text)
            .assertion("success_has_no_llm_failure", (not success) or not llm_generation_failed)
            .assertion("quota_has_resume_time", (not quota_path) or bool(resume_times or state_resume_times))
            .metric("run_seconds", round(elapsed, 3))
            .metric("capacity_exhausted_events", len(capacity_events))
            .artifact("run-log", str(run_log))
            .artifact("server-stdout", str(server_stdout))
            .artifact("server-stderr", str(server_stderr))
            .publish("outcome", outcome)
        )
        state_path = exp_dir / "data" / "openevolve_model_capacity.json"
        event_path = exp_dir / "data" / "openevolve_model_capacity_events.jsonl"
        if state_path.exists():
            result.artifact("capacity-state", str(state_path))
        if event_path.exists():
            result.artifact("capacity-events", str(event_path))
        return result.log(f"outcome={outcome} exit={exit_code} timed_out={timed_out}")
    finally:
        info = _read_server_info(exp_dir)
        if info and not server_pid:
            try:
                server_pid = int(info["pid"])
            except (KeyError, TypeError, ValueError):
                server_pid = None
        _terminate(server_pid or (server_proc.pid if server_proc else None))


if __name__ == "__main__":
    main()
