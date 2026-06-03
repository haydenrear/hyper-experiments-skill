"""Entry point for {{experiment_id}} — {{title}} (agentic fitness variant).

Drives an OpenEvolve evolutionary search with agentic fitness reranking
for this experiment. The seed
program lives in `initial_program.py` (with EVOLVE-BLOCK markers around
the regions the LLM is allowed to mutate); the fitness function lives
in `evaluator.py` (`evaluate(program_path)` returning a metrics dict or
an `openevolve.evaluation_result.EvaluationResult`); the openevolve
configuration lives in `config.yaml`.

Run from the hyper-experiments project root:

    uv sync --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code
    uv run --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code run-openevolve

Or from inside this code directory:

    uv sync
    uv run run-openevolve

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

Local ACP service:

    The default `config.yaml` points at the ACP-backed
    OpenAI-compatible HTTP server provided by the
    `acp-cdc-ai-python` skill (a transitive skill_reference of
    hyper-experiments). When `config.yaml` points at localhost, this
    script starts one experiment-local ACP server, waits for it to
    become ready, overrides the loaded OpenEvolve config object with
    the auto-picked port, sends ACP JSONL traces to
    `data/acp-openai-server/jsonl/`, and stops the server when the
    OpenEvolve run exits.

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
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from python_exp import hello

CODE_DIR = Path(__file__).resolve().parent
RUN_CONFIG_PATH = CODE_DIR / "run_config.json"

# Default API base for the local OpenAI-compatible server. Used only as
# a heuristic to decide whether a missing `OPENAI_API_KEY` should be
# defaulted to a sentinel: when the configured api_base points at
# localhost the key is ignored by the server, so a missing key is a
# soft-default rather than an error. Real (paid) providers still
# require the user to export a real key.
LOCAL_API_BASE_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")

# Marker file the `acp-cdc-ai-python` skill's launcher drops under this
# experiment's root every time it starts. Lets us probe whether the
# server the default `config.yaml` expects is actually up without making
# a network call. The marker also carries the auto-picked port, so
# evolve experiments can run one ACP server per experiment without
# hard-coding port 8000 everywhere.
ACP_SERVER_INFO_FILENAME = ".acp-server/server.json"
EXPERIMENT_ROOT_MARKER = "index.md"
ACP_SERVER_READY_TIMEOUT_SECONDS = 180


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


def _find_experiment_root(start: Path) -> Path | None:
    """Walk up from `start` looking for this experiment's root."""
    for candidate in (start, *start.parents):
        if (candidate / EXPERIMENT_ROOT_MARKER).exists() and (candidate / "code") == CODE_DIR:
            return candidate
    return None


def _api_base_is_local(api_base: str | None) -> bool:
    if not api_base:
        return False
    return any(host in api_base for host in LOCAL_API_BASE_HOSTS)


def _acp_skill_home() -> Path:
    raw = os.environ.get("ACP_CDC_AI_PYTHON_SKILL_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    sm_home = Path(os.environ.get("SKILL_MANAGER_HOME", str(Path.home() / ".skill-manager")))
    return sm_home / "skills" / "acp-cdc-ai-python"


def _read_acp_server_info(experiment_root: Path) -> dict | None:
    info_path = experiment_root / ACP_SERVER_INFO_FILENAME
    if not info_path.exists():
        return None
    try:
        return json.loads(info_path.read_text())
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


def _wait_for_acp_server(experiment_root: Path, proc: subprocess.Popen) -> dict:
    deadline = time.time() + ACP_SERVER_READY_TIMEOUT_SECONDS
    last_info: dict | None = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"ACP server exited early with code {proc.returncode}")
        info = _read_acp_server_info(experiment_root)
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
                        return {"host": host, "port": port, "pid": pid}
            except (OSError, urllib.error.URLError):
                time.sleep(1)
                continue
        time.sleep(1)
    raise RuntimeError(f"ACP server did not become ready; last server info={last_info!r}")


def _start_acp_server(run_config: dict) -> tuple[subprocess.Popen, dict]:
    experiment_root = _find_experiment_root(CODE_DIR)
    if experiment_root is None:
        raise RuntimeError(f"could not locate this experiment's root from {CODE_DIR}")
    start_server = _acp_skill_home() / "scripts" / "start-server.py"
    if not start_server.exists():
        raise RuntimeError(
            f"missing acp-cdc-ai-python launcher at {start_server}; "
            "install the acp-cdc-ai-python skill or set ACP_CDC_AI_PYTHON_SKILL_HOME"
        )

    data_dir = _resolve(run_config["paths"]["data"])
    jsonl_dir = data_dir / "acp-openai-server" / "jsonl"
    process_dir = data_dir / "acp-openai-server" / "process"
    jsonl_dir.mkdir(parents=True, exist_ok=True)
    process_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = process_dir / "stdout.log"
    stderr_path = process_dir / "stderr.log"

    print(f"openevolve: starting ACP server with JSONL log dir={jsonl_dir}")
    with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
        proc = subprocess.Popen(
            [
                str(start_server),
                "--project-root",
                str(experiment_root),
                "--host",
                "127.0.0.1",
                "--log-dir",
                str(jsonl_dir),
            ],
            cwd=experiment_root,
            stdout=out,
            stderr=err,
            env=os.environ.copy(),
        )
    try:
        info = _wait_for_acp_server(experiment_root, proc)
    except RuntimeError as e:
        _stop_acp_server(proc, None)
        raise RuntimeError(
            f"{e}. See {stdout_path} and {stderr_path} for launcher output."
        ) from e
    print(
        f"openevolve: ACP server ready "
        f"(host={info['host']!r} port={info['port']!r} pid={info['pid']})."
    )
    return proc, {
        **info,
        "info_path": str(experiment_root / ACP_SERVER_INFO_FILENAME),
        "jsonl_dir": str(jsonl_dir),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _stop_acp_server(proc: subprocess.Popen | None, server_info: dict | None) -> None:
    if proc is None:
        return
    try:
        pid = int(server_info["pid"]) if server_info else proc.pid
    except (KeyError, TypeError, ValueError):
        pid = proc.pid
    if proc.poll() is None:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait(timeout=10)
    print(f"openevolve: stopped ACP server pid={pid}")


def _bind_local_api_base_to_acp_server(cfg, server_info: dict | None) -> str | None:
    """Use the experiment-local ACP server's actual host/port."""
    api_base = getattr(cfg.llm, "api_base", None)
    if server_info is None:
        return api_base
    api_base = f"http://{server_info['host']}:{server_info['port']}/v1"
    cfg.llm.api_base = api_base
    cfg.llm.update_model_params({"api_base": api_base}, overwrite=True)
    fitness = getattr(cfg, "fitness", None)
    agentic = getattr(fitness, "agentic", None) if fitness is not None else None
    if agentic is not None and getattr(agentic, "acp_cdc_ai_python", False):
        agentic.acp_cdc_ai_python_base_url = api_base
        experiment_root = _find_experiment_root(CODE_DIR)
        if experiment_root is not None and not agentic.acp_cdc_ai_python_cwd:
            agentic.acp_cdc_ai_python_cwd = str(experiment_root)
    print(f"openevolve: using experiment-local ACP api_base={api_base}")
    return api_base


def _configured_model_names(cfg) -> list[str]:
    names = []
    for model in getattr(cfg.llm, "models", []) or []:
        name = getattr(model, "name", None) or getattr(model, "model", None)
        if name is None and isinstance(model, dict):
            name = model.get("name") or model.get("model")
        if name is not None:
            names.append(str(name))
    return names


def _server_model_ids(api_base: str | None) -> list[str] | None:
    if not api_base:
        return None
    url = api_base.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"warning: could not query {url} for available models: {e}",
              file=sys.stderr)
        return None
    data = payload.get("data", []) if isinstance(payload, dict) else []
    ids = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


def _validate_configured_models(api_base: str | None, cfg) -> None:
    configured = _configured_model_names(cfg)
    print("openevolve: configured model priority:")
    for name in configured:
        print(f"  - {name}")

    available = _server_model_ids(api_base)
    if available is None:
        return
    print("openevolve: ACP/server available models:")
    for name in available:
        print(f"  - {name}")
    available_set = set(available)
    missing = [name for name in configured if name not in available_set]
    if missing:
        print(
            "error: config.yaml names model(s) the ACP/OpenAI-compatible "
            "server did not advertise:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print(
            "       Update code/config.yaml llm.models to one of the "
            "available model ids above. For Gemini through acp-cdc-ai-python, "
            "use the GEMINI_ prefix plus the Gemini CLI model name, e.g. "
            "GEMINI_gemini-2.5-flash.",
            file=sys.stderr,
        )
        raise SystemExit(1)


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


def _install_model_capacity_failover(run_config: dict) -> Path:
    """Install per-experiment model cooldown memory for OpenEvolve."""
    data_dir = _resolve(run_config["paths"]["data"])
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path = data_dir / "openevolve_model_capacity.json"

    import openevolve_capacity

    openevolve_capacity.install(state_path)
    print(f"openevolve: model capacity memory={state_path}")
    print(f"openevolve: model capacity events={state_path.with_name('openevolve_model_capacity_events.jsonl')}")
    return state_path


async def _run_evolution(run_config: dict) -> int:
    # Imported lazily so the smoke path doesn't pay the openevolve import
    # cost (and so a missing openevolve install only fails the real run).
    _install_model_capacity_failover(run_config)

    from openevolve import OpenEvolve
    from openevolve.config import load_config

    oe_cfg = run_config["openevolve"]
    config_path = _resolve(oe_cfg["config_file"])
    initial_path = _resolve(oe_cfg["initial_program"])
    evaluator_path = _resolve(oe_cfg["evaluator"])
    output_dir = _resolve(run_config["paths"]["openevolve_output"])
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(str(config_path))
    server_proc = None
    server_info = None
    try:
        api_base = getattr(cfg.llm, "api_base", None)
        if _api_base_is_local(api_base):
            server_proc, server_info = _start_acp_server(run_config)
        api_base = _bind_local_api_base_to_acp_server(cfg, server_info)
        _validate_configured_models(api_base, cfg)
        _ensure_api_key_for_local(api_base)
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
    finally:
        _stop_acp_server(server_proc, server_info)


def main() -> int:
    run_config = load_run_config()
    print(
        f"Run config: {run_config['run_name']} "
        f"(family={run_config['family']}, variant={run_config.get('variant')})"
    )
    print(hello())

    run_baselines(run_config)

    if os.environ.get("OPENEVOLVE_SMOKE"):
        return _smoke_check(run_config["openevolve"])

    return asyncio.run(_run_evolution(run_config))


if __name__ == "__main__":
    raise SystemExit(main())
