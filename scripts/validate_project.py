from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.bootstrap import ensure_sumo_tools_on_path, get_sumo_home
from simulation.config import load_experiment_config
from simulation.logging_utils import configure_logging


def _check_executable(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} is not on PATH")
    return path


def validate_environment() -> dict[str, str]:
    tools = ensure_sumo_tools_on_path()
    sumo_home = get_sumo_home()
    import traci  # noqa: F401
    import sumolib  # noqa: F401

    return {
        "SUMO_HOME": str(sumo_home),
        "SUMO_TOOLS": str(tools),
        "sumo": _check_executable("sumo"),
        "netconvert": _check_executable("netconvert"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run without GUI checks.")
    parser.add_argument(
        "--config",
        default=PROJECT_ROOT / "config" / "experiment.yaml",
        type=Path,
    )
    args = parser.parse_args()

    configure_logging()
    logging.info("Loading config from %s", args.config)
    config = load_experiment_config(args.config)
    env = validate_environment()

    print(json.dumps({"config_path": str(config.source_path), "environment": env}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

