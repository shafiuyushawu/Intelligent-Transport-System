from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.aggregate import save_aggregated_outputs
from analysis.plots import save_policy_comparison_plots
from simulation.batch import run_policy_matrix
from simulation.config import load_experiment_config
from simulation.logging_utils import configure_logging
from scripts.validate_project import validate_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase 7 policy experiment matrix.")
    parser.add_argument("--config", default=Path("config/experiment.yaml"), type=Path)
    parser.add_argument("--root", default=Path("."), type=Path)
    parser.add_argument("--output-dir", default=None, type=Path)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--policies", nargs="+", default=["normal", "long", "huang"])
    parser.add_argument("--demand-levels", nargs="+", default=["low", "medium", "heavy"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 22, 33, 44, 55])
    parser.add_argument("--max-simulation-time", type=float, default=None)
    parser.add_argument("--max-wall-clock-seconds", type=float, default=None)
    parser.add_argument("--detector-output", default=None)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging()
    validate_environment()
    config = load_experiment_config(args.config).data
    root = args.root.resolve()
    output_dir = args.output_dir.resolve() if args.output_dir else root / "results"

    manifest = run_policy_matrix(
        config,
        root,
        policies=args.policies,
        demand_levels=args.demand_levels,
        seeds=args.seeds,
        gui=args.gui,
        output_dir=output_dir,
        resume=not args.no_resume,
        max_simulation_time=args.max_simulation_time,
        max_wall_clock_seconds=args.max_wall_clock_seconds,
        detector_output=args.detector_output,
    )
    aggregate_payload = save_aggregated_outputs(output_dir)
    plot_payload = save_policy_comparison_plots(output_dir)

    print(json.dumps({"matrix": manifest, "aggregate": aggregate_payload, "plots": plot_payload}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
