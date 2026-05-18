"""Shared helpers for hyper-experiments scaffolding scripts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "references" / "templates"
ROOT_MARKER = "hyper-experiments.md"
EXP_ID_RE = re.compile(r"^exp-(\d{4})")

VALID_VARIANTS = ("default", "evolve")
DEFAULT_VARIANT = "default"

# OpenEvolve writes its MAP-Elites database into per-experiment
# `<exp>/logs/openevolve_output/`, with snapshots saved as
# `checkpoint_<N>/` subdirectories at the `checkpoint_interval`
# declared in `code/config.yaml`. The default path is mirrored in the
# evolve `run_config.json` template at `paths.openevolve_output`.
OPENEVOLVE_DB_REL = Path("logs/openevolve_output")
_OPENEVOLVE_CHECKPOINT_RE = re.compile(r"^checkpoint_(\d+)$")
_ZERO_OID = "0" * 40


class ProjectLockError(RuntimeError):
    """Raised when a project-scoped git lock cannot be acquired or released."""


class GitProjectLock:
    """A project-scoped lock backed by an atomic git ref update.

    The ref points at a small blob containing owner metadata. `git update-ref`
    is the compare-and-swap primitive: acquisition creates the ref only if it
    does not exist, stale stealing replaces only the exact observed owner, and
    release deletes only if this process still owns the ref.
    """

    def __init__(
        self,
        *,
        git_dir: Path,
        ref: str,
        oid: str,
        metadata: dict,
    ) -> None:
        self.git_dir = git_dir
        self.ref = ref
        self.oid = oid
        self.metadata = metadata
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        proc = _git(
            self.git_dir,
            ["update-ref", "-d", self.ref, self.oid],
            check=False,
        )
        self._released = True
        if proc.returncode != 0:
            raise ProjectLockError(
                f"could not release project lock {self.ref}; "
                f"it may have expired or been stolen. git said: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.release()
        except ProjectLockError as e:
            if exc_type is not None:
                print(f"warning: {e}", file=sys.stderr)
                return
            raise


def _git(cwd: Path, args: list[str], *, input_text: str | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as e:
        raise ProjectLockError("git executable not found; project locks require git") from e
    except subprocess.SubprocessError as e:
        raise ProjectLockError(f"git {' '.join(args)} failed: {e}") from e
    if check and proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise ProjectLockError(f"git {' '.join(args)} failed: {msg}")
    return proc


def _git_toplevel(root: Path) -> Path:
    proc = _git(root, ["rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise ProjectLockError(
            f"{root} is not inside a git worktree; hyper-experiments "
            f"project locks are git-backed. Initialize or enter a git "
            f"worktree before running this script. git said: {msg}"
        )
    return Path(proc.stdout.strip()).resolve()


def _project_lock_ref(git_top: Path, root: Path, name: str) -> str:
    try:
        project_id_source = root.resolve().relative_to(git_top)
    except ValueError:
        project_id_source = root.resolve()
    project_id = hashlib.sha1(str(project_id_source).encode("utf-8")).hexdigest()[:16]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-/") or "project"
    return f"refs/hyper-experiments/locks/{project_id}/{safe_name}"


def _write_lock_blob(git_top: Path, metadata: dict) -> str:
    payload = json.dumps(metadata, sort_keys=True, indent=2) + "\n"
    proc = _git(git_top, ["hash-object", "-w", "--stdin"], input_text=payload)
    return proc.stdout.strip()


def _read_lock_metadata(git_top: Path, oid: str | None) -> dict:
    if not oid:
        return {}
    proc = _git(git_top, ["cat-file", "-p", oid], check=False)
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def _lock_holder_summary(metadata: dict, oid: str | None) -> str:
    if not metadata:
        return oid or "unknown owner"
    host = metadata.get("host", "unknown-host")
    pid = metadata.get("pid", "unknown-pid")
    acquired = metadata.get("acquired_at", "unknown-time")
    token = str(metadata.get("token", ""))[:8]
    suffix = f", token {token}" if token else ""
    return f"{host} pid {pid}, acquired {acquired}{suffix}"


def acquire_project_lock(
    root: Path,
    name: str,
    *,
    timeout_seconds: float = 30.0,
    wait: bool = True,
    stale_after_seconds: float = 900.0,
) -> GitProjectLock:
    """Acquire a project-scoped lock using an atomic git ref.

    The lock is visible to every process using the same git worktree/repository.
    It fails after `timeout_seconds` unless `wait` is false, in which case it
    makes one attempt and returns a retryable error.
    """
    root = root.resolve()
    git_top = _git_toplevel(root)
    ref = _project_lock_ref(git_top, root, name)
    now = time.time()
    metadata = {
        "project_root": str(root),
        "lock": name,
        "ref": ref,
        "token": uuid.uuid4().hex,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "acquired_at": utcnow_iso(),
        "acquired_at_epoch": now,
        "stale_after_seconds": stale_after_seconds,
    }
    oid = _write_lock_blob(git_top, metadata)
    deadline = time.monotonic() + max(timeout_seconds, 0.0)

    while True:
        proc = _git(
            git_top,
            ["update-ref", "--create-reflog", ref, oid, _ZERO_OID],
            check=False,
        )
        if proc.returncode == 0:
            return GitProjectLock(git_dir=git_top, ref=ref, oid=oid, metadata=metadata)

        current_proc = _git(git_top, ["rev-parse", "-q", "--verify", ref], check=False)
        current_oid = current_proc.stdout.strip() if current_proc.returncode == 0 else None
        holder = _read_lock_metadata(git_top, current_oid)
        holder_age = time.time() - float(holder.get("acquired_at_epoch", time.time()))

        if stale_after_seconds > 0 and holder_age > stale_after_seconds and current_oid:
            steal = _git(
                git_top,
                ["update-ref", "-m", "steal stale hyper-experiments lock",
                 ref, oid, current_oid],
                check=False,
            )
            if steal.returncode == 0:
                return GitProjectLock(git_dir=git_top, ref=ref, oid=oid, metadata=metadata)

        timed_out = (not wait) or time.monotonic() >= deadline
        if timed_out:
            raise ProjectLockError(
                f"project lock {name!r} is held by "
                f"{_lock_holder_summary(holder, current_oid)}. Retry the "
                f"command, increase --lock-timeout, or use --lock-stale-after "
                f"only after confirming the owner died."
            )
        time.sleep(0.25)


def project_lock_status(root: Path, name: str) -> dict:
    """Return the current git-backed lock status for `name`."""
    root = root.resolve()
    git_top = _git_toplevel(root)
    ref = _project_lock_ref(git_top, root, name)
    current_proc = _git(git_top, ["rev-parse", "-q", "--verify", ref], check=False)
    if current_proc.returncode != 0:
        return {"locked": False, "ref": ref, "oid": None, "metadata": {}}
    oid = current_proc.stdout.strip()
    return {
        "locked": True,
        "ref": ref,
        "oid": oid,
        "metadata": _read_lock_metadata(git_top, oid),
    }


def release_project_lock(
    root: Path,
    name: str,
    *,
    token: str | None = None,
    force: bool = False,
) -> dict:
    """Release a project lock by token, or force-release it explicitly.

    Normal releases require the owner token printed by `project_lock.py acquire`.
    `force=True` is for operator cleanup after confirming the owner process died.
    """
    root = root.resolve()
    git_top = _git_toplevel(root)
    status = project_lock_status(root, name)
    if not status["locked"]:
        return status

    metadata = status["metadata"]
    expected = metadata.get("token")
    if not force and (not token or token != expected):
        raise ProjectLockError(
            f"refusing to release project lock {name!r}: owner token does not "
            f"match. Use the token printed by acquire, or pass --force after "
            f"confirming the owner died."
        )

    proc = _git(
        git_top,
        ["update-ref", "-d", status["ref"], status["oid"]],
        check=False,
    )
    if proc.returncode != 0:
        raise ProjectLockError(
            f"could not release project lock {name!r}; it may have changed. "
            f"git said: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    status["released"] = True
    return status


def openevolve_db_dir(exp_dir: Path) -> Path:
    """Return the openevolve database directory for `exp_dir`."""
    return exp_dir / OPENEVOLVE_DB_REL


def openevolve_latest_checkpoint(exp_dir: Path):
    """Return (iteration, absolute_path) for the highest-numbered
    openevolve checkpoint under `exp_dir/logs/openevolve_output/`, or
    None if the database is empty / missing.
    """
    db_dir = openevolve_db_dir(exp_dir)
    if not db_dir.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for child in db_dir.iterdir():
        if not child.is_dir():
            continue
        m = _OPENEVOLVE_CHECKPOINT_RE.match(child.name)
        if not m:
            continue
        n = int(m.group(1))
        if best is None or n > best[0]:
            best = (n, child)
    return best


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "untitled"


def bullet_list(items):
    items = [i for i in (items or []) if i]
    return "\n".join(f"- {it}" for it in items)


def load_template(name: str, variant: str | None = None) -> str:
    """Read a template by name, with optional variant override.

    Variant resolution order:
      1. `<variant>/<name>` if `variant` is given and the file exists,
      2. fallback to `<name>` at the templates root.

    This lets common templates (index.md, plan.md, ...) live once at
    the root while letting a variant override only the files it needs
    to change (typically the `code-*` set). The default variant has
    its `code-*` set under `default/`; the evolve variant has its
    expanded `code-*` set under `evolve/`.
    """
    if variant:
        candidate = TEMPLATES_DIR / variant / name
        if candidate.exists():
            return candidate.read_text()
    return (TEMPLATES_DIR / name).read_text()


def template_exists(name: str, variant: str | None = None) -> bool:
    """Return True if `<variant>/<name>` or `<name>` exists in templates."""
    if variant and (TEMPLATES_DIR / variant / name).exists():
        return True
    return (TEMPLATES_DIR / name).exists()


_VARIANT_FIELD_RE = re.compile(r"^- Variant:\s*(\S+)\s*$", re.MULTILINE)


def project_variant_from_marker(root: Path) -> str:
    """Read the project's default variant from `<root>/hyper-experiments.md`.

    Returns DEFAULT_VARIANT if the marker has no Variant line (legacy
    projects scaffolded before variants existed).
    """
    marker = root / ROOT_MARKER
    if not marker.exists():
        return DEFAULT_VARIANT
    m = _VARIANT_FIELD_RE.search(marker.read_text())
    if m and m.group(1) in VALID_VARIANTS:
        return m.group(1)
    return DEFAULT_VARIANT


def experiment_variant_from_run_config(exp_dir: Path) -> str:
    """Read an experiment's variant from `code/run_config.json`.

    Returns DEFAULT_VARIANT when the file is missing or doesn't carry a
    `variant` field (legacy experiments scaffolded before variants
    existed are default by definition)."""
    cfg = exp_dir / "code" / "run_config.json"
    if not cfg.exists():
        return DEFAULT_VARIANT
    try:
        obj = json.loads(cfg.read_text())
    except json.JSONDecodeError:
        return DEFAULT_VARIANT
    v = obj.get("variant")
    return v if v in VALID_VARIANTS else DEFAULT_VARIANT


def validate_variant(variant: str) -> str:
    if variant not in VALID_VARIANTS:
        raise ValueError(
            f"unknown variant {variant!r}; valid: {', '.join(VALID_VARIANTS)}"
        )
    return variant


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


def parent_slug_from_dir(parent_dir_name: str):
    """Extract the slug from a parent experiment directory name like
    `exp-0036-polynomial-grpo-overfit-shakedown` → `polynomial-grpo-overfit-shakedown`.
    Returns None if the name does not match the canonical pattern."""
    m = re.match(r"^exp-\d{4}-(.*)$", parent_dir_name)
    return m.group(1) if m else None


_TEXT_REWRITE_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def branch_text_replacements(parent_identity: tuple, child_identity: tuple):
    """Return the ordered string replacements for a branched copied tree.

    The order is intentionally simple and visible:
      1. full `exp-NNNN-source-slug` prefix,
      2. bare `exp-NNNN`,
      3. bare source slug.

    The caller protects the full prefix before running the bare id and slug
    replacements, so `exp-0049-old-slug` is counted as one id+slug rewrite
    instead of three overlapping rewrites.
    """
    parent_exp_id, parent_slug = parent_identity
    child_exp_id, child_slug = child_identity
    replacements = []
    if parent_slug:
        replacements.append((
            f"{parent_exp_id}-{parent_slug}",
            f"{child_exp_id}-{child_slug}",
            "id+slug",
        ))
    replacements.append((parent_exp_id, child_exp_id, "id"))
    if parent_slug:
        replacements.append((parent_slug, child_slug, "slug"))
    return replacements


def replace_branch_identity_in_string(
    value: str,
    *,
    parent_identity: tuple,
    child_identity: tuple,
) -> tuple[str, list]:
    """Apply the branch text replacements to one string value.

    Returns `(new_value, replacement_counts)`, where replacement_counts is
    a list of `{kind, old, new, count}` dicts.
    """
    parent_exp_id, parent_slug = parent_identity
    child_exp_id, child_slug = child_identity
    new_value = value
    counts = []

    marker = None
    if parent_slug:
        old_full = f"{parent_exp_id}-{parent_slug}"
        new_full = f"{child_exp_id}-{child_slug}"
        full_count = new_value.count(old_full)
        if full_count:
            marker_base = "__HX_BRANCH_FULL_ID_SLUG_REWRITE__"
            marker = marker_base
            i = 0
            while marker in new_value:
                i += 1
                marker = f"{marker_base}{i}__"
            new_value = new_value.replace(old_full, marker)
            counts.append({
                "kind": "id+slug",
                "old": old_full,
                "new": new_full,
                "count": full_count,
            })

    slug_marker = None
    if parent_slug and parent_slug in child_slug and child_slug in new_value:
        marker_base = "__HX_BRANCH_CHILD_SLUG_PROTECT__"
        slug_marker = marker_base
        i = 0
        while slug_marker in new_value:
            i += 1
            slug_marker = f"{marker_base}{i}__"
        new_value = new_value.replace(child_slug, slug_marker)

    for old, new, kind in branch_text_replacements(parent_identity, child_identity):
        if kind == "id+slug":
            continue
        count = new_value.count(old)
        if not count:
            continue
        new_value = new_value.replace(old, new)
        counts.append({"kind": kind, "old": old, "new": new, "count": count})
    if slug_marker is not None:
        new_value = new_value.replace(slug_marker, child_slug)
    if marker is not None:
        new_value = new_value.replace(marker, f"{child_exp_id}-{child_slug}")
    return new_value, counts


def rewrite_branch_identity_in_text_files(
    paths,
    *,
    report_root: Path,
    parent_identity: tuple,
    child_identity: tuple,
):
    """Run the branch search/replace over copied text files.

    Binary files and non-UTF-8 files are skipped. Returns
    `(relative_path, replacement_counts)` entries for changed files.
    """
    changed = []

    def iter_files(path: Path):
        if not path.exists():
            return
        if path.is_file():
            yield path
            return
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [
                d for d in dirnames if d not in _TEXT_REWRITE_SKIP_DIRS
            ]
            base = Path(dirpath)
            for filename in filenames:
                yield base / filename

    for path in paths:
        for file_path in iter_files(path):
            try:
                raw = file_path.read_bytes()
            except OSError:
                continue
            if b"\0" in raw:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            new, counts = replace_branch_identity_in_string(
                text,
                parent_identity=parent_identity,
                child_identity=child_identity,
            )
            if not counts:
                continue
            file_path.write_bytes(new.encode("utf-8"))
            changed.append((file_path.relative_to(report_root), counts))
    return changed


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


def run_smoke_test_and_cleanup(exp_dir: Path, variant: str = DEFAULT_VARIANT) -> dict:
    """Run `uv sync && uv run run-experiment` inside `<exp>/code/`, then
    delete the artifacts the smoke run produced.

    For the `evolve` variant, the run-experiment invocation is wrapped
    with `OPENEVOLVE_SMOKE=1` so it short-circuits before any LLM call —
    the smoke goal is "scaffold reproduces and entry points import",
    not "burn API credits."

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

    import os as _os
    run_env = _os.environ.copy()
    if variant == "evolve":
        run_env["OPENEVOLVE_SMOKE"] = "1"
    run = subprocess.run(
        [uv, "run", "run-experiment"], cwd=str(code_dir),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=run_env,
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
