from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.config import load_experiment_config
from simulation.congestion import run_congestion_comparison
from simulation.logging_utils import configure_logging


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=PROJECT_ROOT / "config" / "experiment.yaml", type=Path)
    parser.add_argument("--root", default=PROJECT_ROOT, type=Path)
    parser.add_argument(
        "--route-file",
        default=PROJECT_ROOT / "routes" / "generated" / "low.rou.xml",
        type=Path,
    )
    parser.add_argument("--output-prefix", default="zone_ab", type=str)
    args = parser.parse_args()

    configure_logging()
    config = load_experiment_config(args.config)
    result = run_congestion_comparison(config.data, args.root, args.route_file, output_prefix=args.output_prefix)
    print(json.dumps(result["improvements"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
