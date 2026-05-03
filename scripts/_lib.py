"""Shared helpers for hyper-experiments scaffolding scripts."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
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


def _rewrite_parent_experiment(_old, child_vars, _parent):
    return child_vars.get("parent_experiment", _old)


def _rewrite_parent_checkpoint(_old, child_vars, _parent):
    # `parent_checkpoint` defaults to the literal string "null" when no
    # --checkpoint was passed. That is intentional: an inherited parent's
    # parent_checkpoint is wrong for the child by definition, and "null"
    # is the canonical "none specified" marker used elsewhere in the
    # skill (index.md, plan.md). The operator overrides to a real path
    # via the audit block when a checkpoint resume is meant.
    return child_vars.get("parent_checkpoint", _old)


_IDENTITY_REWRITES = {
    "experiment_id": _rewrite_exp_id,
    "slug": _rewrite_slug,
    "run_name": _rewrite_run_name,
    "parent_experiment": _rewrite_parent_experiment,
    "parent_checkpoint": _rewrite_parent_checkpoint,
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


def _enumerate_leaf_paths(obj, prefix=""):
    """Yield (dotted_path, value) for every leaf in a JSON tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _enumerate_leaf_paths(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _enumerate_leaf_paths(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def enumerate_inherited_leaves(json_path: Path, rewritten_paths):
    """List every (dotted_path, value) leaf in `json_path` whose path is not
    in `rewritten_paths`. This is the audit list of fields the child inherited
    verbatim from the parent — the next agent must decide keep/override/delete
    for each one (see SKILL.md > 'Inherited config audit')."""
    obj = json.loads(json_path.read_text())
    skip = set(rewritten_paths or ())
    return [(p, v) for p, v in _enumerate_leaf_paths(obj) if p not in skip]


def sweep_parent_identity_references(
    json_path: Path,
    parent_identity: tuple,
    child_identity: tuple,
    skip_paths=None,
):
    """Find string values containing the parent's identity prefix that were
    not auto-rewritten. Returns (dotted_path, value, suggested_rewrite, kind)
    tuples; does NOT modify the file.

    `kind` is one of:
      - "exact"  — value is exactly the parent prefix (e.g. "exp-0036-foo");
                   suggested rewrite swaps in the child prefix.
      - "embedded-with-slug"
                 — value contains "exp-NNNN-slug" as a substring; rewrite
                   swaps that occurrence only.
      - "embedded-bare"
                 — value contains "exp-NNNN" but not "-slug"; this is more
                   likely a deliberate reference (parent checkpoint path,
                   ancestor mention) than a leaked identity. Reported but
                   suggested_rewrite is None — let the operator decide.

    The caller is expected to surface every result for review; nothing here
    is auto-applied. Identity rewrites at known keys are still handled by
    `sweep_identity_in_json` — this sweep catches the rest.
    """
    parent_exp_id, parent_slug = parent_identity
    child_exp_id, child_slug = child_identity
    skip = set(skip_paths or ())

    parent_prefix_with_slug = (
        f"{parent_exp_id}-{parent_slug}" if parent_slug else None
    )
    child_prefix_with_slug = f"{child_exp_id}-{child_slug}"

    # Match parent's "exp-NNNN-slug" first (more specific), fall back to
    # bare "exp-NNNN" (the parent_exp_id literal). Anchored to word
    # boundaries so we don't false-match inside another id.
    bare_re = re.compile(rf"\b{re.escape(parent_exp_id)}\b")

    obj = json.loads(json_path.read_text())
    findings = []

    def visit(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                visit(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, f"{path}[{i}]")
        elif isinstance(node, str):
            if path in skip:
                return
            # Most specific first.
            if parent_prefix_with_slug and parent_prefix_with_slug in node:
                if node == parent_prefix_with_slug:
                    findings.append((
                        path, node, child_prefix_with_slug, "exact",
                    ))
                else:
                    suggested = node.replace(
                        parent_prefix_with_slug, child_prefix_with_slug,
                    )
                    findings.append((
                        path, node, suggested, "embedded-with-slug",
                    ))
                return
            if bare_re.search(node):
                findings.append((path, node, None, "embedded-bare"))

    visit(obj, "")
    return findings


# --- python_exp vendoring ----------------------------------------------------
#
# Every experiment carries its own frozen copy of the shared `python_exp`
# library at `code/vendored/python_exp/`. The two scaffolding scripts vendor
# automatically:
#   - new_experiment.py vendors from `<root>/tools/python_exp/`
#   - branch_experiment.py inherits the parent's vendored copy (already
#     deep-copied as part of `code/`); these helpers verify / repair the
#     child's pyproject.toml so it still points at `./vendored/python_exp`.
#
# The match is scoped to the [tool.uv.sources] python-exp line; everything
# else in pyproject.toml is left alone. Each helper returns a provenance
# dict so the caller (and any LLM reading stdout) can verify the rewrite
# touched exactly what was intended.

PYTHON_EXP_SOURCE_RE = re.compile(
    r'^(?P<line>python-exp\s*=\s*\{[^}\n]*\})\s*$',
    re.MULTILINE,
)
VENDORED_PYTHON_EXP_LINE = 'python-exp = { path = "./vendored/python_exp" }'


def _git_sha(path: Path):
    """Best-effort `git rev-parse HEAD` for the dir's repo. Returns None if
    not under git or git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _rewrite_python_exp_source(pyproject: Path) -> dict:
    """Rewrite the [tool.uv.sources] python-exp line to point at the local
    vendored copy. Returns a dict describing the change. Raises if the
    line is not found exactly once.
    """
    text = pyproject.read_text()
    matches = list(PYTHON_EXP_SOURCE_RE.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one python-exp line in {pyproject}; "
            f"found {len(matches)}. refusing to rewrite to avoid clobbering."
        )
    m = matches[0]
    old_line = m.group("line")
    new_line = VENDORED_PYTHON_EXP_LINE
    line_no = _lineno(text, m.start())
    if old_line == new_line:
        return {
            "file": str(pyproject),
            "line_no": line_no,
            "old": old_line,
            "new": new_line,
            "changed": False,
        }
    new_text = text[: m.start("line")] + new_line + text[m.end("line") :]
    pyproject.write_text(new_text)
    return {
        "file": str(pyproject),
        "line_no": line_no,
        "old": old_line,
        "new": new_line,
        "changed": True,
    }


def vendor_python_exp_from_tools(
    tools_python_exp: Path,
    code_dir: Path,
) -> dict:
    """Vendor `tools_python_exp` into `code_dir/vendored/python_exp/` and
    rewrite the experiment's pyproject.toml [tool.uv.sources] python-exp
    line to point at the local copy (non-editable).

    Returns a provenance dict so the caller can verify nothing was
    clobbered:

        {
          "vendored_from": "<abs path>",
          "vendored_from_sha": "<git sha or None>",
          "vendored_to": "<abs path>",
          "pyproject": {
            "file": "<abs path>",
            "line_no": <int>,
            "old": "<original line>",
            "new": "<rewritten line>",
            "changed": True,
          },
        }
    """
    if not tools_python_exp.exists():
        raise FileNotFoundError(
            f"shared python_exp not found at {tools_python_exp}"
        )
    pyproject = code_dir / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")

    dest = code_dir / "vendored" / "python_exp"
    if dest.exists():
        raise FileExistsError(
            f"refusing to overwrite existing {dest}; "
            f"vendoring should run on a fresh scaffold"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tools_python_exp, dest)

    return {
        "vendored_from": str(tools_python_exp),
        "vendored_from_sha": _git_sha(tools_python_exp),
        "vendored_to": str(dest),
        "pyproject": _rewrite_python_exp_source(pyproject),
    }


def verify_or_fix_branched_python_exp(
    parent_code_dir: Path,
    child_code_dir: Path,
) -> dict:
    """Verify that branching produced a child whose vendored python_exp came
    from the parent's vendored copy, and that the child's pyproject still
    points at `./vendored/python_exp`. Repairs the pyproject line via
    regex if it drifted (e.g. parent had an editable link).

    Returns a provenance dict:

        {
          "inherited_from": "<parent vendored abs path>",
          "vendored_to":    "<child vendored abs path>",
          "pyproject":      {... same shape as in vendor_python_exp_from_tools ...},
          "status":         "ok" | "parent-had-no-vendored-copy",
        }

    Refuses (raises) if the parent had no vendored copy — operator must
    repair the parent's chain of custody first or scaffold the child via
    `new_experiment.py` to vendor from `tools/python_exp/` instead.
    """
    parent_vendored = parent_code_dir / "vendored" / "python_exp"
    child_vendored = child_code_dir / "vendored" / "python_exp"
    pyproject = child_code_dir / "pyproject.toml"

    if not parent_vendored.exists():
        raise FileNotFoundError(
            f"parent has no vendored python_exp at {parent_vendored}; "
            f"branching cannot inherit a frozen library. "
            f"vendor the parent first, or use new_experiment.py to scaffold "
            f"a fresh experiment that vendors from tools/python_exp/."
        )
    if not child_vendored.exists():
        raise RuntimeError(
            f"branch did not produce {child_vendored}; "
            f"check that parent's code/vendored/ was deep-copied."
        )
    if not pyproject.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")

    return {
        "inherited_from": str(parent_vendored),
        "vendored_to": str(child_vendored),
        "pyproject": _rewrite_python_exp_source(pyproject),
        "status": "ok",
    }


def print_vendoring_provenance(prov: dict, *, source_kind: str) -> None:
    """Pretty-print a vendoring provenance dict to stdout. `source_kind` is
    "tools" (new_experiment) or "parent" (branch_experiment)."""
    print(f"Vendoring provenance ({source_kind}):")
    if source_kind == "tools":
        print(f"  vendored python_exp from: {prov['vendored_from']}"
              + (f" @ {prov['vendored_from_sha']}" if prov['vendored_from_sha'] else ""))
        print(f"  vendored python_exp to:   {prov['vendored_to']}")
    else:
        print(f"  inherited from parent:    {prov['inherited_from']}")
        print(f"  vendored to:              {prov['vendored_to']}")
    py = prov["pyproject"]
    print(f"  pyproject.toml:           {py['file']}:line {py['line_no']}")
    if py["changed"]:
        print(f"    old: {py['old']}")
        print(f"    new: {py['new']}")
    else:
        print(f"    line unchanged: {py['new']}")


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


# Smoke-test artifact cleanup. Running `uv sync && uv run run-experiment`
# leaves four kinds of bytes behind that must not enter the freeze commit:
#
#   - <exp>/code/.venv             (per-experiment virtualenv)
#   - <exp>/code/**/__pycache__    (bytecode caches)
#   - <exp>/tensorboard/*          (heartbeat event file from the scaffold)
#   - <exp>/logs/*                 (anything the scaffold logged)
#
# We wipe directory *contents* for tensorboard/ and logs/ rather than
# removing the dirs themselves — the run script expects them to exist
# (`logdir.mkdir(parents=True, exist_ok=True)` only covers tensorboard).
_SMOKE_REMOVED_TREES = (("code", ".venv"),)
_SMOKE_RECURSIVE_DIRS = ("__pycache__",)
_SMOKE_WIPE_CONTENTS = (("tensorboard",), ("logs",))


def _wipe_dir_contents(d: Path) -> list:
    if not d.is_dir():
        return []
    removed: list = []
    for child in d.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed.append(child)
    return removed


def run_smoke_test_and_cleanup(exp_dir: Path) -> dict:
    """Run `uv sync && uv run run-experiment` inside `<exp>/code/`, then
    delete the artifacts the smoke run produced.

    Returns:
        {
          "ok":          bool,
          "stdout":      str,         # combined stdout/stderr from sync+run
          "removed":     list[Path],  # paths removed (relative to exp_dir)
          "uv":          str | None,  # resolved uv binary
          "skipped":     str | None,  # reason if smoke was skipped (e.g. no uv)
        }

    Cleanup runs only when the smoke test exits 0 — a failed smoke leaves
    artifacts in place so the operator can inspect them.
    """
    code_dir = exp_dir / "code"
    out: dict = {"ok": False, "stdout": "", "removed": [], "uv": None, "skipped": None}

    uv = shutil.which("uv")
    if uv is None:
        out["skipped"] = "uv not on PATH"
        return out
    out["uv"] = uv

    sync = subprocess.run(
        [uv, "sync"], cwd=str(code_dir),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    out["stdout"] += sync.stdout or ""
    if sync.returncode != 0:
        return out

    run = subprocess.run(
        [uv, "run", "run-experiment"], cwd=str(code_dir),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    out["stdout"] += run.stdout or ""
    if run.returncode != 0:
        return out

    out["ok"] = True
    removed: list = []
    for parts in _SMOKE_REMOVED_TREES:
        target = exp_dir.joinpath(*parts)
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(Path(*parts))
    for name in _SMOKE_RECURSIVE_DIRS:
        for d in list(code_dir.rglob(name)):
            if d.is_dir():
                shutil.rmtree(d)
                removed.append(d.relative_to(exp_dir))
    for parts in _SMOKE_WIPE_CONTENTS:
        target = exp_dir.joinpath(*parts)
        for child in _wipe_dir_contents(target):
            removed.append(child.relative_to(exp_dir))
    out["removed"] = removed
    return out
