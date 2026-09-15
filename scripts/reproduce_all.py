from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from analysis.aggregate import save_aggregated_outputs
from analysis.plots import save_policy_comparison_plots
from simulation.config import load_experiment_config
from scripts.validate_project import validate_environment


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full SUMO reproduction workflow.")
    parser.add_argument("--config", default=PROJECT_ROOT / "config" / "experiment.yaml", type=Path)
    parser.add_argument("--root", default=PROJECT_ROOT, type=Path)
    parser.add_argument("--output-dir", default=None, type=Path)
    parser.add_argument("--gui", action="store_true", help="Launch the GUI after the pipeline completes.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the final pytest validation step.")
    parser.add_argument("--demo", action="store_true", help="Run the lightweight presentation demo.")
    parser.add_argument("--policies", nargs="+", default=None)
    parser.add_argument("--demand-levels", nargs="+", default=None)
    parser.add_argument("--seeds", nargs="+", type=int, default=None)
    parser.add_argument("--max-simulation-time", type=float, default=None)
    parser.add_argument("--max-wall-clock-seconds", type=float, default=None)
    parser.add_argument("--no-resume", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = args.root.resolve()

    policies = args.policies or ["normal", "long", "huang"]
    demand_levels = args.demand_levels or (["low"] if args.demo else ["low", "medium", "heavy"])
    seeds = args.seeds or ([11] if args.demo else [11, 22, 33, 44, 55])
    output_dir = args.output_dir.resolve() if args.output_dir else (root / "results" / "demo" if args.demo else root / "results")
    max_wall_clock_seconds = args.max_wall_clock_seconds if args.max_wall_clock_seconds is not None else (120.0 if args.demo else None)
    max_simulation_time = args.max_simulation_time if args.max_simulation_time is not None else (600.0 if args.demo else None)
    detector_output = os.devnull if args.demo else None
    config_path = _prepare_demo_config(args.config, output_dir) if args.demo else args.config

    validate_environment()
    _run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_network.py"), "--config", str(config_path), "--root", str(root)])
    _run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_signals.py"), "--config", str(config_path), "--root", str(root)])
    _run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_routes.py"), "--config", str(config_path), "--root", str(root)])
    run_experiments_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_experiments.py"),
        "--config",
        str(config_path),
        "--root",
        str(root),
        "--output-dir",
        str(output_dir),
        "--policies",
        *policies,
        "--demand-levels",
        *demand_levels,
        "--seeds",
        *[str(seed) for seed in seeds],
    ]
    # Demo runs must be fresh so the comparison uses one consistent horizon.
    if args.demo or args.no_resume:
        run_experiments_cmd.append("--no-resume")
    if args.max_simulation_time is not None:
        run_experiments_cmd.extend(["--max-simulation-time", str(args.max_simulation_time)])
    elif max_simulation_time is not None:
        run_experiments_cmd.extend(["--max-simulation-time", str(max_simulation_time)])
    if max_wall_clock_seconds is not None:
        run_experiments_cmd.extend(["--max-wall-clock-seconds", str(max_wall_clock_seconds)])
    if detector_output is not None:
        run_experiments_cmd.extend(["--detector-output", detector_output])
    _run(run_experiments_cmd)
    aggregate_payload = save_aggregated_outputs(output_dir)
    plot_payload = save_policy_comparison_plots(output_dir)
    _run([sys.executable, str(PROJECT_ROOT / "scripts" / "validate_project.py"), "--headless", "--config", str(config_path)])
    if not args.skip_tests:
        _run([sys.executable, "-m", "pytest"])
    if args.gui:
        _run([sys.executable, str(PROJECT_ROOT / "scripts" / "view_gui.py"), "--config", str(config_path), "--root", str(root)])

    print(json.dumps({"aggregate": aggregate_payload, "plots": plot_payload}, indent=2, sort_keys=True))
    return 0


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _prepare_demo_config(source_config: Path, output_dir: Path) -> Path:
    config = copy.deepcopy(load_experiment_config(source_config).data)
    config["simulation"]["route_generation_horizon_seconds"] = 180
    config["routes"]["demand_levels"]["low"] = 90
    config["congestion"]["warmup_seconds"] = 30
    config["congestion"]["activation_seconds"] = 60
    config["congestion"]["deactivation_seconds"] = 180
    config["congestion"]["incident_duration_seconds"] = 120

    output_dir.mkdir(parents=True, exist_ok=True)
    demo_config_path = output_dir / "demo_config.yaml"
    demo_config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return demo_config_path


if __name__ == "__main__":
    raise SystemExit(main())
