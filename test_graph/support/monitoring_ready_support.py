"""Consume the launcher proven by Test Graph's monitoring readiness node."""

from __future__ import annotations

import os
from pathlib import Path


MONITORING_READY_NODE = "monitoring.cluster.assert.ready"


def monitoring_cli_from_readiness(ctx) -> str:
    """Return the exact installed launcher recorded by the passed assertion."""

    envelope = ctx.upstream(MONITORING_READY_NODE)
    if not isinstance(envelope, dict):
        raise RuntimeError("monitoring readiness envelope is unavailable")
    if envelope.get("nodeId") != MONITORING_READY_NODE:
        raise RuntimeError("monitoring readiness envelope has the wrong node id")
    if envelope.get("status") != "passed":
        raise RuntimeError("monitoring readiness assertion did not pass")

    processes = envelope.get("processes")
    if not isinstance(processes, list):
        raise RuntimeError("monitoring readiness envelope has no process records")
    status_records = [
        record
        for record in processes
        if isinstance(record, dict) and record.get("label") == "status"
    ]
    if len(status_records) != 1:
        raise RuntimeError(
            "monitoring readiness envelope must contain exactly one status process"
        )

    record = status_records[0]
    command = record.get("command")
    if (
        not isinstance(command, list)
        or len(command) != 4
        or not all(isinstance(part, str) for part in command)
        or command[1:] != ["status", "--json", "--require-ready"]
    ):
        raise RuntimeError("monitoring readiness process has an unexpected command")
    if record.get("exitCode") != 0 or record.get("error") not in (None, ""):
        raise RuntimeError("monitoring readiness process was not successful")

    launcher = Path(command[0])
    if not launcher.is_absolute():
        raise RuntimeError("monitoring readiness launcher is not absolute")
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise RuntimeError(
            f"monitoring readiness launcher is not executable: {launcher}"
        )
    return str(launcher)
