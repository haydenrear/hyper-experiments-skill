"""Shared helpers for hyper-experiments scaffolding scripts."""
from __future__ import annotations

import copy
import json
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


_PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")


def _has_placeholder(v):
    return isinstance(v, str) and _PLACEHOLDER_RE.search(v) is not None


def _render_placeholder_str(s: str, vars_: dict) -> str:
    def sub(m):
        key = m.group(1).strip()
        return str(vars_.get(key, m.group(0)))
    return _PLACEHOLDER_RE.sub(sub, s)


def _merge(template, parent, child_vars, path, changes):
    """Produce the merged value at `path`.

    - If `template` is a dict: union of keys (template-driven paths take
      priority; parent-only keys are inherited verbatim).
    - If `template` is a list: recurse positionally over the parent's items
      (so the child's list is the same length as the parent's).
    - If `template` is a string containing a `{{placeholder}}`: render it for
      the child; record a rename when the parent had a different value.
    - Otherwise: inherit the parent's value if present; else fall through to
      the template default.
    """
    if isinstance(template, dict):
        parent_dict = parent if isinstance(parent, dict) else {}
        result = {}
        for k in template:
            sub_path = f"{path}.{k}" if path else k
            result[k] = _merge(template[k], parent_dict.get(k), child_vars, sub_path, changes)
        for k in parent_dict:
            if k not in template:
                result[k] = copy.deepcopy(parent_dict[k])
        return result

    if isinstance(template, list):
        parent_list = parent if isinstance(parent, list) else None
        if parent_list is None:
            return [
                _merge(item, None, child_vars, f"{path}[{i}]", changes)
                for i, item in enumerate(template)
            ]
        result = []
        for i, p_item in enumerate(parent_list):
            sub_path = f"{path}[{i}]"
            t_item = template[i] if i < len(template) else None
            if t_item is None:
                result.append(copy.deepcopy(p_item))
            else:
                result.append(_merge(t_item, p_item, child_vars, sub_path, changes))
        return result

    if _has_placeholder(template):
        rendered = _render_placeholder_str(template, child_vars)
        if parent is not None and parent != rendered:
            changes.append((path, parent, rendered))
        return rendered

    if parent is not None:
        return copy.deepcopy(parent)
    return copy.deepcopy(template)


EXP_ID_PREFIX_RE = re.compile(r"^exp-\d{4}-")


def parent_slug_from_dir(parent_dir_name: str):
    """Extract the slug from a parent experiment directory name like
    `exp-0036-polynomial-grpo-overfit-shakedown` → `polynomial-grpo-overfit-shakedown`.
    Returns None if the name does not match the canonical pattern."""
    m = re.match(r"^exp-\d{4}-(.*)$", parent_dir_name)
    return m.group(1) if m else None


# JSON keys whose values identify the experiment and must be rewritten
# when branching/copying. Values are functions that compute the new value
# from (old_value, child_vars, parent_identity). `parent_identity` is the
# tuple (parent_exp_id, parent_slug) so identity-bearing strings like
# `run_name = "exp-0036-some-slug"` can be retargeted even when the
# parent stamped the literal value rather than a placeholder.
def _rewrite_exp_id(_old, child_vars, _parent):
    return child_vars["experiment_id"]


def _rewrite_slug(_old, child_vars, _parent):
    return child_vars["slug"]


def _rewrite_run_name(old, child_vars, parent):
    new_prefix = f"{child_vars['experiment_id']}-{child_vars['slug']}"
    if not isinstance(old, str):
        return new_prefix
    parent_exp_id, parent_slug = parent
    parent_prefix = f"{parent_exp_id}-{parent_slug}" if parent_slug else parent_exp_id
    if parent_prefix and old.startswith(parent_prefix):
        return new_prefix + old[len(parent_prefix):]
    return new_prefix


_IDENTITY_REWRITES = {
    "experiment_id": _rewrite_exp_id,
    "slug": _rewrite_slug,
    "run_name": _rewrite_run_name,
}


def sweep_identity_in_json(
    json_path: Path,
    child_vars: dict,
    parent_identity: tuple,
):
    """Walk a JSON tree and rewrite identity-bearing values whose KEY is in
    `_IDENTITY_REWRITES` (`experiment_id`, `slug`, `run_name`). Returns a list
    of (dotted_path, old, new) for every rewrite that changed a value. Writes
    the file back only if at least one change occurred.

    `parent_identity` is `(parent_exp_id, parent_slug)`. `parent_slug` may be
    `None` if the parent dir name did not match the canonical pattern; in
    that case `run_name` retargeting falls back to a full overwrite.
    """
    obj = json.loads(json_path.read_text())
    changes: list = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in list(node.items()):
                p = f"{path}.{k}" if path else k
                fn = _IDENTITY_REWRITES.get(k)
                if fn is not None and isinstance(v, (str, int, float, bool)):
                    new = fn(v, child_vars, parent_identity)
                    if new != v:
                        changes.append((p, v, new))
                        node[k] = new
                else:
                    walk(v, p)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(obj, "")
    if changes:
        json_path.write_text(json.dumps(obj, indent=2) + "\n")
    return changes


def inherit_run_config(template_obj, parent_config, child_vars):
    """Produce a child `run_config.json` from the template and (optionally) the
    parent's config.

    The template carries `{{placeholder}}` strings at every slot that identifies
    the experiment (ids, names, tags). At every such slot the child's rendered
    value wins, overriding whatever the parent had. Everywhere else the
    parent's value is inherited verbatim. Keys present only in the parent are
    kept; keys present only in the template are added (rendered).

    Returns (merged_config, changes) where `changes` is a list of
    (dotted_path, old_value, new_value) tuples for every placeholder-driven
    rewrite of a parent value.
    """
    changes: list = []
    if parent_config is None:
        return _merge(template_obj, None, child_vars, "", changes), changes
    merged = _merge(template_obj, parent_config, child_vars, "", changes)
    return merged, changes
