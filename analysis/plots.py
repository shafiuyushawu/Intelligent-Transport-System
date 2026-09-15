from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from analysis.aggregate import aggregate_route_metrics, aggregate_segment_metrics, aggregate_policy_metrics, collect_route_summaries, collect_run_summaries


POLICY_COLORS = {
    "normal": "#64748b",
    "long": "#f59e0b",
    "huang": "#16a34a",
}

POLICY_ORDER = ["normal", "long", "huang"]
DEMAND_ORDER = ["low", "medium", "heavy"]


def save_policy_comparison_plots(results_root: str | Path) -> dict[str, str]:
    root = Path(results_root)
    figures_dir = root / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    runs = collect_run_summaries(root)
    route_rows = collect_route_summaries(root)
    policy_metrics = aggregate_policy_metrics(runs)
    route_metrics = aggregate_route_metrics(route_rows)
    segment_metrics = aggregate_segment_metrics(route_rows)

    if policy_metrics.empty:
        return {}

    outputs: dict[str, str] = {}
    available_demands = [demand for demand in DEMAND_ORDER if demand in set(policy_metrics["demand_level"].dropna().tolist())]
    for demand in available_demands:
        outputs[f"{demand}_travel_time"] = _plot_metric_by_demand(
            policy_metrics,
            demand=demand,
            metric_col="mean_travel_time_s_mean",
            ylabel="Mean travel time (s)",
            output_path=figures_dir / f"{demand}_travel_time.png",
            title=f"{demand.title()} traffic: mean travel time",
        )

    outputs["overall_travel_time"] = _plot_overall_metric(
        runs,
        metric_col="mean_travel_time_s",
        ylabel="Mean travel time (s)",
        output_path=figures_dir / "overall_travel_time.png",
        title="Overall mean travel time",
    )
    outputs["waiting_time"] = _plot_metric_grid(
        policy_metrics,
        demands=available_demands,
        metric_col="mean_waiting_time_s_mean",
        ylabel="Mean waiting time (s)",
        output_path=figures_dir / "waiting_time.png",
        title="Waiting time by demand",
    )
    outputs["queue_length"] = _plot_metric_grid(
        policy_metrics,
        demands=available_demands,
        metric_col="mean_queue_length_m_mean",
        ylabel="Mean queue length (m)",
        output_path=figures_dir / "queue_length.png",
        title="Queue length by demand",
    )
    outputs["throughput"] = _plot_metric_grid(
        policy_metrics,
        demands=available_demands,
        metric_col="throughput_mean",
        ylabel="Throughput",
        output_path=figures_dir / "throughput.png",
        title="Throughput by demand",
    )
    outputs["congestion_propagation"] = _plot_congestion_propagation(
        policy_metrics,
        demands=available_demands,
        output_path=figures_dir / "congestion_propagation.png",
    )
    outputs["segment_comparison"] = _plot_segment_comparison(
        segment_metrics,
        demands=available_demands,
        output_path=figures_dir / "segment_comparison.png",
    )

    if not route_metrics.empty:
        outputs["route_overview"] = _plot_route_overview(
            route_metrics,
            output_path=figures_dir / "route_overview.png",
        )

    return outputs


def _plot_metric_by_demand(
    df: pd.DataFrame,
    *,
    demand: str,
    metric_col: str,
    ylabel: str,
    output_path: Path,
    title: str,
) -> str:
    subset = df[df["demand_level"] == demand]
    fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    _draw_policy_bars(
        ax,
        subset,
        metric_col=metric_col,
        ylabel=ylabel,
        title=title,
        x_order=POLICY_ORDER,
        show_error_bars=True,
    )
    fig.savefig(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)
    return str(output_path)


def _plot_metric_grid(
    df: pd.DataFrame,
    *,
    demands: list[str],
    metric_col: str,
    ylabel: str,
    output_path: Path,
    title: str,
) -> str:
    fig, axes = plt.subplots(1, len(demands), figsize=(max(6, 4.5 * len(demands)), 4.5), sharey=True, constrained_layout=True)
    if len(demands) == 1:
        axes = [axes]
    for ax, demand in zip(axes, demands, strict=False):
        subset = df[df["demand_level"] == demand]
        _draw_policy_bars(
            ax,
            subset,
            metric_col=metric_col,
            ylabel=ylabel,
            title=f"{demand.title()} traffic",
            x_order=POLICY_ORDER,
            show_error_bars=True,
        )
    fig.suptitle(title)
    fig.savefig(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)
    return str(output_path)


def _plot_overall_metric(
    runs: pd.DataFrame,
    *,
    metric_col: str,
    ylabel: str,
    output_path: Path,
    title: str,
) -> str:
    overall = runs.groupby("policy", dropna=False)[metric_col].mean().reindex(POLICY_ORDER)
    fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    bars = [float(value) if pd.notna(value) else 0.0 for value in overall.tolist()]
    ax.bar(range(len(POLICY_ORDER)), bars, color=[POLICY_COLORS[policy] for policy in POLICY_ORDER], width=0.6)
    ax.set_xticks(range(len(POLICY_ORDER)), ["Normal", "Long", "Huang"])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.savefig(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)
    return str(output_path)


def _plot_congestion_propagation(df: pd.DataFrame, *, demands: list[str], output_path: Path) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=False, constrained_layout=True)
    metrics = [
        ("vehicles_entering_zone_ab_mean", "Vehicles entering zone AB"),
        ("congestion_neighbouring_roads_mean", "Congestion on neighbouring roads"),
    ]
    for ax, (metric_col, ylabel) in zip(axes, metrics, strict=False):
        _draw_demand_policy_bars(
            ax,
            df,
            demands=demands,
            metric_col=metric_col,
            ylabel=ylabel,
            title=ylabel,
        )
    fig.suptitle("Congestion propagation")
    fig.savefig(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)
    return str(output_path)


def _plot_segment_comparison(df: pd.DataFrame, *, demands: list[str], output_path: Path) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True, constrained_layout=True)
    entrances = ["I", "J", "K"]
    for ax, entrance in zip(axes, entrances, strict=False):
        subset = df[df["entrance"] == entrance]
        _draw_demand_policy_bars(
            ax,
            subset,
            demands=demands,
            metric_col="mean_travel_time_s",
            ylabel="Mean travel time (s)",
            title=f"Entrance {entrance}",
        )
    fig.suptitle("I, J, and K segment comparisons")
    fig.savefig(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)
    return str(output_path)


def _plot_route_overview(df: pd.DataFrame, *, output_path: Path) -> str:
    top_routes = (
        df.sort_values(["demand_level", "policy", "route_id"])
        .groupby("route_id", dropna=False)["mean_travel_time_s"]
        .mean()
        .sort_values(ascending=False)
        .head(12)
        .index.tolist()
    )
    subset = df[df["route_id"].isin(top_routes)].copy()
    if subset.empty:
        return ""
    fig, ax = plt.subplots(figsize=(14, 5), constrained_layout=True)
    for policy in POLICY_ORDER:
        policy_rows = subset[subset["policy"] == policy]
        if policy_rows.empty:
            continue
        ordered = policy_rows.set_index("route_id").reindex(top_routes)
        ax.plot(top_routes, ordered["mean_travel_time_s"], marker="o", label=policy.title(), color=POLICY_COLORS[policy])
    ax.set_ylabel("Mean travel time (s)")
    ax.set_xlabel("Route")
    ax.set_title("Route overview")
    ax.legend(frameon=False)
    fig.autofmt_xdate(rotation=45)
    fig.savefig(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    plt.close(fig)
    return str(output_path)


def _draw_demand_policy_bars(
    ax: plt.Axes,
    df: pd.DataFrame,
    *,
    demands: list[str],
    metric_col: str,
    ylabel: str,
    title: str,
) -> None:
    width = 0.25
    positions = range(len(demands))
    offsets = [-width, 0.0, width]
    for offset, policy in zip(offsets, POLICY_ORDER, strict=False):
        values = []
        for demand in demands:
            row = df[(df["policy"] == policy) & (df["demand_level"] == demand)]
            values.append(float(row.iloc[0][metric_col]) if not row.empty else 0.0)
        ax.bar([index + offset for index in positions], values, width=width, label=policy.title(), color=POLICY_COLORS[policy])
    ax.set_xticks(list(positions), demands)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False)


def _draw_policy_bars(
    ax: plt.Axes,
    df: pd.DataFrame,
    *,
    metric_col: str,
    ylabel: str,
    title: str,
    x_order: list[str],
    show_error_bars: bool = False,
) -> None:
    values = []
    errors = []
    for policy in x_order:
        row = df[df["policy"] == policy]
        if row.empty:
            values.append(0.0)
            errors.append(0.0)
            continue
        values.append(float(row.iloc[0][metric_col]))
        if show_error_bars and f"{metric_col.replace('_mean', '')}_ci95_high" in row.columns:
            base = metric_col.replace("_mean", "")
            hi = float(row.iloc[0].get(f"{base}_ci95_high", 0.0))
            lo = float(row.iloc[0].get(f"{base}_ci95_low", 0.0))
            errors.append(max(0.0, hi - values[-1], values[-1] - lo))
        else:
            errors.append(0.0)
    positions = range(len(x_order))
    ax.bar(
        list(positions),
        values,
        yerr=errors if show_error_bars else None,
        color=[POLICY_COLORS[p] for p in x_order],
        capsize=4,
    )
    ax.set_xticks(list(positions), ["Normal", "Long", "Huang"])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.tick_params(axis="x", rotation=0)
