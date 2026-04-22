#!/usr/bin/env python3
"""Disk usage report + pruning proposals for a hyper-experiments project.

Auto-detects the project root by walking up from cwd until it finds
`hyper-experiments.md`. Pass --experiments-root to override.

Reports:
- free / used / total on the filesystem hosting the project,
- per-experiment footprint (checkpoints/, tensorboard/, data/generated/),
- pruning candidates, tiered by chain-of-custody safety:
    * Tier 1 — planned experiments: safe, pre-launch;
    * Tier 2 — archived experiments: safe if truly cold-archived;
    * Tier 3 — running / stopped / completed: chain-of-custody waiver
      required, see `references/chain-of-custody.md` Rule 4.

Optional pre-launch gate:

    python scripts/check_disk.py --needed-gb 50

Exits 0 if free space is at least --needed-gb; exits 1 otherwise with a
shortfall message. The pre-launch workflow (SKILL.md > Standard workflow
step 8) treats a non-zero exit as a hard refusal to launch.

This script NEVER deletes anything. It prints paths and commands; the
operator runs them (or not) manually.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from _lib import find_experiments_root

STATUS_RE = re.compile(r"^[-*]\s*Status:\s*(\S+)", re.MULTILINE)
EXP_NAME_RE = re.compile(r"^exp-\d{4}")


def du_tree(path: Path) -> int:
    """Sum sizes of all regular files under `path` (follows no symlinks)."""
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def fmt_bytes(n: int) -> str:
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if x < 1024 or unit == "TiB":
            return f"{x:.1f} {unit}" if unit != "B" else f"{int(x)} B"
        x /= 1024
    return f"{x:.1f} TiB"


def read_status(exp_dir: Path) -> str:
    idx = exp_dir / "index.md"
    if not idx.exists():
        return "unknown"
    m = STATUS_RE.search(idx.read_text())
    return m.group(1) if m else "unknown"


def collect_experiments(root: Path):
    families = root / "experiments" / "families"
    if not families.exists():
        return []
    out = []
    for fam in sorted(families.iterdir()):
        if not fam.is_dir():
            continue
        for exp in sorted(fam.iterdir()):
            if not exp.is_dir() or not EXP_NAME_RE.match(exp.name):
                continue
            ckpt = du_tree(exp / "checkpoints")
            tb = du_tree(exp / "tensorboard")
            gen = du_tree(exp / "data" / "generated")
            out.append({
                "rel": str(exp.relative_to(root)),
                "status": read_status(exp),
                "checkpoints": ckpt,
                "tensorboard": tb,
                "generated": gen,
                "total": ckpt + tb + gen,
            })
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


def print_disk_summary(root: Path):
    total, used, free = shutil.disk_usage(root)
    used_pct = 100.0 * used / total if total else 0.0
    print(f"Disk for {root}:")
    print(f"  Total: {fmt_bytes(total)}")
    print(f"  Used : {fmt_bytes(used)}  ({used_pct:.1f}%)")
    print(f"  Free : {fmt_bytes(free)}")
    print()
    return free


def print_top(exps, n):
    print(f"Top {min(n, len(exps))} experiments by footprint:")
    print(f"  {'Rank':<5} {'Total':>10}  {'Status':<11} Experiment")
    for i, e in enumerate(exps[:n], 1):
        print(f"  {i:<5} {fmt_bytes(e['total']):>10}  {e['status']:<11} {e['rel']}")
    print()


def print_breakdown(exps, n):
    print(f"Breakdown (top {min(n, len(exps))}):")
    for e in exps[:n]:
        print(f"  {e['rel']}  [{e['status']}]  total {fmt_bytes(e['total'])}")
        print(f"    checkpoints/    {fmt_bytes(e['checkpoints']):>10}")
        print(f"    tensorboard/    {fmt_bytes(e['tensorboard']):>10}")
        print(f"    data/generated/ {fmt_bytes(e['generated']):>10}")
    print()


def print_prune_candidates(exps, tier_limit):
    tier1 = [e for e in exps if e["status"] == "planned" and e["total"] > 0]
    tier2 = [e for e in exps if e["status"] == "archived" and e["checkpoints"] > 0]
    tier3 = [
        e for e in exps
        if e["status"] in ("completed", "running", "stopped")
        and e["checkpoints"] > 0
    ]

    print("Pruning candidates:")
    print()
    print("  Tier 1 — safe (experiment has not launched yet):")
    if tier1:
        for e in tier1:
            print(f"    {e['rel']}  total {fmt_bytes(e['total'])}")
            print(f"      -> rm -rf {e['rel']}/checkpoints/* "
                  f"{e['rel']}/tensorboard/* {e['rel']}/data/generated/*")
    else:
        print("    <none>")
    print()
    print("  Tier 2 — safe if this experiment is truly cold-archived:")
    if tier2:
        for e in tier2:
            print(f"    {e['rel']}  checkpoints {fmt_bytes(e['checkpoints'])}")
            print(f"      -> move to cold storage, not delete; record the")
            print(f"         move under a Cold Storage block in "
                  f"{e['rel']}/run.md")
    else:
        print("    <none>")
    print()
    print("  Tier 3 — chain-of-custody waiver required:")
    print("    Pruning checkpoints from running / stopped / completed")
    print("    experiments violates chain-of-custody Rule 4. Only do this")
    print("    if you are willing to document the deviation in run.md and")
    print("    accept that re-running the experiment may no longer be fully")
    print("    reproducible. Prefer Tier 1 / Tier 2 first.")
    if tier3:
        for e in tier3[:tier_limit]:
            print(f"    {e['rel']}  [{e['status']}]  "
                  f"checkpoints {fmt_bytes(e['checkpoints'])}")
        if len(tier3) > tier_limit:
            print(f"    ... and {len(tier3) - tier_limit} more")
    else:
        print("    <none>")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--experiments-root", type=Path, default=None,
                    help="Project root (contains hyper-experiments.md). "
                         "Auto-detected from cwd if omitted.")
    ap.add_argument("--needed-gb", type=float, default=None,
                    help="If set, exit non-zero when free < N GiB. "
                         "Use as a pre-launch gate.")
    ap.add_argument("--top", type=int, default=10,
                    help="Number of experiments in the top-N list "
                         "and per-tier listings. Default: 10.")
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
            print("error: could not find hyper-experiments.md by walking up "
                  "from cwd.", file=sys.stderr)
            return 1

    free = print_disk_summary(root)

    exps = collect_experiments(root)
    if exps:
        print_top(exps, args.top)
        print_breakdown(exps, args.top)
        print_prune_candidates(exps, args.top)
    else:
        print("No experiments found under experiments/families/.")
        print()

    if args.needed_gb is not None:
        needed_b = int(args.needed_gb * (1024 ** 3))
        if free < needed_b:
            shortfall = needed_b - free
            print(f"error: need {args.needed_gb} GiB free; "
                  f"have {fmt_bytes(free)}", file=sys.stderr)
            print(f"       shortfall: {fmt_bytes(shortfall)}", file=sys.stderr)
            print(f"       Consider pruning Tier 1 / Tier 2 candidates above "
                  f"before launch.", file=sys.stderr)
            return 1
        print(f"OK: {args.needed_gb} GiB requested, {fmt_bytes(free)} "
              f"available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
