from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analysis.aggregate import aggregate_policy_metrics, collect_run_summaries, save_aggregated_outputs
from analysis.statistics import percentage_difference, summarize_values
from simulation.batch import run_policy_matrix


def _fake_result(policy: str, demand: str, seed: int) -> dict:
    summary = {
        "policy": policy,
        "demand_level": demand,
        "seed": seed,
        "mean_travel_time_s": 10.0 + seed,
        "median_travel_time_s": 9.0 + seed,
        "mean_delay_s": 1.0,
        "mean_waiting_time_s": 2.0,
        "mean_time_loss_s": 3.0,
        "mean_speed_mps": 4.0,
        "mean_queue_length_m": 5.0,
        "max_queue_length_m": 6.0,
        "throughput": 7,
        "completed_trips": 7,
        "unfinished_trips": 0,
        "teleports": 0,
        "collisions": 0,
        "vehicles_entering_zone_ab": 1,
        "congestion_neighbouring_roads": 2,
        "simulation_capped": False,
    }
    return {"summary": summary, "files": {}, "policy_actions": [], "vehicle_rows": [], "route_rows": []}


def test_run_policy_matrix_resume_skips_existing_runs(tmp_path, monkeypatch):
    processed = tmp_path / "results" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    summary_path = processed / "normal_low_11_summary.json"
    summary_path.write_text(json.dumps(_fake_result("normal", "low", 11)), encoding="utf-8")

    calls: list[tuple[str, str, int]] = []

    def fail_if_called(*args, **kwargs):
        calls.append((args[2], args[3], args[4]))
        return _fake_result(args[2], args[3], args[4])

    monkeypatch.setattr("simulation.batch.run_policy_simulation", fail_if_called)
    manifest = run_policy_matrix(
        config={},
        root=tmp_path,
        policies=["normal"],
        demand_levels=["low"],
        seeds=[11],
        output_dir=tmp_path / "results",
        resume=True,
    )

    assert calls == []
    assert manifest["run_count"] == 1
    assert manifest["failure_count"] == 0


def test_aggregation_and_statistics(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    for policy in ["normal", "long", "huang"]:
        payload = _fake_result(policy, "low", 11)
        (processed / f"{policy}_low_11_summary.json").write_text(json.dumps(payload), encoding="utf-8")

    df = collect_run_summaries(tmp_path)
    metrics = aggregate_policy_metrics(df)
    assert set(metrics["policy"]) == {"normal", "long", "huang"}
    out = save_aggregated_outputs(tmp_path)
    assert Path(out["summary_csv"]).exists()
    assert Path(out["comparison_csv"]).exists()

    summary = summarize_values([1.0, 2.0, 3.0])
    assert summary["mean"] == 2.0
    assert percentage_difference(10.0, 12.0) == 20.0
