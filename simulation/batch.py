from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from simulation.runner import run_policy_simulation


def run_policy_matrix(
    config: dict[str, Any],
    root: str | Path,
    policies: list[str],
    demand_levels: list[str],
    seeds: list[int],
    *,
    gui: bool = False,
    output_dir: str | Path | None = None,
    resume: bool = True,
    max_simulation_time: float | None = None,
    max_wall_clock_seconds: float | None = None,
    detector_output: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    results_root = Path(output_dir) if output_dir is not None else root_path / "results"
    processed_dir = results_root / "processed"
    logs_dir = results_root / "logs"
    processed_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for policy in policies:
        for demand in demand_levels:
            for seed in seeds:
                summary_path = processed_dir / f"{policy}_{demand}_{seed}_summary.json"
                if resume and summary_path.exists():
                    runs.append(json.loads(summary_path.read_text(encoding="utf-8")))
                    continue
                try:
                    result = run_policy_simulation(
                        config,
                        root_path,
                        policy,
                        demand,
                        seed,
                        gui=gui,
                        output_dir=results_root,
                        max_simulation_time=max_simulation_time,
                        max_wall_clock_seconds=max_wall_clock_seconds,
                        detector_output=detector_output,
                    )
                    runs.append(result)
                except Exception as exc:  # pragma: no cover - surfaced in failure report
                    failures.append(
                        {
                            "policy": policy,
                            "demand": demand,
                            "seed": seed,
                            "error": str(exc),
                        }
                    )

    matrix_rows = [_matrix_row(run) for run in runs]
    matrix_df = pd.DataFrame(matrix_rows)
    matrix_csv = processed_dir / "matrix_summary.csv"
    if not matrix_df.empty:
        matrix_df.sort_values(["policy", "demand_level", "seed"], inplace=True)
        matrix_df.to_csv(matrix_csv, index=False)
    else:
        matrix_csv.write_text("", encoding="utf-8")

    manifest = {
        "policies": policies,
        "demand_levels": demand_levels,
        "seeds": seeds,
        "runs": runs,
        "failures": failures,
        "matrix_csv": str(matrix_csv),
        "run_count": len(runs),
        "failure_count": len(failures),
    }
    (processed_dir / "matrix_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _matrix_row(result: dict[str, Any]) -> dict[str, Any]:
    summary = result["summary"]
    return {
        "policy": summary["policy"],
        "demand_level": summary["demand_level"],
        "seed": summary["seed"],
        "mean_travel_time_s": summary.get("mean_travel_time_s", 0.0),
        "median_travel_time_s": summary.get("median_travel_time_s", 0.0),
        "mean_delay_s": summary.get("mean_delay_s", 0.0),
        "mean_waiting_time_s": summary.get("mean_waiting_time_s", 0.0),
        "mean_time_loss_s": summary.get("mean_time_loss_s", 0.0),
        "mean_speed_mps": summary.get("mean_speed_mps", 0.0),
        "mean_queue_length_m": summary.get("mean_queue_length_m", 0.0),
        "max_queue_length_m": summary.get("max_queue_length_m", 0.0),
        "throughput": summary.get("throughput", summary.get("completed_trips", 0)),
        "completed_trips": summary.get("completed_trips", 0),
        "unfinished_trips": summary.get("unfinished_trips", 0),
        "teleports": summary.get("teleports", 0),
        "collisions": summary.get("collisions", 0),
        "vehicles_entering_zone_ab": summary.get("vehicles_entering_zone_ab", 0),
        "congestion_neighbouring_roads": summary.get("congestion_neighbouring_roads", 0),
        "simulation_capped": summary.get("simulation_capped", False),
    }
