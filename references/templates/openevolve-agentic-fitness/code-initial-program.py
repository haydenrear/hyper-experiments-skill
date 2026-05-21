# Seed program for {{experiment_id}} — {{title}}.
#
# This is the program that openevolve will mutate iteratively. Mark the
# regions that the LLM is allowed to evolve with `# EVOLVE-BLOCK-START`
# and `# EVOLVE-BLOCK-END`. Code outside the markers stays fixed.
#
# Construction guidance for an evolve experiment:
#
#   1. Decide what is being evolved. A single function? A module? An
#      entire pipeline? The "meta-loop" framing in SKILL.md > Variants
#      applies even when there is only one element being evolved —
#      describe the loop in `plan.md`'s 'Implementation' section.
#   2. Keep the seed minimal and obviously correct. Evolution recovers
#      faster from a slow-but-correct seed than from a buggy clever one.
#   3. The non-evolving outer wrapper (below the EVOLVE-BLOCK-END) is
#      the contract the evaluator depends on. Pin its API early —
#      changing it mid-experiment invalidates earlier generations.
#   4. Imports of `python_exp` and any other shared libraries belong
#      OUTSIDE the EVOLVE markers, otherwise the LLM may delete them.
#
# After editing, run a smoke check before launch:
#
#     OPENEVOLVE_SMOKE=1 uv run run-experiment

from __future__ import annotations

# Imports that must NOT be evolved — keep above the EVOLVE-BLOCK markers.
# from python_exp import ...

# EVOLVE-BLOCK-START
"""Initial implementation. Replace with your seed."""


def solve(*args, **kwargs):
    """The function under evolution.

    Replace this body with your seed implementation. Keep the signature
    fixed — `evaluator.py` calls into this function (or whatever entry
    point you wire up below) and a signature change breaks the
    evaluator without producing useful evolutionary signal.
    """
    raise NotImplementedError("TODO: provide a seed implementation for {{experiment_id}}")


# EVOLVE-BLOCK-END


# Fixed (not evolved) — the contract `evaluator.py` depends on. Keep this
# stable across the entire evolutionary run.

def run() -> dict:
    """Entry point the evaluator calls. Returns whatever shape the
    evaluator expects (metrics dict, single value, tuple, etc.)."""
    # TODO: wire this to call solve(...) with this experiment's inputs
    # and return the value(s) the evaluator scores.
    raise NotImplementedError("TODO: implement run() so evaluator.py can score it")


if __name__ == "__main__":
    print(run())
