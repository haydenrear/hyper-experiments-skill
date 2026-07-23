# /// script
# requires-python = ">=3.10"
# dependencies = ["testgraphsdk"]
#
# [tool.uv.sources]
# testgraphsdk = { path = "../sdk/python", editable = true }
# ///
"""Run the fresh default template without an LLM."""
from __future__ import annotations

import sys
from pathlib import Path

from testgraphsdk import NodeSpec, node

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from hyper_run_support import run_default_node  # noqa: E402


SPEC = (
    NodeSpec("hyper.default.short_run")
    .kind("action")
    .depends_on("hyper.variants.scaffolded")
    .depends_on("monitoring.cluster.assert.ready")
    .tags("hyper-experiments", "default", "observability", "live")
    .timeout("30m")
    .side_effects("fs:tmp", "net:local", "net:external")
    .output("outcome", "string")
    .output("traceId", "string")
    .output("serviceName", "string")
    .output("variant", "string")
)


@node(SPEC)
def main(ctx):
    return run_default_node(ctx)


if __name__ == "__main__":
    main()
