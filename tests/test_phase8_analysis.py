from __future__ import annotations

import json
from pathlib import Path

from analysis.aggregate import (
    aggregate_route_metrics,
    aggregate_segment_metrics,
    collect_route_summaries,
    save_aggregated_outputs,
)
from analysis.plots import save_policy_comparison_plots


def _summary_payload(policy: str, demand: str, seed: int) -> dict:
    summary = {
        "policy": policy,
        "demand_level": demand,
        "seed": seed,
        "mean_travel_time_s": 10.0 + seed,
        "median_travel_time_s": 9.0 + seed,
        "mean_delay_s": 1.0 + seed / 10.0,
        "mean_waiting_time_s": 2.0 + seed / 10.0,
        "mean_time_loss_s": 3.0 + seed / 10.0,
        "mean_speed_mps": 4.0,
        "mean_queue_length_m": 5.0 + seed / 10.0,
        "max_queue_length_m": 6.0 + seed / 10.0,
        "throughput": 7 + seed,
        "completed_trips": 7 + seed,
        "unfinished_trips": 0,
        "teleports": 0,
        "collisions": 0,
        "vehicles_entering_zone_ab": 1 + seed,
        "congestion_neighbouring_roads": 2 + seed,
        "simulation_capped": False,
    }
    route_rows = [
        {
            "route_id": f"{policy}_{demand}_I1",
            "entrance": "I",
            "exit": "1",
            "movement": "straight",
            "vehicle_count": 2,
            "mean_travel_time_s": 11.0 + seed,
            "median_travel_time_s": 11.0 + seed,
            "mean_waiting_time_s": 1.0,
            "mean_time_loss_s": 1.5,
            "mean_speed_mps": 6.0,
            "route_length_m": 100.0,
        },
        {
            "route_id": f"{policy}_{demand}_J2",
            "entrance": "J",
            "exit": "2",
            "movement": "right",
            "vehicle_count": 3,
            "mean_travel_time_s": 12.0 + seed,
            "median_travel_time_s": 12.0 + seed,
            "mean_waiting_time_s": 2.0,
            "mean_time_loss_s": 2.5,
            "mean_speed_mps": 5.0,
            "route_length_m": 120.0,
        },
        {
            "route_id": f"{policy}_{demand}_K3",
            "entrance": "K",
            "exit": "3",
            "movement": "left",
            "vehicle_count": 1,
            "mean_travel_time_s": 13.0 + seed,
            "median_travel_time_s": 13.0 + seed,
            "mean_waiting_time_s": 3.0,
            "mean_time_loss_s": 3.5,
            "mean_speed_mps": 4.0,
            "route_length_m": 140.0,
        },
    ]
    return {"summary": summary, "files": {}, "policy_actions": [], "vehicle_rows": [], "route_rows": route_rows}


def test_phase8_aggregation_and_plots(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    for policy in ["normal", "long", "huang"]:
        for demand in ["low", "medium", "heavy"]:
            payload = _summary_payload(policy, demand, seed=11)
            (processed / f"{policy}_{demand}_11_summary.json").write_text(json.dumps(payload), encoding="utf-8")

    aggregate_payload = save_aggregated_outputs(tmp_path)
    plot_payload = save_policy_comparison_plots(tmp_path)

    assert Path(aggregate_payload["summary_csv"]).exists()
    assert Path(aggregate_payload["route_summary_csv"]).exists()
    assert Path(aggregate_payload["segment_summary_csv"]).exists()
    assert Path(aggregate_payload["comparison_csv"]).exists()
    assert len(plot_payload) >= 7
    assert (tmp_path / "figures" / "low_travel_time.png").exists()
    assert (tmp_path / "figures" / "overall_travel_time.pdf").exists()
    assert (tmp_path / "figures" / "segment_comparison.png").exists()


def test_route_and_segment_aggregation(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    payload = _summary_payload("normal", "low", 11)
    (processed / "normal_low_11_summary.json").write_text(json.dumps(payload), encoding="utf-8")

    route_df = aggregate_route_metrics(collect_route_summaries(tmp_path))
    segment_df = aggregate_segment_metrics(collect_route_summaries(tmp_path))
    assert set(route_df["entrance"]) == {"I", "J", "K"}
    assert set(segment_df["entrance"]) == {"I", "J", "K"}
