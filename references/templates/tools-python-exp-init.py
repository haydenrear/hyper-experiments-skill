"""Shared tooling importable from any experiment's code/ as `python_exp`.

Add shared modules, helpers, and utilities here. Experiments declare this
package as an editable dependency via their own `code/pyproject.toml`, so
changes to code under this directory are immediately visible to every
experiment's virtual environment after `uv sync`.
"""


def hello() -> str:
    """Placeholder export so experiments can confirm the shared library
    is installed correctly. Safe to delete once real utilities exist."""
    return "python_exp: shared tools are wired up"
