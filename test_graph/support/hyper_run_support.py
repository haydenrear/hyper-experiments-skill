"""Shared live-run mechanics for the all-variant observability graph."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from testgraphsdk import NodeResult, ProcessRecord


CLAUDE_SONNET_MODEL = "CLAUDE_claude-sonnet-4-6"
TRACEPARENT_RE = re.compile(
    r"^[0-9a-f]{2}-(?P<trace_id>[0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$"
)
ITERATION_COMPLETED_RE = re.compile(
    r"Iteration 1: Program [0-9a-f-]+ \(parent: [^)]+\) completed in "
)


@dataclass(frozen=True)
class RunOutcome:
    exit_code: int
    timed_out: bool
    elapsed_seconds: float
    log_path: Path
    run_text: str
    process_logs: tuple[Path, ...]
    process_log_text: str
    started_at: datetime
    ended_at: datetime


def inherited_trace_id() -> str | None:
    traceparent = (
        os.environ.get("traceparent")
        or os.environ.get("TRACEPARENT")
        or ""
    ).strip().lower()
    match = TRACEPARENT_RE.fullmatch(traceparent)
    if match is None:
        return None
    trace_id = match.group("trace_id")
    return trace_id if int(trace_id, 16) else None


def trace_artifact(code_dir: Path) -> tuple[Path, dict]:
    run_config = json.loads((code_dir / "run_config.json").read_text())
    configured = (
        run_config.get("observability", {}).get("trace_artifact")
        or run_config.get("paths", {}).get("trace_artifact")
        or "../artifacts/trace.json"
    )
    path = (code_dir / str(configured)).resolve()
    payload = json.loads(path.read_text()) if path.exists() else {}
    return path, payload


def integration_acp_skill_home() -> Path:
    """Resolve the integration constituent, never an installed stale copy."""

    return (
        Path(__file__).resolve().parents[3] / "acp-cdc-ai-python"
    ).resolve()


def _stop_acp_server(exp_dir: Path) -> None:
    stop_server = integration_acp_skill_home() / "scripts" / "stop-server.py"
    if not stop_server.exists():
        return
    try:
        subprocess.run(
            [
                str(stop_server),
                "--project-root",
                str(exp_dir),
                "--stop-timeout",
                "10",
            ],
            cwd=exp_dir,
            timeout=45,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run(
    *,
    command: list[str],
    code_dir: Path,
    exp_dir: Path,
    log_path: Path,
    timeout_seconds: int,
    env: dict[str, str],
) -> RunOutcome:
    timed_out = False
    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            command,
            cwd=code_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            exit_code = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()
            try:
                exit_code = proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                exit_code = proc.wait()
    ended_at = datetime.now(timezone.utc)
    jsonl_dir = exp_dir / "data" / "acp-openai-server" / "jsonl"
    process_logs = tuple(sorted(jsonl_dir.glob("*.process.log")))
    return RunOutcome(
        exit_code=exit_code,
        timed_out=timed_out,
        elapsed_seconds=time.monotonic() - started,
        log_path=log_path,
        run_text=log_path.read_text(errors="replace"),
        process_logs=process_logs,
        process_log_text="\n".join(
            path.read_text(errors="replace") for path in process_logs
        ),
        started_at=started_at,
        ended_at=ended_at,
    )


def run_default_node(ctx) -> NodeResult:
    fixture = "hyper.variants.scaffolded"
    exp_raw = ctx.get(fixture, "defaultExperimentDir")
    code_raw = ctx.get(fixture, "defaultCodeDir")
    expected_service = ctx.get(fixture, "defaultServiceName")
    if not exp_raw or not code_raw or not expected_service:
        return NodeResult.fail(ctx.node_id, "missing default experiment context")

    exp_dir = Path(exp_raw)
    code_dir = Path(code_raw)
    log_path = ctx.report_dir / "hyper_default_short_run.log"
    timeout_seconds = int(os.environ.get("TEST_GRAPH_DEFAULT_RUN_TIMEOUT", "1200"))
    outcome = _run(
        command=["uv", "run", "run-experiment"],
        code_dir=code_dir,
        exp_dir=exp_dir,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
        env=dict(os.environ),
    )
    artifact_path, artifact = trace_artifact(code_dir)
    graph_trace_id = inherited_trace_id()
    trace_id = artifact.get("trace_id")
    service_name = artifact.get("service_name")
    success = (
        outcome.exit_code == 0
        and not outcome.timed_out
        and trace_id == graph_trace_id
        and service_name == expected_service
        and "TODO: implement experiment logic" in outcome.run_text
        and "openevolve: ACP server ready" not in outcome.run_text
    )
    result = (
        NodeResult.pass_(ctx.node_id)
        if success
        else NodeResult.fail(
            ctx.node_id,
            f"default template run failed exit={outcome.exit_code} "
            f"timeout={outcome.timed_out}",
        )
    )
    return (
        result
        .assertion("default_run_exit_zero", outcome.exit_code == 0)
        .assertion("default_run_is_non_llm", "openevolve: ACP server ready" not in outcome.run_text)
        .assertion("default_template_body_ran", "TODO: implement experiment logic" in outcome.run_text)
        .assertion("default_trace_id_matches_graph", trace_id == graph_trace_id)
        .assertion("default_service_name_matches_config", service_name == expected_service)
        .metric("run_seconds", round(outcome.elapsed_seconds, 3))
        .artifact("run-log", str(log_path))
        .artifact("trace-artifact", str(artifact_path))
        .process(
            ProcessRecord(
                label="default-hyper-experiment",
                command=["uv", "run", "run-experiment"],
                started_at=outcome.started_at,
                ended_at=outcome.ended_at,
                exit_code=outcome.exit_code,
                log_path=str(log_path),
            )
        )
        .publish("outcome", "success" if success else "unexpected_failure")
        .publish("traceId", str(trace_id or ""))
        .publish("serviceName", str(service_name or ""))
        .publish("variant", "default")
    )


def _agentic_research_event(exp_dir: Path) -> tuple[Path, bool]:
    path = exp_dir / "logs" / "fitness_events" / "fitness_research_events.jsonl"
    if not path.exists():
        return path, False
    for line in path.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        epoch = record.get("epoch", {})
        if (
            record.get("type") == "score_epoch"
            and isinstance(epoch, dict)
            and epoch.get("created_by") == "acp-cdc-ai-python"
        ):
            return path, True
    return path, False


def run_claude_openevolve_node(ctx, *, variant_key: str) -> NodeResult:
    fixture = "hyper.variants.scaffolded"
    exp_raw = ctx.get(fixture, f"{variant_key}ExperimentDir")
    code_raw = ctx.get(fixture, f"{variant_key}CodeDir")
    expected_service = ctx.get(fixture, f"{variant_key}ServiceName")
    expected_model = ctx.get(fixture, "modelPriority")
    if not exp_raw or not code_raw or not expected_service:
        return NodeResult.fail(ctx.node_id, f"missing {variant_key} experiment context")

    exp_dir = Path(exp_raw)
    code_dir = Path(code_raw)
    acp_skill_home = integration_acp_skill_home()
    acp_launcher = acp_skill_home / "scripts" / "start-server.py"
    if not acp_launcher.exists():
        return NodeResult.fail(
            ctx.node_id,
            f"integration ACP launcher is missing at {acp_launcher}",
        )
    log_path = ctx.report_dir / f"hyper_{variant_key}_claude_sonnet_run.log"
    is_agentic = variant_key == "agentic"
    timeout_env = (
        "TEST_GRAPH_AGENTIC_RUN_TIMEOUT"
        if is_agentic
        else "TEST_GRAPH_OPENEVOLVE_RUN_TIMEOUT"
    )
    timeout_seconds = int(
        os.environ.get(timeout_env, "1200" if is_agentic else "600")
    )
    run_env = {
        **os.environ,
        "OPENAI_API_KEY": os.environ.get(
            "OPENAI_API_KEY", "local-no-auth-required"
        ),
        "OPENEVOLVE_MODEL_COOLDOWN_ON_ALL_UNAVAILABLE": "raise",
        "OPENEVOLVE_MODEL_COOLDOWN_DEFAULT_SECONDS": os.environ.get(
            "TEST_GRAPH_OPENEVOLVE_DEFAULT_COOLDOWN_SECONDS", "86400"
        ),
        "ACP_CDC_AI_PYTHON_SKILL_HOME": str(acp_skill_home),
    }
    try:
        outcome = _run(
            command=["uv", "run", "run-openevolve"],
            code_dir=code_dir,
            exp_dir=exp_dir,
            log_path=log_path,
            timeout_seconds=timeout_seconds,
            env=run_env,
        )
        artifact_path, artifact = trace_artifact(code_dir)
        graph_trace_id = inherited_trace_id()
        trace_id = artifact.get("trace_id")
        service_name = artifact.get("service_name")
        agentic_event_path, agentic_research_completed = _agentic_research_event(exp_dir)
        acp_ready = "openevolve: ACP server ready" in outcome.run_text
        model_configured = expected_model == CLAUDE_SONNET_MODEL
        model_initialized = (
            f"Initialized OpenAI LLM with model: {CLAUDE_SONNET_MODEL}"
            in outcome.run_text
        )
        claude_agent_started = "claude-agent-acp" in outcome.process_log_text
        child_trace_received = (
            bool(graph_trace_id)
            and f"acp_child_trace_id={graph_trace_id}" in outcome.process_log_text
        )
        iteration_completed = ITERATION_COMPLETED_RE.search(outcome.run_text) is not None
        iteration_failed = "Iteration 1 error:" in outcome.run_text
        llm_failed = "LLM generation failed" in outcome.run_text
        evolution_completed = "openevolve: evolution complete." in outcome.run_text
        success = (
            outcome.exit_code == 0
            and not outcome.timed_out
            and acp_ready
            and model_configured
            and model_initialized
            and claude_agent_started
            and child_trace_received
            and iteration_completed
            and not iteration_failed
            and not llm_failed
            and evolution_completed
            and trace_id == graph_trace_id
            and service_name == expected_service
            and (not is_agentic or agentic_research_completed)
        )
        result = (
            NodeResult.pass_(ctx.node_id)
            if success
            else NodeResult.fail(
                ctx.node_id,
                f"{variant_key} Claude run failed exit={outcome.exit_code} "
                f"timeout={outcome.timed_out}",
            )
        )
        result.assertion("acp_server_ready", acp_ready)
        result.assertion("integration_acp_launcher_used", acp_launcher.exists())
        result.assertion("exact_claude_sonnet_model_configured", model_configured)
        result.assertion("exact_claude_sonnet_model_initialized", model_initialized)
        result.assertion("claude_agent_acp_started", claude_agent_started)
        result.assertion(
            "claude_agent_child_received_graph_trace",
            child_trace_received,
        )
        result.assertion("one_generation_completed", iteration_completed)
        result.assertion("generation_has_no_error", not iteration_failed)
        result.assertion("no_llm_generation_failure", not llm_failed)
        result.assertion("evolution_completed", evolution_completed)
        result.assertion("trace_id_matches_graph", trace_id == graph_trace_id)
        result.assertion("service_name_matches_config", service_name == expected_service)
        if is_agentic:
            result.assertion(
                "agentic_research_epoch_created_by_acp",
                agentic_research_completed,
            )
            result.artifact("agentic-fitness-research-events", str(agentic_event_path))
        result.metric("run_seconds", round(outcome.elapsed_seconds, 3))
        result.artifact("run-log", str(log_path))
        result.artifact("trace-artifact", str(artifact_path))
        for index, process_log in enumerate(outcome.process_logs, start=1):
            result.artifact(f"claude-agent-process-log-{index}", str(process_log))
        result.process(
            ProcessRecord(
                label=f"{variant_key}-claude-openevolve",
                command=["uv", "run", "run-openevolve"],
                started_at=outcome.started_at,
                ended_at=outcome.ended_at,
                exit_code=outcome.exit_code,
                log_path=str(log_path),
            )
        )
        result.publish("outcome", "success" if success else "unexpected_failure")
        result.publish("traceId", str(trace_id or ""))
        result.publish("serviceName", str(service_name or ""))
        result.publish(
            "variant",
            "openevolve-agentic-fitness" if is_agentic else "evolve",
        )
        result.publish("acpSkillHome", str(acp_skill_home))
        return result
    finally:
        _stop_acp_server(exp_dir)
