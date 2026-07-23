"""Default observability for generated hyper-experiments."""
from __future__ import annotations

import atexit
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from opentelemetry.context import attach, detach
from tracing_skill_observability import (
    ObservabilityHandle,
    configure_observability,
    current_trace_id,
    get_logger,
    get_meter,
    span,
)

TRACE_ARTIFACT_SCHEMA_VERSION = 1
TRACEPARENT_ENV = "TRACEPARENT"
TRACESTATE_ENV = "TRACESTATE"
TRACEPARENT_W3C_ENV = "traceparent"
TRACESTATE_W3C_ENV = "tracestate"
_ACTIVE: ExperimentObservability | None = None


@dataclass
class ExperimentObservability:
    """One generated experiment's shared trace, signals, and flush handle."""

    handle: ObservabilityHandle
    trace_id: str | None
    carrier: dict[str, str]
    trace_artifact: Path
    family: str
    variant: str
    _flush_result: bool | None = None
    _context_token: object | None = None

    @classmethod
    def configure(
        cls,
        config: Mapping[str, object],
        *,
        code_dir: Path,
    ) -> "ExperimentObservability":
        observability = dict(config.get("observability", {}))
        service_name = str(
            observability.get("service_name")
            or config.get("run_name")
            or config.get("experiment_id")
            or "hyper-experiment"
        )
        service_version = str(observability.get("service_version") or "0.1.0")
        paths = dict(config.get("paths", {}))
        trace_artifact = (
            code_dir
            / str(
                observability.get("trace_artifact")
                or paths.get("trace_artifact")
                or "../artifacts/trace.json"
            )
        ).resolve()
        handle = configure_observability(
            service_name=service_name,
            service_version=service_version,
            log_mode=str(observability.get("log_mode") or "otlp-only"),
        )
        inherited = _carrier_from_environment() or _carrier_from_artifact(
            trace_artifact
        )
        trace_id = None
        carrier: dict[str, str] = {}
        token = None
        try:
            token = attach(handle.extract(inherited))
            with span(
                "hyper_experiments.bootstrap",
                **{
                    "experiment.id": str(config.get("experiment_id") or "unknown"),
                    "experiment.family": str(config.get("family") or "unknown"),
                    "experiment.variant": str(config.get("variant") or "unknown"),
                },
            ):
                trace_id = current_trace_id()
                carrier = dict(handle.inject(dict(inherited)))
                meter = get_meter("hyper_experiments.generated", service_version)
                meter.create_counter(
                    "hyper_experiments.boundaries",
                    unit="{boundary}",
                    description="Bounded generated-experiment lifecycle events.",
                ).add(1, {"boundary": "bootstrap"})
                get_logger(__name__).info(
                    "hyper_experiments.observability.started",
                    extra={
                        "experiment_id": config.get("experiment_id"),
                        "family": config.get("family"),
                        "variant": config.get("variant"),
                    },
                )
        except Exception:
            get_logger(__name__).exception(
                "hyper_experiments.observability.bootstrap_failed"
            )
        finally:
            if token is not None:
                detach(token)

        instance = cls(
            handle=handle,
            trace_id=trace_id,
            carrier=carrier,
            trace_artifact=trace_artifact,
            family=str(config.get("family") or "unknown"),
            variant=str(config.get("variant") or "unknown"),
        )
        instance._persist_trace_artifact(service_name)
        instance._export_context_to_environment()
        instance._activate_carrier_context()
        return instance

    def record_iteration(self, *, stage: str) -> None:
        self._record_boundary("iteration", stage=stage)

    def record_evaluation(self, *, stage: str) -> None:
        self._record_boundary("evaluation", stage=stage)

    def subprocess_env(
        self,
        base: Mapping[str, str] | None = None,
        *,
        stage: str,
    ) -> dict[str, str]:
        self._record_boundary("subprocess", stage=stage)
        env = dict(base or os.environ)
        if traceparent := self.carrier.get("traceparent"):
            env[TRACEPARENT_ENV] = traceparent
            env[TRACEPARENT_W3C_ENV] = traceparent
        else:
            env.pop(TRACEPARENT_ENV, None)
            env.pop(TRACEPARENT_W3C_ENV, None)
        if tracestate := self.carrier.get("tracestate"):
            env[TRACESTATE_ENV] = tracestate
            env[TRACESTATE_W3C_ENV] = tracestate
        else:
            env.pop(TRACESTATE_ENV, None)
            env.pop(TRACESTATE_W3C_ENV, None)
        return env

    def flush(self, timeout_millis: int = 5_000) -> bool:
        if self._flush_result is not None:
            self._detach_carrier_context()
            return self._flush_result
        get_logger(__name__).info(
            "hyper_experiments.observability.flush_requested",
            extra={"trace_id": self.trace_id},
        )
        try:
            self._flush_result = self.handle.flush(timeout_millis=timeout_millis)
        except Exception:
            get_logger(__name__).exception(
                "hyper_experiments.observability.flush_failed",
                extra={"trace_id": self.trace_id},
            )
            self._flush_result = False
        finally:
            self._detach_carrier_context()
        return self._flush_result

    def _record_boundary(self, boundary: str, *, stage: str) -> None:
        token = None
        try:
            token = attach(self.handle.extract(self.carrier))
            with span(
                f"hyper_experiments.{boundary}",
                **{
                    "experiment.family": self.family,
                    "experiment.variant": self.variant,
                    "experiment.boundary.stage": stage,
                },
            ):
                get_meter("hyper_experiments.generated").create_counter(
                    f"hyper_experiments.{boundary}",
                    unit=f"{{{boundary}}}",
                    description=f"Generated experiment {boundary} boundaries.",
                ).add(1, {"stage": stage})
                get_logger(__name__).info(
                    f"hyper_experiments.{boundary}",
                    extra={"stage": stage, "trace_id": self.trace_id},
                )
        except Exception:
            get_logger(__name__).exception(
                "hyper_experiments.observability.boundary_failed",
                extra={"boundary": boundary, "stage": stage},
            )
        finally:
            if token is not None:
                detach(token)

    def _persist_trace_artifact(self, service_name: str) -> None:
        if self.trace_id is None:
            get_logger(__name__).warning(
                "hyper_experiments.trace_artifact.unavailable"
            )
            return
        payload = {
            "schema_version": TRACE_ARTIFACT_SCHEMA_VERSION,
            "service_name": service_name,
            "trace_id": self.trace_id,
            "traceparent": self.carrier.get("traceparent"),
        }
        if self.carrier.get("tracestate"):
            payload["tracestate"] = self.carrier["tracestate"]
        try:
            self.trace_artifact.parent.mkdir(parents=True, exist_ok=True)
            if self.trace_artifact.exists():
                existing = json.loads(self.trace_artifact.read_text())
                if existing.get("trace_id") == self.trace_id:
                    return
            temporary = self.trace_artifact.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            temporary.replace(self.trace_artifact)
        except (OSError, ValueError, TypeError):
            get_logger(__name__).exception(
                "hyper_experiments.trace_artifact.persist_failed",
                extra={"path": str(self.trace_artifact)},
            )

    def _export_context_to_environment(self) -> None:
        if traceparent := self.carrier.get("traceparent"):
            os.environ[TRACEPARENT_ENV] = traceparent
            os.environ[TRACEPARENT_W3C_ENV] = traceparent
        else:
            os.environ.pop(TRACEPARENT_ENV, None)
            os.environ.pop(TRACEPARENT_W3C_ENV, None)
        if tracestate := self.carrier.get("tracestate"):
            os.environ[TRACESTATE_ENV] = tracestate
            os.environ[TRACESTATE_W3C_ENV] = tracestate
        else:
            os.environ.pop(TRACESTATE_ENV, None)
            os.environ.pop(TRACESTATE_W3C_ENV, None)

    def _activate_carrier_context(self) -> None:
        """Keep W3C identity active without creating one long recording span."""

        if self._context_token is not None or not self.carrier:
            return
        try:
            self._context_token = attach(self.handle.extract(self.carrier))
        except Exception:
            get_logger(__name__).exception(
                "hyper_experiments.observability.context_activate_failed"
            )

    def _detach_carrier_context(self) -> None:
        token = self._context_token
        if token is None:
            return
        self._context_token = None
        try:
            detach(token)
        except Exception:
            get_logger(__name__).exception(
                "hyper_experiments.observability.context_detach_failed"
            )


def _carrier_from_environment() -> dict[str, str]:
    carrier = {}
    if traceparent := (
        os.environ.get(TRACEPARENT_W3C_ENV)
        or os.environ.get(TRACEPARENT_ENV)
    ):
        carrier["traceparent"] = traceparent
    if tracestate := (
        os.environ.get(TRACESTATE_W3C_ENV)
        or os.environ.get(TRACESTATE_ENV)
    ):
        carrier["tracestate"] = tracestate
    return carrier


def _carrier_from_artifact(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    carrier = {}
    if traceparent := payload.get("traceparent"):
        carrier["traceparent"] = str(traceparent)
    if tracestate := payload.get("tracestate"):
        carrier["tracestate"] = str(tracestate)
    return carrier


def configure_experiment_observability(
    config: Mapping[str, object],
    *,
    code_dir: Path,
) -> ExperimentObservability:
    """Configure one process-wide experiment handle and terminal flush."""

    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = ExperimentObservability.configure(config, code_dir=code_dir)
        timeout = int(
            dict(config.get("observability", {})).get(
                "flush_timeout_millis",
                5_000,
            )
        )
        atexit.register(_ACTIVE.flush, timeout_millis=timeout)
    return _ACTIVE
