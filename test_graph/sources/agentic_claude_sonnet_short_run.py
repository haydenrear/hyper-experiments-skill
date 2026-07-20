# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Run one agentic-fitness iteration through Claude Sonnet and ACP."""
from __future__ import annotations

import sys
from pathlib import Path

from testgraphsdk import NodeSpec, node

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from hyper_run_support import run_claude_openevolve_node  # noqa: E402


SPEC = (
    NodeSpec("hyper.agentic.claude_sonnet.short_run")
    .kind("action")
    .depends_on("hyper.variants.scaffolded")
    .tags(
        "openevolve",
        "agentic-fitness",
        "claude",
        "sonnet",
        "claude-agent-acp",
        "live",
    )
    .timeout("45m")
    .side_effects("fs:tmp", "net:local", "net:external")
    .output("outcome", "string")
    .output("traceId", "string")
    .output("serviceName", "string")
    .output("variant", "string")
    .output("acpSkillHome", "string")
)


@node(SPEC)
def main(ctx):
    return run_claude_openevolve_node(ctx, variant_key="agentic")


if __name__ == "__main__":
    main()
