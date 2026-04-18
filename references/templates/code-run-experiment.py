"""Entry point for {{experiment_id}} — {{title}}.

Run from the hyper-experiments project root:

    uv sync --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code
    uv run --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code run-experiment

Or from inside this code directory:

    uv sync
    uv run run-experiment

This stub imports from the shared library `python_exp` (provided by
`tools/python_exp/`) as a sanity check. Replace `main()` with the actual
experiment logic.
"""
from python_exp import hello


def main() -> int:
    print(hello())
    print("TODO: implement experiment logic for {{experiment_id}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
