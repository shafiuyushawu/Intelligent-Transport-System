from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.config import load_experiment_config
from simulation.logging_utils import configure_logging
from simulation.network_builder import generate_network_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=PROJECT_ROOT / "config" / "experiment.yaml",
        type=Path,
    )
    parser.add_argument("--root", default=PROJECT_ROOT, type=Path)
    args = parser.parse_args()

    configure_logging()
    config = load_experiment_config(args.config)
    metadata = generate_network_artifacts(config.data, args.root)
    logging.info("Generated network with %s intersections", metadata["counts"]["intersections"])
    print(json.dumps(metadata["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
