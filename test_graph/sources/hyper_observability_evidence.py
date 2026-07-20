# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Correlate all graph, experiment, and ACP telemetry through monitoring."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

from testgraphsdk import NodeResult, NodeSpec, node


ACTION_NODES = {
    "default": "hyper.default.short_run",
    "evolve": "hyper.evolve.claude_sonnet.short_run",
    "agentic": "hyper.agentic.claude_sonnet.short_run",
}
TEST_GRAPH_SERVICES = {"test-graph", "test-graph-node-python"}
ACP_SERVICE = "acp-cdc-ai-python"
TRACEPARENT_RE = re.compile(
    r"^[0-9a-f]{2}-(?P<trace_id>[0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$"
)
CORRELATION_METRIC = "tracing_observability_trace_correlation"
ACP_LIFECYCLE_EVENTS = {
    "conversation.pinned",
    "turn.selected",
    "process.started",
    "turn.completed",
}
NATIVE_SERIES = {
    "default": {
        ("hyper_experiments_boundaries", "boundary", "bootstrap"),
        ("hyper_experiments_iteration", "stage", "scaffold"),
    },
    "evolve": {
        ("hyper_experiments_boundaries", "boundary", "bootstrap"),
        ("hyper_experiments_iteration", "stage", "openevolve-dispatch"),
        ("hyper_experiments_iteration", "stage", "openevolve-complete"),
        ("hyper_experiments_subprocess", "stage", "acp-server-launch"),
        ("hyper_experiments_evaluation", "stage", "stage1"),
        ("hyper_experiments_evaluation", "stage", "full"),
    },
    "agentic": {
        ("hyper_experiments_boundaries", "boundary", "bootstrap"),
        ("hyper_experiments_iteration", "stage", "openevolve-dispatch"),
        ("hyper_experiments_iteration", "stage", "openevolve-complete"),
        ("hyper_experiments_subprocess", "stage", "acp-server-launch"),
        ("hyper_experiments_evaluation", "stage", "stage1"),
        ("hyper_experiments_evaluation", "stage", "full"),
    },
}

SPEC = (
    NodeSpec("hyper.observability.evidence")
    .kind("evidence")
    .depends_on(ACTION_NODES["default"])
    .depends_on(ACTION_NODES["evolve"])
    .depends_on(ACTION_NODES["agentic"])
    .tags("observability", "traces", "structured-logs", "metrics", "monitoring")
    .timeout("10m")
    .side_effects("fs:tmp", "net:local", "net:external")
    .output("traceId", "string")
)


def _trace_id_from_traceparent(value: str | None) -> str | None:
    match = TRACEPARENT_RE.fullmatch((value or "").strip().lower())
    if match is None:
        return None
    trace_id = match.group("trace_id")
    return trace_id if int(trace_id, 16) else None


def _graph_trace_id(ctx) -> tuple[str | None, dict[str, str | None]]:
    sources: dict[str, str | None] = {}
    carrier_path = ctx.report_dir / "trace-context.json"
    try:
        carrier = json.loads(carrier_path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        carrier = {}
    sources["carrier"] = _trace_id_from_traceparent(carrier.get("traceparent"))
    sources["environment"] = _trace_id_from_traceparent(
        os.environ.get("traceparent") or os.environ.get("TRACEPARENT")
    )
    for variant, node_id in ACTION_NODES.items():
        sources[f"{variant}.published"] = ctx.get(node_id, "traceId")
        envelope = ctx.upstream(node_id) or {}
        sources[f"{variant}.envelope"] = envelope.get("traceId")
    nonempty = [value for value in sources.values() if value]
    return (nonempty[0] if nonempty else None), sources


def _service_name(mapping: dict) -> str | None:
    for key in ("service_name", "service.name", "service"):
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    resource = mapping.get("resource")
    if isinstance(resource, dict):
        return _service_name(resource)
    attributes = mapping.get("attributes")
    if isinstance(attributes, dict):
        return _service_name(attributes)
    return None


def _span_services(payload: dict) -> set[str]:
    return {
        service
        for item in payload.get("spans", [])
        if isinstance(item, dict)
        for service in [_service_name(item)]
        if service
    }


def _parsed_log_candidates(item: dict) -> list[dict]:
    try:
        outer = json.loads(item.get("line", ""))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(outer, dict):
        return []

    candidates: list[dict] = [outer]
    body = outer.get("body")
    if isinstance(body, str):
        try:
            parsed_body = json.loads(body)
        except json.JSONDecodeError:
            parsed_body = None
        if isinstance(parsed_body, dict):
            candidates.append(parsed_body)
    elif isinstance(body, dict):
        candidates.append(body)

    labels = item.get("labels")
    if isinstance(labels, dict):
        candidates.append(labels)
    return candidates


def _structured_log_services(payload: dict) -> set[str]:
    services: set[str] = set()
    for item in payload.get("logs", []):
        if not isinstance(item, dict):
            continue
        for candidate in _parsed_log_candidates(item):
            if service := _service_name(candidate):
                services.add(service)
    return services


def _openevolve_log_services(payload: dict) -> set[str]:
    services: set[str] = set()
    for item in payload.get("logs", []):
        if not isinstance(item, dict):
            continue
        candidates = _parsed_log_candidates(item)
        service_names = {
            service
            for candidate in candidates
            for service in [_service_name(candidate)]
            if service
        }
        logger_names = {
            str(candidate.get("logger", ""))
            for candidate in candidates
            if candidate.get("logger")
        }
        if any(name.startswith("openevolve") for name in logger_names):
            services.update(service_names)
    return services


def _canonical_metric_name(name: str) -> str:
    normalized = name.replace(".", "_")
    return normalized.removesuffix("_total")


def _metric_series(payload: dict) -> Iterable[dict]:
    for item in payload.get("metrics", []):
        if isinstance(item, dict) and isinstance(item.get("metric"), dict):
            yield item


def _correlation_metric_services(payload: dict, trace_id: str) -> set[str]:
    services: set[str] = set()
    for series in _metric_series(payload):
        labels = series["metric"]
        metric_name = _canonical_metric_name(str(labels.get("__name__", "")))
        if metric_name != CORRELATION_METRIC:
            continue
        if labels.get("trace_id") != trace_id or not series.get("values"):
            continue
        if service := _service_name(labels):
            services.add(service)
    return services


def _correlation_metric_instances(
    payload: dict,
    *,
    trace_id: str,
    service_name: str,
) -> set[str]:
    instances: set[str] = set()
    for series in _metric_series(payload):
        labels = series["metric"]
        if (
            _canonical_metric_name(str(labels.get("__name__", "")))
            != CORRELATION_METRIC
            or labels.get("trace_id") != trace_id
            or _service_name(labels) != service_name
            or not series.get("values")
        ):
            continue
        instance = labels.get("service_instance_id")
        if isinstance(instance, str) and instance:
            instances.add(instance)
    return instances


def _trace_coverage(
    payload: dict,
    *,
    trace_id: str,
    expected_services: set[str],
) -> tuple[set[str], set[str], set[str]]:
    return (
        expected_services - _span_services(payload),
        expected_services - _structured_log_services(payload),
        expected_services - _correlation_metric_services(payload, trace_id),
    )


def _run_json(command: list[str], *, timeout: int = 180) -> tuple[int, dict, str, str]:
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return proc.returncode, payload, proc.stdout, proc.stderr


def _native_metric_labels(
    payload: dict,
    *,
    allowed_instances: set[str] | None = None,
) -> dict[str, list[dict]]:
    data = payload.get("data", {})
    results = data.get("result", []) if isinstance(data, dict) else []
    labels_by_name: dict[str, list[dict]] = {}
    for series in results:
        if not isinstance(series, dict):
            continue
        labels = series.get("metric", {})
        if not isinstance(labels, dict):
            continue
        if allowed_instances is not None and (
            labels.get("service_instance_id") not in allowed_instances
        ):
            continue
        has_samples = bool(series.get("values") or series.get("value"))
        if not has_samples:
            continue
        name = str(labels.get("__name__", ""))
        if name:
            labels_by_name.setdefault(_canonical_metric_name(name), []).append(labels)
    return labels_by_name


def _missing_native_series(
    payload: dict,
    expected: set[tuple[str, str, str]],
    *,
    allowed_instances: set[str] | None = None,
) -> set[str]:
    labels_by_name = _native_metric_labels(
        payload,
        allowed_instances=allowed_instances,
    )
    missing: set[str] = set()
    for metric_name, label_name, label_value in expected:
        if not any(
            labels.get(label_name) == label_value
            for labels in labels_by_name.get(metric_name, [])
        ):
            missing.add(f"{metric_name}{{{label_name}={label_value}}}")
    return missing


def _promql_expression(service_name: str) -> str:
    escaped = service_name.replace("\\", "\\\\").replace('"', '\\"')
    return (
        '{__name__=~"hyper_experiments_'
        '(boundaries|iteration|subprocess|evaluation)(_total)?",'
        f'service_name="{escaped}"}}'
    )


def _acp_native_events(
    payload: dict,
    *,
    allowed_instances: set[str],
) -> set[str]:
    labels = _native_metric_labels(
        payload,
        allowed_instances=allowed_instances,
    ).get("acp_server_events", [])
    return {
        str(item["event"])
        for item in labels
        if item.get("event") in ACP_LIFECYCLE_EVENTS
        and item.get("provider") == "claude"
        and item.get("outcome") == "ok"
    }


@node(SPEC)
def main(ctx):
    trace_id, trace_sources = _graph_trace_id(ctx)
    trace_ids_match = bool(trace_id) and all(
        value == trace_id for value in trace_sources.values()
    )
    if not trace_id:
        return NodeResult.fail(ctx.node_id, "Test Graph trace ID is unavailable")

    services_by_variant = {
        variant: ctx.get(node_id, "serviceName") or ""
        for variant, node_id in ACTION_NODES.items()
    }
    integration_acp_home = (
        Path(__file__).resolve().parents[3] / "acp-cdc-ai-python"
    ).resolve()
    acp_homes = {
        variant: ctx.get(ACTION_NODES[variant], "acpSkillHome")
        for variant in ("evolve", "agentic")
    }
    integration_acp_bound = (
        (integration_acp_home / "scripts" / "start-server.py").exists()
        and all(
            value == str(integration_acp_home)
            for value in acp_homes.values()
        )
    )
    expected_services = {
        *TEST_GRAPH_SERVICES,
        ACP_SERVICE,
        *services_by_variant.values(),
    }
    expected_services.discard("")

    monitoring = shutil.which("monitoring")
    if monitoring is None:
        return (
            NodeResult.fail(ctx.node_id, "monitoring CLI is not installed on PATH")
            .assertion("graph_trace_id_sources_match", trace_ids_match)
            .assertion("monitoring_cli_available", False)
            .publish("traceId", trace_id)
        )

    settle_seconds = int(os.environ.get("TEST_GRAPH_MONITORING_SETTLE_SECONDS", "180"))
    deadline = time.monotonic() + settle_seconds
    trace_command = [
        monitoring,
        "trace",
        trace_id,
        "--since",
        "3h",
        "--require-all",
        "--json",
    ]
    trace_exit = -1
    trace_payload: dict = {}
    trace_stdout = ""
    trace_stderr = ""
    missing_spans = set(expected_services)
    missing_logs = set(expected_services)
    missing_correlation_metrics = set(expected_services)
    expected_openevolve_log_services = {
        services_by_variant["evolve"],
        services_by_variant["agentic"],
    }
    expected_openevolve_log_services.discard("")
    missing_openevolve_logs = set(expected_openevolve_log_services)
    while True:
        trace_exit, trace_payload, trace_stdout, trace_stderr = _run_json(
            trace_command
        )
        (
            missing_spans,
            missing_logs,
            missing_correlation_metrics,
        ) = _trace_coverage(
            trace_payload,
            trace_id=trace_id,
            expected_services=expected_services,
        )
        missing_openevolve_logs = (
            expected_openevolve_log_services
            - _openevolve_log_services(trace_payload)
        )
        if (
            trace_exit == 0
            and not missing_spans
            and not missing_logs
            and not missing_correlation_metrics
            and not missing_openevolve_logs
        ):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(10)

    trace_path = ctx.report_dir / "monitoring-trace.json"
    trace_path.write_text(trace_stdout)
    trace_log_path = ctx.report_dir / "monitoring-trace.stderr.log"
    trace_log_path.write_text(trace_stderr)

    native_instances = {
        variant: _correlation_metric_instances(
            trace_payload,
            trace_id=trace_id,
            service_name=service_name,
        )
        for variant, service_name in services_by_variant.items()
    }
    acp_instances = _correlation_metric_instances(
        trace_payload,
        trace_id=trace_id,
        service_name=ACP_SERVICE,
    )
    native_missing: dict[str, set[str]] = {
        variant: _missing_native_series({}, expected)
        for variant, expected in NATIVE_SERIES.items()
    }
    native_artifacts: dict[str, Path] = {}
    native_logs: dict[str, Path] = {}
    acp_native_path = ctx.report_dir / "monitoring-native-metrics-acp.json"
    acp_native_log_path = (
        ctx.report_dir / "monitoring-native-metrics-acp.stderr.log"
    )
    acp_events: set[str] = set()
    native_deadline = time.monotonic() + settle_seconds
    while True:
        for variant, service_name in services_by_variant.items():
            expression = _promql_expression(service_name)
            exit_code, payload, stdout, stderr = _run_json(
                [monitoring, "promql", expression, "--since", "3h"]
            )
            native_missing[variant] = (
                _missing_native_series(
                    payload,
                    NATIVE_SERIES[variant],
                    allowed_instances=native_instances[variant],
                )
                if exit_code == 0
                else _missing_native_series({}, NATIVE_SERIES[variant])
            )
            artifact_path = (
                ctx.report_dir / f"monitoring-native-metrics-{variant}.json"
            )
            artifact_path.write_text(stdout)
            log_path = (
                ctx.report_dir
                / f"monitoring-native-metrics-{variant}.stderr.log"
            )
            log_path.write_text(stderr)
            native_artifacts[variant] = artifact_path
            native_logs[variant] = log_path
        acp_exit, acp_payload, acp_stdout, acp_stderr = _run_json(
            [
                monitoring,
                "promql",
                (
                    '{__name__=~"acp_server_events(_total)?",'
                    'service_name="acp-cdc-ai-python",provider="claude",'
                    'event=~"conversation[.]pinned|turn[.]selected|'
                    'process[.]started|turn[.]completed"}'
                ),
                "--since",
                "3h",
            ]
        )
        if acp_exit == 0:
            acp_events = _acp_native_events(
                acp_payload,
                allowed_instances=acp_instances,
            )
        acp_native_path.write_text(acp_stdout)
        acp_native_log_path.write_text(acp_stderr)
        if (
            all(not missing for missing in native_missing.values())
            and ACP_LIFECYCLE_EVENTS <= acp_events
        ):
            break
        if time.monotonic() >= native_deadline:
            break
        time.sleep(10)

    trace_complete = trace_exit == 0 and bool(trace_payload.get("complete"))
    all_services_present = not (
        missing_spans or missing_logs or missing_correlation_metrics
    )
    openevolve_logs_complete = not missing_openevolve_logs
    native_complete = all(not missing for missing in native_missing.values())
    acp_missing_events = ACP_LIFECYCLE_EVENTS - acp_events
    acp_native_complete = not acp_missing_events
    passed = (
        trace_ids_match
        and integration_acp_bound
        and trace_complete
        and all_services_present
        and openevolve_logs_complete
        and native_complete
        and acp_native_complete
    )
    missing_summary = {
        "spans": sorted(missing_spans),
        "logs": sorted(missing_logs),
        "openevolve_logs": sorted(missing_openevolve_logs),
        "correlation_metrics": sorted(missing_correlation_metrics),
        "acp_native_metrics": sorted(acp_missing_events),
        "native_metric_instances": {
            **{
                variant: sorted(instances)
                for variant, instances in native_instances.items()
            },
            "acp": sorted(acp_instances),
        },
        "native_metrics": {
            variant: sorted(missing)
            for variant, missing in native_missing.items()
            if missing
        },
    }
    result = (
        NodeResult.pass_(ctx.node_id)
        if passed
        else NodeResult.fail(
            ctx.node_id,
            f"observability evidence incomplete: {json.dumps(missing_summary, sort_keys=True)}",
        )
    )
    result.assertion("graph_trace_id_sources_match", trace_ids_match)
    result.assertion("integration_acp_constituent_bound", integration_acp_bound)
    result.assertion("monitoring_cli_available", True)
    result.assertion("monitoring_trace_require_all_passed", trace_complete)
    result.assertion("all_expected_services_have_spans", not missing_spans)
    result.assertion("all_expected_services_have_structured_logs", not missing_logs)
    result.assertion(
        "both_llm_variants_have_openevolve_structured_logs",
        openevolve_logs_complete,
    )
    result.assertion(
        "all_expected_services_have_trace_correlation_metrics",
        not missing_correlation_metrics,
    )
    for variant, missing in native_missing.items():
        result.assertion(f"{variant}_native_metrics_present", not missing)
        if variant != "default":
            result.assertion(
                f"{variant}_evaluator_metric_present",
                not any(
                    item.startswith("hyper_experiments_evaluation{")
                    for item in missing
                ),
            )
        result.artifact(
            f"{variant}-native-metrics",
            str(native_artifacts[variant]),
        )
        result.artifact(
            f"{variant}-native-metrics-log",
            str(native_logs[variant]),
        )
    result.assertion(
        "native_metrics_scoped_to_current_trace_instances",
        bool(acp_instances) and all(native_instances.values()),
    )
    for event in sorted(ACP_LIFECYCLE_EVENTS):
        result.assertion(
            f"acp_{event.replace('.', '_')}_native_metric_present",
            event in acp_events,
        )
    result.artifact("acp-native-metrics", str(acp_native_path))
    result.artifact("acp-native-metrics-log", str(acp_native_log_path))
    result.artifact("monitoring-trace", str(trace_path))
    result.artifact("monitoring-trace-log", str(trace_log_path))
    result.publish("traceId", trace_id)
    return result.log(
        f"traceId={trace_id} expectedServices={sorted(expected_services)} "
        f"missing={json.dumps(missing_summary, sort_keys=True)}"
    )


if __name__ == "__main__":
    main()
