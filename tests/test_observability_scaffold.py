from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SHA = "618d33169d9aa3e168c60ab9100fb7efb24a13e6"
PROVIDER_PIN = (
    "tracing-skill-observability @ "
    "git+https://github.com/haydenrear/tracing_skill.git@"
    f"{PROVIDER_SHA}#subdirectory=sources/python"
)


class ObservabilityScaffoldTests(unittest.TestCase):
    def test_all_variants_generate_the_default_observability_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hx-observability-") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=project,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            env = {
                **os.environ,
                "HYPER_EXPERIMENTS_SKILL_HOME": str(ROOT),
                "PYTHONPYCACHEPREFIX": str(Path(tmp) / "pycache"),
            }
            init = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "init_project.py"),
                    "--root",
                    str(project),
                    "--project-name",
                    "observability contract",
                    "--description",
                    "generated contract regression",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stdout)

            shared_helper = (
                project
                / "tools"
                / "python_exp"
                / "src"
                / "python_exp"
                / "observability.py"
            )
            self.assertTrue(shared_helper.is_file())
            self.assertIn(
                PROVIDER_PIN,
                (project / "tools" / "python_exp" / "pyproject.toml").read_text(),
            )

            for variant in ("default", "evolve", "openevolve-agentic-fitness"):
                with self.subTest(variant=variant):
                    scaffold = subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "scripts" / "new_experiment.py"),
                            "--experiments-root",
                            str(project),
                            "--family",
                            variant.replace("-", "_"),
                            "--title",
                            f"{variant} observability",
                            "--type",
                            "root",
                            "--question",
                            "Does the scaffold install observability by default?",
                            "--delta",
                            "generated observability contract",
                            "--invariant",
                            "no user instrumentation",
                            "--command",
                            "uv run run-experiment",
                            "--variant",
                            variant,
                        ],
                        cwd=ROOT,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(scaffold.returncode, 0, scaffold.stdout)

                    family = project / "experiments" / "families" / variant.replace("-", "_")
                    experiment_dirs = sorted(family.glob("exp-*"))
                    self.assertEqual(len(experiment_dirs), 1)
                    code = experiment_dirs[0] / "code"
                    pyproject = (code / "pyproject.toml").read_text()
                    run_source = (code / "run_experiment.py").read_text()
                    regression_source = (code / "check_regressions.py").read_text()
                    run_config = json.loads((code / "run_config.json").read_text())

                    self.assertNotIn("tracing-skill-observability", pyproject)
                    self.assertEqual(
                        run_config["paths"]["trace_artifact"],
                        "../artifacts/trace.json",
                    )
                    self.assertEqual(
                        run_config["observability"]["log_mode"],
                        "otlp-only",
                    )
                    self.assertEqual(
                        run_config["observability"]["flush_timeout_millis"],
                        5_000,
                    )
                    self.assertIn("configure_experiment_observability", run_source)
                    self.assertIn("observability.flush(", run_source)
                    if variant == "default":
                        self.assertIn("log_dir=str(logdir)", run_source)
                        self.assertIn("writer.log_dir", run_source)
                        self.assertNotIn("writer.logdir", run_source)
                        self._run_generated_default_entrypoint(code)
                    self.assertIn(
                        "configure_experiment_observability",
                        regression_source,
                    )
                    self.assertNotIn("prometheus", run_source.lower())
                    self.assertNotIn("pushgateway", run_source.lower())

                    vendored_helper = (
                        code
                        / "vendored"
                        / "python_exp"
                        / "src"
                        / "python_exp"
                        / "observability.py"
                    )
                    self.assertTrue(vendored_helper.is_file())
                    self.assertIn(
                        PROVIDER_PIN,
                        (
                            code
                            / "vendored"
                            / "python_exp"
                            / "pyproject.toml"
                        ).read_text(),
                    )

                    if variant != "default":
                        evaluator = (code / "evaluator.py").read_text()
                        best_program = (code / "run_best_program.py").read_text()
                        self.assertIn("record_evaluation", evaluator)
                        self.assertIn("subprocess_env", run_source)
                        self.assertIn(
                            "configure_experiment_observability",
                            best_program,
                        )
                        self.assertIn("observability.flush(", best_program)
                        self.assertIn("stop-server.py", run_source)
                        self.assertNotIn("import signal", run_source)
                        self.assertNotIn("os.kill(pid, signal.", run_source)

    def _run_generated_default_entrypoint(self, code: Path) -> None:
        class FakeObservability:
            trace_id = "1234567890abcdef1234567890abcdef"
            trace_artifact = Path("/tmp/generated-trace.json")

            def record_iteration(self, *, stage: str) -> None:
                self.stage = stage

            def flush(self, timeout_millis: int = 5_000) -> bool:
                self.flush_timeout_millis = timeout_millis
                return True

        class FakeSummaryWriter:
            def __init__(
                self,
                *,
                log_dir: str,
                flush_secs: int,
                max_queue: int,
            ) -> None:
                self.log_dir = log_dir
                self.flush_secs = flush_secs
                self.max_queue = max_queue

            def add_scalar(self, *args, **kwargs) -> None:
                return None

            def close(self) -> None:
                return None

        python_exp = types.ModuleType("python_exp")
        python_exp.hello = lambda: "python_exp: test"
        python_exp_observability = types.ModuleType("python_exp.observability")
        python_exp_observability.configure_experiment_observability = (
            lambda config, code_dir: FakeObservability()
        )
        torch = types.ModuleType("torch")
        torch_utils = types.ModuleType("torch.utils")
        tensorboard = types.ModuleType("torch.utils.tensorboard")
        tensorboard.SummaryWriter = FakeSummaryWriter
        torch.utils = torch_utils
        torch_utils.tensorboard = tensorboard

        source = code / "run_experiment.py"
        spec = importlib.util.spec_from_file_location(
            "generated_default_entrypoint_test",
            source,
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules,
            {
                "python_exp": python_exp,
                "python_exp.observability": python_exp_observability,
                "torch": torch,
                "torch.utils": torch_utils,
                "torch.utils.tensorboard": tensorboard,
                spec.name: module,
            },
        ):
            spec.loader.exec_module(module)
            self.assertEqual(module.main(), 0)

    def test_shared_helper_emits_signals_propagates_and_flushes_once(self) -> None:
        events: list[tuple] = []
        trace_id = "1234567890abcdef1234567890abcdef"
        current_trace = [trace_id]
        fail_metrics = [False]

        class FakeHandle:
            flush_calls = 0

            def extract(self, carrier):
                events.append(("extract", dict(carrier)))
                return dict(carrier)

            def inject(self, carrier):
                carrier["traceparent"] = f"00-{trace_id}-0123456789abcdef-01"
                return carrier

            def flush(self, timeout_millis=5_000):
                self.flush_calls += 1
                events.append(("flush", timeout_millis))
                return True

        class FakeCounter:
            def add(self, amount, attributes):
                if fail_metrics[0]:
                    raise RuntimeError("metrics unavailable")
                events.append(("metric", amount, dict(attributes)))

        class FakeMeter:
            def create_counter(self, name, **kwargs):
                events.append(("counter", name))
                return FakeCounter()

        class FakeLogger:
            def info(self, name, extra=None):
                events.append(("log", name, dict(extra or {})))

            def exception(self, name, extra=None):
                events.append(("exception", name, dict(extra or {})))

            def warning(self, name, extra=None):
                events.append(("warning", name, dict(extra or {})))

        @contextmanager
        def fake_span(name, **attributes):
            events.append(("span", name, dict(attributes)))
            yield object()

        otel_context = types.ModuleType("opentelemetry.context")
        otel_context.attach = lambda context: ("token", context)
        otel_context.detach = lambda token: events.append(("detach", token))
        otel = types.ModuleType("opentelemetry")
        otel.context = otel_context

        provider = types.ModuleType("tracing_skill_observability")
        handle = FakeHandle()
        provider.ObservabilityHandle = FakeHandle

        def fake_configure_observability(**kwargs):
            events.append(("configure", dict(kwargs)))
            return handle

        provider.configure_observability = fake_configure_observability
        provider.current_trace_id = lambda: current_trace[0]
        provider.get_logger = lambda name=None: FakeLogger()
        provider.get_meter = lambda *args: FakeMeter()
        provider.span = fake_span

        helper_path = (
            ROOT
            / "references"
            / "templates"
            / "tools-python-exp-observability.py"
        )
        spec = importlib.util.spec_from_file_location(
            "generated_observability_test",
            helper_path,
        )
        module = importlib.util.module_from_spec(spec)

        with tempfile.TemporaryDirectory(prefix="hx-observability-runtime-") as tmp:
            code_dir = Path(tmp) / "code"
            code_dir.mkdir()
            config = {
                "experiment_id": "exp-0001",
                "family": "contract",
                "variant": "default",
                "run_name": "exp-0001-contract",
                "paths": {"trace_artifact": "../artifacts/trace.json"},
                "observability": {"flush_timeout_millis": 321},
            }
            with patch.dict(
                sys.modules,
                {
                    "opentelemetry": otel,
                    "opentelemetry.context": otel_context,
                    "tracing_skill_observability": provider,
                    spec.name: module,
                },
            ), patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                observability = module.configure_experiment_observability(
                    config,
                    code_dir=code_dir,
                )
                artifact = json.loads(observability.trace_artifact.read_text())
                original_artifact = observability.trace_artifact.read_text()

                self.assertEqual(artifact["trace_id"], trace_id)
                self.assertEqual(artifact["schema_version"], 1)
                self.assertEqual(os.environ["TRACEPARENT"], artifact["traceparent"])

                observability.record_iteration(stage="step")
                observability.record_evaluation(stage="full")
                child_env = observability.subprocess_env(
                    {"PATH": "/bin"},
                    stage="worker",
                )
                self.assertEqual(child_env["TRACEPARENT"], artifact["traceparent"])
                self.assertEqual(child_env["traceparent"], artifact["traceparent"])
                self.assertEqual(os.environ["traceparent"], artifact["traceparent"])
                self.assertEqual(
                    observability.trace_artifact.read_text(),
                    original_artifact,
                )
                self.assertTrue(observability.flush(timeout_millis=321))
                self.assertTrue(observability.flush(timeout_millis=999))

                fail_metrics[0] = True
                observability.record_iteration(stage="fail-open")
                fail_metrics[0] = False

                current_trace[0] = None
                unavailable = module.ExperimentObservability.configure(
                    config,
                    code_dir=code_dir,
                )
                self.assertIsNone(unavailable.trace_id)

        self.assertEqual(handle.flush_calls, 1)
        self.assertTrue(
            any(
                event[0] == "configure"
                and event[1]["log_mode"] == "otlp-only"
                for event in events
            )
        )
        self.assertTrue(any(event[:2] == ("span", "hyper_experiments.bootstrap") for event in events))
        self.assertTrue(any(event[0] == "metric" for event in events))
        self.assertTrue(any(event[0] == "log" for event in events))


if __name__ == "__main__":
    unittest.main()
