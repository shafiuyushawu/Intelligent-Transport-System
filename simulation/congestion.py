from __future__ import annotations

import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from simulation.bootstrap import ensure_sumo_tools_on_path

ensure_sumo_tools_on_path()

import traci  # type: ignore  # noqa: E402
from sumolib import net as sumo_net  # type: ignore  # noqa: E402


@dataclass(frozen=True)
class CongestionSpec:
    zone_id: str
    warmup_seconds: int
    activation_seconds: int
    deactivation_seconds: int
    incident_duration_seconds: int
    reduced_speed_kph: float
    affected_edges: list[str]
    affected_lane_indices: list[int]
    detector_length_m: float
    detector_edges: dict[str, list[str]]

    @property
    def reduced_speed_mps(self) -> float:
        return self.reduced_speed_kph / 3.6


@dataclass(frozen=True)
class CongestionPaths:
    root: Path
    net_xml: Path
    signals_xml: Path
    detectors_xml: Path
    raw_dir: Path
    figures_dir: Path
    metadata_dir: Path


def build_congestion_paths(root: str | Path) -> CongestionPaths:
    root_path = Path(root)
    return CongestionPaths(
        root=root_path,
        net_xml=root_path / "network" / "generated" / "city.net.xml",
        signals_xml=root_path / "network" / "generated" / "city.tll.xml",
        detectors_xml=root_path / "network" / "generated" / "zone_ab_detectors.add.xml",
        raw_dir=root_path / "results" / "raw",
        figures_dir=root_path / "results" / "figures",
        metadata_dir=root_path / "results" / "processed",
    )


def load_congestion_spec(config: dict[str, Any]) -> CongestionSpec:
    congestion = config["congestion"]
    activation_seconds = int(congestion["activation_seconds"])
    deactivation_seconds = int(congestion["deactivation_seconds"])
    incident_duration_seconds = int(congestion["incident_duration_seconds"])
    if deactivation_seconds - activation_seconds != incident_duration_seconds:
        raise ValueError(
            "Congestion incident_duration_seconds must equal deactivation_seconds - activation_seconds"
        )
    return CongestionSpec(
        zone_id=str(congestion["zone_id"]),
        warmup_seconds=int(congestion["warmup_seconds"]),
        activation_seconds=activation_seconds,
        deactivation_seconds=deactivation_seconds,
        incident_duration_seconds=incident_duration_seconds,
        reduced_speed_kph=float(congestion["reduced_speed_kph"]),
        affected_edges=[str(item) for item in congestion["affected_edges"]],
        affected_lane_indices=[int(item) for item in congestion["affected_lane_indices"]],
        detector_length_m=float(congestion["detector_length_m"]),
        detector_edges={k: [str(item) for item in v] for k, v in congestion["detector_edges"].items()},
    )


def generate_congestion_detectors(
    config: dict[str, Any],
    root: str | Path,
    *,
    detector_output: str = "NUL",
) -> dict[str, Any]:
    paths = build_congestion_paths(root)
    spec = load_congestion_spec(config)
    net = sumo_net.readNet(str(paths.net_xml))
    paths.detectors_xml.parent.mkdir(parents=True, exist_ok=True)
    paths.metadata_dir.mkdir(parents=True, exist_ok=True)

    root_xml = ET.Element("additional")
    detector_rows: list[dict[str, Any]] = []
    for role, edge_ids in spec.detector_edges.items():
        for edge_id in edge_ids:
            edge = net.getEdge(edge_id)
            for lane in _selected_lanes(edge, spec.affected_lane_indices):
                detector_id = f"{spec.zone_id}_{role}_{lane.getID()}"
                lane_length = lane.getLength()
                detector_length = min(spec.detector_length_m, lane_length)
                pos = max(0.0, lane_length - detector_length)
                ET.SubElement(
                    root_xml,
                    "laneAreaDetector",
                    {
                        "id": detector_id,
                        "lane": lane.getID(),
                        "pos": f"{pos:.2f}",
                        "length": f"{detector_length:.2f}",
                        "freq": "1",
                        "file": detector_output,
                    },
                )
                detector_rows.append(
                    {
                        "id": detector_id,
                        "role": role,
                        "edge_id": edge_id,
                        "lane_id": lane.getID(),
                        "lane_length_m": lane_length,
                        "detector_length_m": detector_length,
                        "pos_m": pos,
                    }
                )
    tree = ET.ElementTree(root_xml)
    ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    tree.write(paths.detectors_xml, encoding="utf-8", xml_declaration=True)
    metadata = {
        "zone_id": spec.zone_id,
        "detectors_xml": str(paths.detectors_xml),
        "detectors": detector_rows,
    }
    (paths.metadata_dir / "zone_ab_detectors.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def run_congestion_comparison(
    config: dict[str, Any],
    root: str | Path,
    route_file: str | Path,
    output_prefix: str = "zone_ab",
) -> dict[str, Any]:
    paths = build_congestion_paths(root)
    spec = load_congestion_spec(config)
    detectors = generate_congestion_detectors(config, root)
    paths.raw_dir.mkdir(parents=True, exist_ok=True)
    paths.figures_dir.mkdir(parents=True, exist_ok=True)

    baseline = _run_single_scenario(
        paths=paths,
        spec=spec,
        route_file=Path(route_file),
        detectors_xml=Path(detectors["detectors_xml"]),
        label="baseline",
        incident=False,
        output_prefix=output_prefix,
    )
    congested = _run_single_scenario(
        paths=paths,
        spec=spec,
        route_file=Path(route_file),
        detectors_xml=Path(detectors["detectors_xml"]),
        label="incident",
        incident=True,
        output_prefix=output_prefix,
    )
    plot_paths = _plot_comparison(baseline, congested, paths.figures_dir / f"{output_prefix}_comparison")
    comparison = {
        "baseline": baseline,
        "incident": congested,
        "plots": plot_paths,
        "improvements": {
            "mean_speed_delta": congested["summary"]["mean_speed_mps"] - baseline["summary"]["mean_speed_mps"],
            "waiting_time_delta": congested["summary"]["mean_waiting_time_s"] - baseline["summary"]["mean_waiting_time_s"],
            "queue_length_delta": congested["summary"]["mean_queue_length_m"] - baseline["summary"]["mean_queue_length_m"],
            "travel_time_delta": congested["summary"]["mean_travel_time_s"] - baseline["summary"]["mean_travel_time_s"],
        },
    }
    (paths.raw_dir / f"{output_prefix}_comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return comparison


def _selected_lanes(edge: Any, lane_indices: list[int]) -> list[Any]:
    lanes = list(edge.getLanes())
    if not lanes:
        return []
    if not lane_indices:
        return lanes
    return [lanes[index] for index in lane_indices if index < len(lanes)]


def _run_single_scenario(
    *,
    paths: CongestionPaths,
    spec: CongestionSpec,
    route_file: Path,
    detectors_xml: Path,
    label: str,
    incident: bool,
    output_prefix: str,
) -> dict[str, Any]:
    tripinfo_path = paths.raw_dir / f"{output_prefix}_{label}_tripinfo.xml"
    step_csv_path = paths.raw_dir / f"{output_prefix}_{label}_diagnostics.csv"
    cmd = [
        shutil.which("sumo") or "sumo",
        "-n",
        str(paths.net_xml),
        "-r",
        str(route_file),
        "-a",
        f"{paths.signals_xml},{detectors_xml}",
        "--tripinfo-output",
        str(tripinfo_path),
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--no-warnings",
        "true",
        "--time-to-teleport",
        "-1",
        "--quit-on-end",
        "true",
    ]
    traci.start(cmd)
    net = sumo_net.readNet(str(paths.net_xml))
    affected_edge_ids = list(spec.affected_edges)
    affected_lane_map = _expand_affected_lane_map(net, spec)
    affected_lane_ids = [lane_id for lane_ids in affected_lane_map.values() for lane_id in lane_ids]
    original_speeds: dict[str, float] = {}
    for lane_id in affected_lane_ids:
        original_speeds[lane_id] = traci.lane.getMaxSpeed(lane_id)
    original_disallowed: dict[str, tuple[str, ...]] = {}
    for lane_id in affected_lane_ids:
        original_disallowed[lane_id] = tuple(traci.lane.getDisallowed(lane_id))
    original_edge_speeds: dict[str, float] = {}
    for edge_id in affected_edge_ids:
        original_edge_speeds[edge_id] = net.getEdge(edge_id).getSpeed()

    detector_ids = _detector_ids_from_file(detectors_xml)
    records: list[dict[str, Any]] = []
    open_lane_index = 1 if 1 in spec.affected_lane_indices else spec.affected_lane_indices[0]
    while traci.simulation.getMinExpectedNumber() > 0:
        current_time = int(traci.simulation.getTime())
        if incident and current_time == spec.activation_seconds:
            for edge_id in affected_edge_ids:
                traci.edge.setMaxSpeed(edge_id, spec.reduced_speed_mps)
            for edge_id, lane_ids in affected_lane_map.items():
                for lane_index, lane_id in enumerate(lane_ids):
                    traci.lane.setMaxSpeed(lane_id, spec.reduced_speed_mps)
                    if lane_index != open_lane_index:
                        traci.lane.setDisallowed(lane_id, ["passenger"])
        if incident and current_time == spec.deactivation_seconds:
            for edge_id, speed in original_edge_speeds.items():
                traci.edge.setMaxSpeed(edge_id, speed)
            for lane_id, speed in original_speeds.items():
                traci.lane.setMaxSpeed(lane_id, speed)
            for lane_id, disallowed in original_disallowed.items():
                traci.lane.setDisallowed(lane_id, list(disallowed))
        traci.simulationStep()
        for detector_id in detector_ids:
            records.append(
                {
                    "time_s": traci.simulation.getTime(),
                    "scenario": label,
                    "detector_id": detector_id,
                    "role": _detector_role(detector_id),
                    "mean_speed_mps": traci.lanearea.getLastStepMeanSpeed(detector_id),
                    "vehicle_number": traci.lanearea.getLastStepVehicleNumber(detector_id),
                    "queue_length_m": traci.lanearea.getJamLengthMeters(detector_id),
                }
            )
    traci.close()
    _write_csv(step_csv_path, records)
    summary = _summarize_tripinfo(tripinfo_path)
    diag_summary = _summarize_diagnostics(records)
    summary.update(diag_summary)
    summary["tripinfo_path"] = str(tripinfo_path)
    summary["diagnostic_csv_path"] = str(step_csv_path)
    summary["scenario"] = label
    return {
        "summary": summary,
        "records": records,
    }


def _expand_affected_lanes(net: Any, spec: CongestionSpec) -> list[str]:
    lane_ids: list[str] = []
    for edge_id in spec.affected_edges:
        edge = net.getEdge(edge_id)
        for lane in _selected_lanes(edge, spec.affected_lane_indices):
            lane_ids.append(lane.getID())
    return lane_ids


def _expand_affected_lane_map(net: Any, spec: CongestionSpec) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for edge_id in spec.affected_edges:
        edge = net.getEdge(edge_id)
        mapping[edge_id] = [lane.getID() for lane in _selected_lanes(edge, spec.affected_lane_indices)]
    return mapping


def _detector_ids_from_file(detectors_xml: Path) -> list[str]:
    root = ET.parse(detectors_xml).getroot()
    return [node.attrib["id"] for node in root.findall("laneAreaDetector")]


def _detector_role(detector_id: str) -> str:
    parts = detector_id.split("_")
    if len(parts) < 3:
        return "unknown"
    return parts[2]


def _summarize_tripinfo(tripinfo_path: Path) -> dict[str, Any]:
    root = ET.parse(tripinfo_path).getroot()
    trips = []
    for trip in root.findall("tripinfo"):
        duration = float(trip.attrib.get("duration", 0.0))
        waiting = float(trip.attrib.get("waitingTime", 0.0))
        time_loss = float(trip.attrib.get("timeLoss", 0.0))
        route_length = float(trip.attrib.get("routeLength", 0.0))
        travel_time = duration
        avg_speed = route_length / duration if duration > 0 else 0.0
        trips.append(
            {
                "id": trip.attrib["id"],
                "duration": duration,
                "waiting_time": waiting,
                "time_loss": time_loss,
                "route_length": route_length,
                "avg_speed": avg_speed,
            }
        )
    if not trips:
        return {
            "mean_travel_time_s": 0.0,
            "mean_waiting_time_s": 0.0,
            "mean_time_loss_s": 0.0,
            "mean_speed_mps": 0.0,
            "throughput": 0,
            "completed_trips": 0,
            "unfinished_trips": 0,
            "teleports": 0,
        }
    return {
        "mean_travel_time_s": mean(trip["duration"] for trip in trips),
        "mean_waiting_time_s": mean(trip["waiting_time"] for trip in trips),
        "mean_time_loss_s": mean(trip["time_loss"] for trip in trips),
        "mean_speed_mps": mean(trip["avg_speed"] for trip in trips),
        "throughput": len(trips),
        "completed_trips": len(trips),
        "unfinished_trips": 0,
        "teleports": 0,
    }


def _summarize_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "mean_queue_length_m": 0.0,
            "max_queue_length_m": 0.0,
            "mean_detector_speed_mps": 0.0,
        }
    return {
        "mean_queue_length_m": mean(item["queue_length_m"] for item in records),
        "max_queue_length_m": max(item["queue_length_m"] for item in records),
        "mean_detector_speed_mps": mean(item["mean_speed_mps"] for item in records),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _plot_comparison(
    baseline: dict[str, Any],
    congested: dict[str, Any],
    output_prefix: Path,
) -> dict[str, str]:
    baseline_records = baseline["records"]
    congested_records = congested["records"]
    baseline_path = output_prefix.with_suffix(".png")
    baseline_pdf = output_prefix.with_suffix(".pdf")

    def aggregate(records: list[dict[str, Any]], key: str) -> dict[str, float]:
        by_role: dict[str, list[float]] = {}
        for row in records:
            by_role.setdefault(row["role"], []).append(float(row[key]))
        return {role: mean(values) for role, values in by_role.items() if values}

    roles = sorted(set(row["role"] for row in baseline_records) | set(row["role"] for row in congested_records))
    speed_baseline = aggregate(baseline_records, "mean_speed_mps")
    speed_congested = aggregate(congested_records, "mean_speed_mps")
    queue_baseline = aggregate(baseline_records, "queue_length_m")
    queue_congested = aggregate(congested_records, "queue_length_m")

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), constrained_layout=True)
    x = range(len(roles))
    axes[0].bar([i - 0.15 for i in x], [speed_baseline.get(role, 0.0) for role in roles], width=0.3, label="baseline")
    axes[0].bar([i + 0.15 for i in x], [speed_congested.get(role, 0.0) for role in roles], width=0.3, label="incident")
    axes[0].set_xticks(list(x), roles, rotation=20)
    axes[0].set_ylabel("Mean speed (m/s)")
    axes[0].legend()

    axes[1].bar([i - 0.15 for i in x], [queue_baseline.get(role, 0.0) for role in roles], width=0.3, label="baseline")
    axes[1].bar([i + 0.15 for i in x], [queue_congested.get(role, 0.0) for role in roles], width=0.3, label="incident")
    axes[1].set_xticks(list(x), roles, rotation=20)
    axes[1].set_ylabel("Mean queue length (m)")
    axes[1].legend()

    fig.savefig(baseline_path)
    fig.savefig(baseline_pdf)
    plt.close(fig)
    return {"png": str(baseline_path), "pdf": str(baseline_pdf)}
