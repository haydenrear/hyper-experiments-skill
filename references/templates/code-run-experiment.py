"""Entry point for {{experiment_id}} — {{title}}.

Run from the hyper-experiments project root:

    uv sync --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code
    uv run --project experiments/families/{{family}}/{{experiment_id}}-{{slug}}/code run-experiment

Or from inside this code directory:

    uv sync
    uv run run-experiment

This stub loads `run_config.json` (inherited from the parent experiment
when one existed), opens a TensorBoard `SummaryWriter` pointed at
`<experiment>/tensorboard/`, and imports the shared library `python_exp`
as a sanity check. Replace `main()` with the actual experiment logic —
keep the writer wired to `config["paths"]["tensorboard"]` so `tb-query`
finds the event files at the expected location.
"""
from __future__ import annotations

import json
from pathlib import Path

from python_exp import hello
from tensorboardX import SummaryWriter

CONFIG_PATH = Path(__file__).parent / "run_config.json"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return json.load(f)


def make_writer(config: dict) -> SummaryWriter:
    logdir = (Path(__file__).parent / config["paths"]["tensorboard"]).resolve()
    logdir.mkdir(parents=True, exist_ok=True)
    tb_cfg = config.get("logging", {}).get("tensorboard", {})
    return SummaryWriter(
        logdir=str(logdir),
        flush_secs=tb_cfg.get("flush_secs", 30),
        max_queue=tb_cfg.get("max_queue", 100),
    )


def main() -> int:
    config = load_config()
    print(f"Run config: {config['run_name']} (family={config['family']})")
    print(hello())

    writer = make_writer(config)
    try:
        writer.add_scalar("scaffold/heartbeat", 1.0, global_step=0)
        print(f"TensorBoard logdir: {writer.logdir}")
        print(f"TODO: implement experiment logic for {config['experiment_id']}")
    finally:
        writer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
