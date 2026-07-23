from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
GRAPH_ROOT = ROOT / "test_graph"
READY_NODE = "monitoring.cluster.assert.ready"
DEPLOY_CDC_PIN = "5a5a7e67422644d845d3afbeb78b99892963a658"


def _load_monitoring_support():
    spec = importlib.util.spec_from_file_location(
        "monitoring_ready_support_test",
        GRAPH_ROOT / "support" / "monitoring_ready_support.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Hyper monitoring readiness support")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Context:
    def __init__(self, envelope: dict | None):
        self.envelope = envelope

    def upstream(self, node_id: str):
        if node_id != READY_NODE:
            raise AssertionError(f"unexpected upstream node: {node_id}")
        return self.envelope


class MonitoringPrerequisiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.monitoring_support = _load_monitoring_support()

    def test_graph_composes_provider_readiness_before_all_consumers(self) -> None:
        build = (GRAPH_ROOT / "build.gradle.kts").read_text()
        self.assertIn(f'standardNode("{READY_NODE}")', build)

        consumers = (
            (
                "hyper_default_short_run.py",
                f'.depends_on("{READY_NODE}")',
            ),
            (
                "openevolve_claude_sonnet_short_run.py",
                f'.depends_on("{READY_NODE}")',
            ),
            (
                "agentic_claude_sonnet_short_run.py",
                f'.depends_on("{READY_NODE}")',
            ),
            (
                "hyper_observability_evidence.py",
                ".depends_on(MONITORING_READY_NODE)",
            ),
        )
        for filename, dependency in consumers:
            with self.subTest(filename=filename):
                source = (GRAPH_ROOT / "sources" / filename).read_text()
                self.assertIn(dependency, source)

    def test_provider_catalog_link_and_deploy_cdc_pin_are_exact(self) -> None:
        catalog = GRAPH_ROOT / "standard-nodes"
        self.assertTrue(catalog.is_symlink())
        self.assertEqual(
            os.readlink(catalog),
            "../../test_graph/project_sdk_sources/standard-nodes",
        )
        self.assertEqual(
            catalog.resolve(),
            (ROOT.parent / "test_graph/project_sdk_sources/standard-nodes").resolve(),
        )

        manifest = (ROOT / "skill-manager.toml").read_text()
        self.assertIn(f"github:haydenrear/deploy-cdc#{DEPLOY_CDC_PIN}", manifest)

    def test_monitoring_launcher_comes_from_successful_readiness_envelope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hx-monitoring-cli-") as tmp:
            launcher = Path(tmp) / "monitoring"
            launcher.write_text("#!/bin/sh\nexit 0\n")
            launcher.chmod(0o755)
            envelope = {
                "nodeId": READY_NODE,
                "status": "passed",
                "processes": [
                    {
                        "label": "status",
                        "command": [
                            str(launcher),
                            "status",
                            "--json",
                            "--require-ready",
                        ],
                        "exitCode": 0,
                        "error": None,
                    }
                ],
            }
            with mock.patch.dict(os.environ, {"PATH": ""}):
                observed = self.monitoring_support.monitoring_cli_from_readiness(
                    _Context(envelope)
                )
            self.assertEqual(observed, str(launcher))

            envelope["processes"][0]["command"] = [str(launcher), "status"]
            with self.assertRaisesRegex(RuntimeError, "unexpected command"):
                self.monitoring_support.monitoring_cli_from_readiness(
                    _Context(envelope)
                )


if __name__ == "__main__":
    unittest.main()
