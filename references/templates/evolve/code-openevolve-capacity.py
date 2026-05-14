"""Model-capacity failover for this OpenEvolve experiment.

The ACP-backed OpenAI-compatible server can surface provider quota errors
like:

    You have exhausted your capacity on this model. Your quota will reset after 15h2m49s.
    You have exhausted your daily quota on this model.

OpenEvolve normally retries the same model and then fails the iteration.
This helper makes quota exhaustion fail fast for the current model,
records the model's cooldown in this experiment's data directory, and
tries the next configured model in priority order.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ENV_STATE_PATH = "OPENEVOLVE_MODEL_COOLDOWN_PATH"
ENV_EVENT_LOG_PATH = "OPENEVOLVE_MODEL_COOLDOWN_EVENT_LOG"
ENV_DEFAULT_COOLDOWN_SECONDS = "OPENEVOLVE_MODEL_COOLDOWN_DEFAULT_SECONDS"
ENV_ON_ALL_UNAVAILABLE = "OPENEVOLVE_MODEL_COOLDOWN_ON_ALL_UNAVAILABLE"
DEFAULT_COOLDOWN_SECONDS = 24 * 60 * 60
_CAPACITY_RE = re.compile(
    r"exhausted your (?:daily quota|capacity) on this model.*?quota will reset after\s+([0-9dhms\s]+)",
    re.IGNORECASE | re.DOTALL,
)
_CAPACITY_SIGNAL_RE = re.compile(
    r"exhausted your (?:daily quota|capacity) on this model",
    re.IGNORECASE | re.DOTALL,
)
_DURATION_PART_RE = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)


class _ModelCapacityExhausted(BaseException):
    """Internal signal that bypasses OpenAILLM's generic retry loop."""

    def __init__(self, model: str, resume_at: datetime, raw_error: str):
        super().__init__(raw_error)
        self.model = model
        self.resume_at = resume_at
        self.raw_error = raw_error


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _from_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_reset_after(raw_error: str) -> timedelta | None:
    match = _CAPACITY_RE.search(raw_error)
    if not match:
        return None
    total = 0
    for amount_s, unit in _DURATION_PART_RE.findall(match.group(1)):
        amount = int(amount_s)
        unit = unit.lower()
        if unit == "d":
            total += amount * 24 * 60 * 60
        elif unit == "h":
            total += amount * 60 * 60
        elif unit == "m":
            total += amount * 60
        elif unit == "s":
            total += amount
    if total <= 0:
        return None
    return timedelta(seconds=total)


def _is_capacity_error(raw_error: str) -> bool:
    return _CAPACITY_SIGNAL_RE.search(raw_error) is not None


def _default_cooldown() -> timedelta:
    raw = os.environ.get(ENV_DEFAULT_COOLDOWN_SECONDS, "").strip()
    if raw:
        try:
            seconds = int(raw)
            if seconds > 0:
                return timedelta(seconds=seconds)
        except ValueError:
            logger.warning(
                "%s=%r is not a positive integer; using %ss",
                ENV_DEFAULT_COOLDOWN_SECONDS,
                raw,
                DEFAULT_COOLDOWN_SECONDS,
            )
    return timedelta(seconds=DEFAULT_COOLDOWN_SECONDS)


def _model_name(model: Any) -> str:
    return str(getattr(model, "model", None) or getattr(model, "name", None) or model)


def _state_path() -> Path | None:
    raw = os.environ.get(ENV_STATE_PATH)
    return Path(raw).expanduser().resolve() if raw else None


def _event_log_path() -> Path | None:
    raw = os.environ.get(ENV_EVENT_LOG_PATH)
    return Path(raw).expanduser().resolve() if raw else None


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "models": {}}


def _read_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_state()
    except Exception as exc:
        logger.warning("Could not read model cooldown state %s: %s", path, exc)
        return _empty_state()
    if not isinstance(state, dict):
        return _empty_state()
    state.setdefault("version", 1)
    state.setdefault("models", {})
    if not isinstance(state["models"], dict):
        state["models"] = {}
    return state


def _atomic_write(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _with_lock(path: Path, fn: Callable[[dict[str, Any]], Any]) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        import fcntl
    except ImportError:
        state = _read_state(path)
        result = fn(state)
        _atomic_write(path, state)
        return result

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            state = _read_state(path)
            result = fn(state)
            _atomic_write(path, state)
            return result
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _append_event(event: dict[str, Any]) -> None:
    path = _event_log_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": _to_iso(_utc_now()), **event}
    line = json.dumps(payload, sort_keys=True) + "\n"
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        import fcntl
    except ImportError:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        return

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _cooldown_until(model_name: str) -> datetime | None:
    path = _state_path()
    if path is None:
        return None
    state = _read_state(path)
    entry = state.get("models", {}).get(model_name, {})
    resume_at = _from_iso(entry.get("resume_at"))
    if resume_at and resume_at > _utc_now():
        return resume_at
    return None


def _record_cooldown(model_name: str, resume_at: datetime, raw_error: str) -> None:
    path = _state_path()
    if path is None:
        return

    def update(state: dict[str, Any]) -> None:
        models = state.setdefault("models", {})
        models[model_name] = {
            "resume_at": _to_iso(resume_at),
            "updated_at": _to_iso(_utc_now()),
            "last_error": raw_error,
        }

    _with_lock(path, update)
    resume_at_iso = _to_iso(resume_at)
    logger.warning("Model %s capacity exhausted; cooling down until %s", model_name, resume_at_iso)
    _append_event(
        {
            "event": "capacity_exhausted",
            "model": model_name,
            "resume_at": resume_at_iso,
            "last_error": raw_error,
        }
    )


async def _priority_generate(ensemble: Any, call: Callable[[Any], Any]) -> str:
    if not getattr(ensemble, "models", None):
        raise RuntimeError("LLM ensemble has no models")

    while True:
        earliest_resume: datetime | None = None
        for model in ensemble.models:
            name = _model_name(model)
            resume_at = _cooldown_until(name)
            if resume_at is not None:
                resume_at_iso = _to_iso(resume_at)
                if earliest_resume is None or resume_at < earliest_resume:
                    earliest_resume = resume_at
                logger.info("Skipping model %s until %s", name, resume_at_iso)
                _append_event(
                    {"event": "model_skipped_cooling_down", "model": name, "resume_at": resume_at_iso}
                )
                continue

            logger.info("Trying model: %s", name)
            _append_event({"event": "model_try", "model": name})
            try:
                return await call(model)
            except _ModelCapacityExhausted as exc:
                _record_cooldown(exc.model, exc.resume_at, exc.raw_error)
                if earliest_resume is None or exc.resume_at < earliest_resume:
                    earliest_resume = exc.resume_at
                logger.warning("Trying next model after capacity exhaustion for %s", exc.model)
                continue

        if earliest_resume is None:
            raise RuntimeError("No LLM models were available to try")

        sleep_for = max(1.0, (earliest_resume - _utc_now()).total_seconds())
        on_all_unavailable = os.environ.get(ENV_ON_ALL_UNAVAILABLE, "").strip().lower()
        if on_all_unavailable == "raise":
            logger.warning(
                "All priority models are cooling down until %s; raising instead of sleeping",
                _to_iso(earliest_resume),
            )
        else:
            logger.warning(
                "All priority models are cooling down; sleeping %.1fs until %s",
                sleep_for,
                _to_iso(earliest_resume),
            )
        _append_event(
            {
                "event": "all_models_cooling_down",
                "mode": "raise" if on_all_unavailable == "raise" else "sleep",
                "sleep_seconds": sleep_for,
                "resume_at": _to_iso(earliest_resume),
            }
        )
        if on_all_unavailable == "raise":
            raise RuntimeError(
                "All priority models are cooling down until "
                f"{_to_iso(earliest_resume)}"
            )
        await asyncio.sleep(sleep_for)


def install(state_path: str | Path) -> None:
    """Install quota-aware model failover into OpenEvolve in this process."""
    path = Path(state_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ[ENV_STATE_PATH] = str(path)
    os.environ[ENV_EVENT_LOG_PATH] = str(path.with_name("openevolve_model_capacity_events.jsonl"))

    from openevolve.llm.ensemble import LLMEnsemble
    from openevolve.llm.openai import OpenAILLM
    import openevolve.process_parallel as process_parallel

    if not hasattr(OpenAILLM, "_hv_capacity_original_call_api"):
        OpenAILLM._hv_capacity_original_call_api = OpenAILLM._call_api

        async def _call_api_with_capacity(self, params: dict[str, Any]) -> str:
            try:
                return await OpenAILLM._hv_capacity_original_call_api(self, params)
            except Exception as exc:
                raw_error = str(exc)
                reset_after = _parse_reset_after(raw_error)
                if reset_after is None and _is_capacity_error(raw_error):
                    reset_after = _default_cooldown()
                if reset_after is not None:
                    raise _ModelCapacityExhausted(
                        _model_name(self), _utc_now() + reset_after, raw_error
                    ) from exc
                raise

        OpenAILLM._call_api = _call_api_with_capacity

    if not hasattr(LLMEnsemble, "_hv_capacity_original_generate_with_context"):
        LLMEnsemble._hv_capacity_original_generate = LLMEnsemble.generate
        LLMEnsemble._hv_capacity_original_generate_with_context = (
            LLMEnsemble.generate_with_context
        )

        async def _generate(self, prompt: str, **kwargs) -> str:
            return await _priority_generate(
                self, lambda model: model.generate(prompt, **kwargs)
            )

        async def _generate_with_context(self, system_message, messages, **kwargs) -> str:
            return await _priority_generate(
                self,
                lambda model: model.generate_with_context(system_message, messages, **kwargs),
            )

        LLMEnsemble.generate = _generate
        LLMEnsemble.generate_with_context = _generate_with_context

    current_worker_init = getattr(process_parallel, "_worker_init", None)
    if (
        current_worker_init is not worker_init
        and not hasattr(process_parallel, "_hv_capacity_original_worker_init")
    ):
        process_parallel._hv_capacity_original_worker_init = current_worker_init
        process_parallel._worker_init = worker_init

    logger.info("Installed OpenEvolve model-capacity failover at %s", path)


def worker_init(config_dict: dict, evaluation_file: str, parent_env: dict | None = None) -> None:
    """ProcessPool initializer that installs failover before worker LLMs exist."""
    if parent_env:
        os.environ.update(parent_env)

    path = os.environ.get(ENV_STATE_PATH)
    if path:
        install(path)

    import openevolve.process_parallel as process_parallel

    original = getattr(process_parallel, "_hv_capacity_original_worker_init", None)
    if original is None:
        raise RuntimeError("OpenEvolve worker initializer was not captured")
    original(config_dict, evaluation_file, parent_env)
