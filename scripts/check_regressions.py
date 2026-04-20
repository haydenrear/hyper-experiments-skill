#!/usr/bin/env python3
"""Run every experiment's `check-regressions` script against the CURRENT
`tools/python_exp/`, regardless of what that experiment has vendored.

This answers the question:

    "If I were to re-vendor every experiment against the current shared
    tools, which experiments would break?"

For each experiment with a `code/pyproject.toml`, this runner:

  1. runs `uv sync` inside the experiment's `code/` (respecting its
     current `[tool.uv.sources]`),
  2. force-installs the CURRENT `<root>/tools/python_exp/` over whatever
     `python-exp` was just installed — this temporarily overrides any
     vendored copy inside the venv,
  3. runs `uv run --no-sync check-regressions`, which invokes the
     experiment's own `check_regressions.py:main`,
  4. records PASS / FAIL / SYNC_FAIL / INSTALL_FAIL.

The experiment's tracked files are not modified — only the venv at
`code/.venv` is touched, and a subsequent `uv sync` inside the
experiment restores the frozen (vendored) state.

Usage:
    python scripts/check_regressions.py [--experiments-root PATH] [--verbose]

Exit codes:
    0 — all experiments passed
    1 — setup error (missing root, missing `uv`)
    3 — at least one experiment failed
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from _lib import find_experiments_root


def iter_experiments(root: Path):
    families = root / "experiments" / "families"
    if not families.exists():
        return
    for fam in sorted(families.iterdir()):
        if not fam.is_dir():
            continue
        for exp in sorted(fam.iterdir()):
            if not exp.is_dir():
                continue
            if not (exp / "code" / "pyproject.toml").exists():
                continue
            yield exp


def _run(cmd, cwd):
    return subprocess.run(
        cmd, cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )


def check_experiment(exp_dir: Path, root: Path, uv: str) -> tuple[str, str]:
    code_dir = exp_dir / "code"
    tools_python_exp = (root / "tools" / "python_exp").resolve()

    sync = _run([uv, "sync", "--quiet"], cwd=code_dir)
    if sync.returncode != 0:
        return "SYNC_FAIL", sync.stdout + sync.stderr

    override = _run(
        [uv, "pip", "install", "--quiet", "--force-reinstall",
         str(tools_python_exp)],
        cwd=code_dir,
    )
    if override.returncode != 0:
        return "INSTALL_FAIL", override.stdout + override.stderr

    run = _run(
        [uv, "run", "--no-sync", "check-regressions"],
        cwd=code_dir,
    )
    status = "PASS" if run.returncode == 0 else "FAIL"
    return status, run.stdout + run.stderr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--experiments-root", type=Path, default=None,
                    help="Project root (contains hyper-experiments.md). "
                         "Auto-detected from cwd if omitted.")
    ap.add_argument("--verbose", action="store_true",
                    help="Print output for every experiment, not just failures.")
    args = ap.parse_args()

    if args.experiments_root is not None:
        root = args.experiments_root.resolve()
        if not (root / "hyper-experiments.md").exists():
            print(f"error: {root} does not contain hyper-experiments.md",
                  file=sys.stderr)
            return 1
    else:
        root = find_experiments_root(Path.cwd())
        if root is None:
            print("error: could not find hyper-experiments.md by walking up from cwd.",
                  file=sys.stderr)
            return 1

    uv = shutil.which("uv")
    if uv is None:
        print("error: `uv` not found on PATH", file=sys.stderr)
        return 1

    tools_python_exp = root / "tools" / "python_exp"
    if not (tools_python_exp / "pyproject.toml").exists():
        print(f"error: {tools_python_exp} is not a uv/setuptools project",
              file=sys.stderr)
        return 1

    failures: list[tuple[Path, str, str]] = []
    total = 0
    for exp in iter_experiments(root):
        total += 1
        rel = exp.relative_to(root)
        status, output = check_experiment(exp, root, uv)
        label = "OK   " if status == "PASS" else f"{status:<5}"
        print(f"{label} {rel}")
        if status != "PASS":
            failures.append((rel, status, output))
        elif args.verbose and output.strip():
            print(output)

    print()
    print(f"Checked {total} experiment(s) — "
          f"{total - len(failures)} passed, {len(failures)} failed.")
    if failures:
        print()
        for rel, status, output in failures:
            print(f"=== {rel} [{status}] ===")
            print(output)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
