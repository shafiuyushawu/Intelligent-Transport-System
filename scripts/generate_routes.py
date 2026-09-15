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
from simulation.routes import generate_route_artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=PROJECT_ROOT / "config" / "experiment.yaml",
        type=Path,
    )
    parser.add_argument("--root", default=PROJECT_ROOT, type=Path)
    parser.add_argument("--demand", choices=["low", "medium", "heavy"], default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    configure_logging()
    config = load_experiment_config(args.config)
    metadata = generate_route_artifacts(config.data, args.root, demand_level=args.demand, seed=args.seed)
    logging.info("Generated route files for %s demand levels", len(metadata["levels"]))
    print(json.dumps(metadata["levels"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
