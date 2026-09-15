from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.statistics import percentage_difference, summarize_values


def load_matrix_manifest(results_root: str | Path) -> dict[str, Any]:
    root = Path(results_root)
    manifest_path = root / "processed" / "matrix_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"runs": []}


def collect_run_summaries(results_root: str | Path) -> pd.DataFrame:
    root = Path(results_root)
    rows: list[dict[str, Any]] = []
    for summary_path in sorted((root / "processed").glob("*_summary.json")):
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows.append(payload["summary"])
    return pd.DataFrame(rows)


def collect_route_summaries(results_root: str | Path) -> pd.DataFrame:
    root = Path(results_root)
    rows: list[dict[str, Any]] = []
    for summary_path in sorted((root / "processed").glob("*_summary.json")):
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        summary = payload.get("summary", {})
        for route_row in payload.get("route_rows", []):
            row = dict(route_row)
            row["policy"] = summary.get("policy")
            row["demand_level"] = summary.get("demand_level")
            row["seed"] = summary.get("seed")
            rows.append(row)
    return pd.DataFrame(rows)


def aggregate_policy_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working_df = df.copy()
    if "throughput" not in working_df.columns:
        if "completed_trips" in working_df.columns:
            working_df["throughput"] = working_df["completed_trips"]
        else:
            working_df["throughput"] = 0.0
    metrics = [
        "mean_travel_time_s",
        "median_travel_time_s",
        "mean_delay_s",
        "mean_waiting_time_s",
        "mean_time_loss_s",
        "mean_speed_mps",
        "mean_queue_length_m",
        "max_queue_length_m",
        "throughput",
        "completed_trips",
        "unfinished_trips",
        "teleports",
        "collisions",
        "vehicles_entering_zone_ab",
        "congestion_neighbouring_roads",
    ]
    rows: list[dict[str, Any]] = []
    for (policy, demand), group in working_df.groupby(["policy", "demand_level"], dropna=False):
        row: dict[str, Any] = {"policy": policy, "demand_level": demand, "runs": len(group)}
        for metric in metrics:
            if metric not in group.columns:
                values: list[float] = []
            else:
                values = [float(value) for value in group[metric].tolist() if value is not None]
            summary = summarize_values(values)
            row[f"{metric}_mean"] = summary["mean"]
            row[f"{metric}_median"] = summary["median"]
            row[f"{metric}_std"] = summary["std"]
            row[f"{metric}_min"] = summary["min"]
            row[f"{metric}_max"] = summary["max"]
            row[f"{metric}_ci95_low"] = summary["ci95_low"]
            row[f"{metric}_ci95_high"] = summary["ci95_high"]
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_route_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["policy", "demand_level", "route_id", "entrance", "exit", "movement"]
    for keys, group in df.groupby(group_cols, dropna=False):
        policy, demand_level, route_id, entrance, exit_id, movement = keys
        rows.append(
            {
                "policy": policy,
                "demand_level": demand_level,
                "route_id": route_id,
                "entrance": entrance,
                "exit": exit_id,
                "movement": movement,
                "runs": int(group.shape[0]),
                "mean_travel_time_s": summarize_values(group["mean_travel_time_s"].tolist())["mean"],
                "median_travel_time_s": summarize_values(group["median_travel_time_s"].tolist())["median"],
                "mean_waiting_time_s": summarize_values(group["mean_waiting_time_s"].tolist())["mean"],
                "mean_time_loss_s": summarize_values(group["mean_time_loss_s"].tolist())["mean"],
                "mean_speed_mps": summarize_values(group["mean_speed_mps"].tolist())["mean"],
                "vehicle_count": int(group["vehicle_count"].sum()),
            }
        )
    return pd.DataFrame(rows)


def aggregate_segment_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["policy", "demand_level", "entrance"]
    for keys, group in df.groupby(group_cols, dropna=False):
        policy, demand_level, entrance = keys
        rows.append(
            {
                "policy": policy,
                "demand_level": demand_level,
                "entrance": entrance,
                "route_count": int(group.shape[0]),
                "mean_travel_time_s": summarize_values(group["mean_travel_time_s"].tolist())["mean"],
                "median_travel_time_s": summarize_values(group["mean_travel_time_s"].tolist())["median"],
                "mean_waiting_time_s": summarize_values(group["mean_waiting_time_s"].tolist())["mean"],
                "mean_time_loss_s": summarize_values(group["mean_time_loss_s"].tolist())["mean"],
            }
        )
    return pd.DataFrame(rows)


def compare_policies(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    pivot = df.pivot_table(index="demand_level", columns="policy", values=f"{metric}_mean")
    rows: list[dict[str, Any]] = []
    for demand, row in pivot.iterrows():
        normal = row.get("normal")
        long_value = row.get("long")
        huang = row.get("huang")
        rows.append(
            {
                "demand_level": demand,
                f"{metric}_normal": normal,
                f"{metric}_long": long_value,
                f"{metric}_huang": huang,
                f"{metric}_huang_vs_normal_pct": percentage_difference(normal, huang) if pd.notna(normal) and pd.notna(huang) else None,
                f"{metric}_huang_vs_long_pct": percentage_difference(long_value, huang) if pd.notna(long_value) and pd.notna(huang) else None,
                f"{metric}_long_vs_normal_pct": percentage_difference(normal, long_value) if pd.notna(normal) and pd.notna(long_value) else None,
            }
        )
    return pd.DataFrame(rows)


def save_aggregated_outputs(results_root: str | Path) -> dict[str, str]:
    root = Path(results_root)
    processed = root / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    df = collect_run_summaries(root)
    route_df = collect_route_summaries(root)
    metrics_df = aggregate_policy_metrics(df)
    route_metrics_df = aggregate_route_metrics(route_df)
    segment_metrics_df = aggregate_segment_metrics(route_df)
    comparison_df = compare_policies(metrics_df, "mean_travel_time_s")

    summary_csv = processed / "aggregated_summary.csv"
    route_summary_csv = processed / "route_summary.csv"
    segment_summary_csv = processed / "segment_summary.csv"
    comparison_csv = processed / "policy_comparisons.csv"
    if not metrics_df.empty:
        metrics_df.to_csv(summary_csv, index=False)
    else:
        summary_csv.write_text("", encoding="utf-8")
    if not route_metrics_df.empty:
        route_metrics_df.to_csv(route_summary_csv, index=False)
    else:
        route_summary_csv.write_text("", encoding="utf-8")
    if not segment_metrics_df.empty:
        segment_metrics_df.to_csv(segment_summary_csv, index=False)
    else:
        segment_summary_csv.write_text("", encoding="utf-8")
    if not comparison_df.empty:
        comparison_df.to_csv(comparison_csv, index=False)
    else:
        comparison_csv.write_text("", encoding="utf-8")

    payload = {
        "runs": int(len(df)),
        "route_rows": int(len(route_df)),
        "aggregated_rows": int(len(metrics_df)),
        "route_summary_rows": int(len(route_metrics_df)),
        "segment_summary_rows": int(len(segment_metrics_df)),
        "comparisons_rows": int(len(comparison_df)),
        "summary_csv": str(summary_csv),
        "route_summary_csv": str(route_summary_csv),
        "segment_summary_csv": str(segment_summary_csv),
        "comparison_csv": str(comparison_csv),
    }
    (processed / "aggregated_manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
