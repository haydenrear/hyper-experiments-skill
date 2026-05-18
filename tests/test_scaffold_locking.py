from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ScaffoldLockingTests(unittest.TestCase):
    def test_project_lock_cli_acquire_status_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hx-lock-cli-") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True)
            env = {**os.environ, "PYTHONPYCACHEPREFIX": str(Path(tmp) / "pycache")}

            acquire = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "project_lock.py"),
                    "acquire",
                    "--root",
                    str(project),
                    "--name",
                    "shared-ledger",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(acquire.returncode, 0, acquire.stdout)
            acquired = json.loads(acquire.stdout)
            token = acquired["metadata"]["token"]

            status = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "project_lock.py"),
                    "status",
                    "--root",
                    str(project),
                    "--name",
                    "shared-ledger",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stdout)
            observed = json.loads(status.stdout)
            self.assertTrue(observed["locked"])
            self.assertEqual(observed["metadata"]["token"], token)

            release = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "project_lock.py"),
                    "release",
                    "--root",
                    str(project),
                    "--name",
                    "shared-ledger",
                    "--token",
                    token,
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(release.returncode, 0, release.stdout)

            final_status = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "project_lock.py"),
                    "status",
                    "--root",
                    str(project),
                    "--name",
                    "shared-ledger",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(final_status.returncode, 0, final_status.stdout)
            self.assertFalse(json.loads(final_status.stdout)["locked"])

    def test_concurrent_new_experiment_allocates_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hx-locking-") as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            subprocess.run(["git", "init"], cwd=project, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True)
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
                    "lock test",
                    "--description",
                    "concurrency regression",
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stdout)

            procs = []
            for i in range(6):
                procs.append(subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "new_experiment.py"),
                        "--experiments-root",
                        str(project),
                        "--family",
                        "race",
                        "--title",
                        f"race child {i}",
                        "--type",
                        "root",
                        "--question",
                        "Does locking serialize ID allocation?",
                        "--delta",
                        "concurrency test",
                        "--invariant",
                        "same project root",
                        "--command",
                        "echo test",
                        "--lock-timeout",
                        "20",
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                ))

            outputs = []
            for proc in procs:
                out, _ = proc.communicate(timeout=30)
                outputs.append(out)
                self.assertEqual(proc.returncode, 0, out)

            exp_dirs = sorted(
                p.name
                for p in (project / "experiments" / "families" / "race").iterdir()
                if p.is_dir() and p.name.startswith("exp-")
            )
            self.assertEqual(len(exp_dirs), 6, "\n---\n".join(outputs))
            self.assertEqual(
                [name[:8] for name in exp_dirs],
                [f"exp-{i:04d}" for i in range(1, 7)],
            )


if __name__ == "__main__":
    unittest.main()
