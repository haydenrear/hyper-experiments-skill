"""Shared helpers for hyper-experiments scaffolding scripts."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "references" / "templates"
ROOT_MARKER = "hyper-experiments.md"
EXP_ID_RE = re.compile(r"^exp-(\d{4})")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "untitled"


def bullet_list(items):
    items = [i for i in (items or []) if i]
    return "\n".join(f"- {it}" for it in items)


def load_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text()


def render_template(template: str, vars: dict) -> str:
    def sub(match):
        key = match.group(1).strip()
        if key in vars:
            return str(vars[key])
        return match.group(0)
    return re.sub(r"\{\{([^}]+)\}\}", sub, template)


def find_experiments_root(start: Path):
    """Walk up from `start` looking for a directory containing hyper-experiments.md."""
    p = start.resolve()
    while True:
        if (p / ROOT_MARKER).exists():
            return p
        if p.parent == p:
            return None
        p = p.parent


def allocate_experiment_id(root: Path) -> str:
    """Scan existing experiment dirs under all families and return next exp-NNNN."""
    families = root / "experiments" / "families"
    max_n = 0
    if families.exists():
        for fam in families.iterdir():
            if not fam.is_dir():
                continue
            for exp in fam.iterdir():
                if not exp.is_dir():
                    continue
                m = EXP_ID_RE.match(exp.name)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    return f"exp-{max_n + 1:04d}"


def find_experiment_dir(root: Path, exp_id: str):
    """Return the directory for exp_id under any family, or None."""
    families = root / "experiments" / "families"
    if not families.exists():
        return None
    matches = list(families.glob(f"*/{exp_id}-*"))
    return matches[0] if matches else None
