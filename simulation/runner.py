from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from typing import Any
from xml.etree import ElementTree as ET

from simulation.bootstrap import ensure_sumo_tools_on_path

ensure_sumo_tools_on_path()

import traci  # type: ignore  # noqa: E402
from sumolib import net as sumo_net  # type: ignore  # noqa: E402

from policies.base import PolicyAction, PolicyContext, RouteCatalog
from policies.huang import HuangPolicy
from policies.long_policy import LongPolicy
from policies.normal import NormalPolicy
from simulation.config import load_experiment_config
from simulation.congestion import CongestionSpec, generate_congestion_detectors, load_congestion_spec


POLICY_REGISTRY = {
    "normal": NormalPolicy,
    "long": LongPolicy,
    "huang": HuangPolicy,
}


def run_policy_simulation(
    config: dict[str, Any],
    root: str | Path,
    policy_name: str,
    demand_level: str,
    seed: int,
    *,
    gui: bool = False,
    route_file: str | Path | None = None,
    output_dir: str | Path | None = None,
    max_simulation_time: float | None = None,
    max_wall_clock_seconds: float | None = None,
    detector_output: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    paths = _build_paths(root_path, output_dir)
    paths["raw_dir"].mkdir(parents=True, exist_ok=True)
    paths["processed_dir"].mkdir(parents=True, exist_ok=True)
    paths["logs_dir"].mkdir(parents=True, exist_ok=True)

    policy = _build_policy(policy_name)
    route_catalog = RouteCatalog.from_files(paths["route_metadata_json"], demand_level)
    route_path = Path(route_file) if route_file else root_path / "routes" / "generated" / f"{demand_level}.rou.xml"
    if not route_path.exists():
        raise FileNotFoundError(route_path)

    congestion_spec = load_congestion_spec(config)
    detector_output_path = (
        Path(detector_output)
        if detector_output is not None
        else paths["raw_dir"] / f"{policy_name}_{demand_level}_{seed}_detectors.xml"
    )
    detector_metadata = generate_congestion_detectors(
        config,
        root_path,
        detector_output=str(detector_output_path),
    )
    network_metadata = json.loads(paths["network_metadata_json"].read_text(encoding="utf-8"))

    tripinfo_path = paths["raw_dir"] / f"{policy_name}_{demand_level}_{seed}_tripinfo.xml"
    interventions_path = paths["processed_dir"] / f"{policy_name}_{demand_level}_{seed}_interventions.csv"
    vehicle_csv_path = paths["processed_dir"] / f"{policy_name}_{demand_level}_{seed}_vehicles.csv"
    route_csv_path = paths["processed_dir"] / f"{policy_name}_{demand_level}_{seed}_routes.csv"
    diagnostics_csv_path = paths["raw_dir"] / f"{policy_name}_{demand_level}_{seed}_diagnostics.csv"
    summary_path = paths["processed_dir"] / f"{policy_name}_{demand_level}_{seed}_summary.json"
    config_snapshot_path = paths["processed_dir"] / f"{policy_name}_{demand_level}_{seed}_config.json"

    cmd = [
        shutil.which("sumo-gui" if gui else "sumo") or ("sumo-gui" if gui else "sumo"),
        "-n",
        str(paths["network_xml"]),
        "-r",
        str(route_path),
        "-a",
        ",".join([str(paths["signals_xml"]), str(detector_metadata["detectors_xml"])]),
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
        "--seed",
        str(seed),
        "--quit-on-end",
        "true",
    ]

    traci.start(cmd)
    net = sumo_net.readNet(str(paths["network_xml"]))
    incident_state = _initialize_congestion_state(net, congestion_spec)
    original_state = incident_state["original_state"]
    policy_actions: list[PolicyAction] = []
    diagnostics: list[dict[str, Any]] = []
    processed_vehicles: set[str] = set()
    rng = random.Random(seed)
    activated = False
    restored = False
    total_teleports = 0
    total_collisions = 0
    total_departed = 0
    total_arrived = 0
    simulation_limit_hit = False
    detector_ids = _detector_ids_from_file(Path(detector_metadata["detectors_xml"]))
    scheduled_vehicles = _count_scheduled_vehicles(route_path)
    start_wall_clock = time.monotonic()
    wall_clock_timeout_hit = False
    current_time = 0

    while traci.simulation.getMinExpectedNumber() > 0:
        current_time = int(traci.simulation.getTime())
        if max_simulation_time is not None and current_time >= max_simulation_time:
            simulation_limit_hit = True
            break
        if max_wall_clock_seconds is not None and (time.monotonic() - start_wall_clock) >= max_wall_clock_seconds:
            wall_clock_timeout_hit = True
            break
        if not activated and current_time >= congestion_spec.activation_seconds:
            _apply_congestion_activation(congestion_spec, incident_state)
            activated = True
        if activated and not restored and current_time >= congestion_spec.deactivation_seconds:
            _restore_congestion(original_state)
            restored = True

        traci.simulationStep()
        current_time = int(traci.simulation.getTime())
        departed = traci.simulation.getDepartedIDList()
        arrived = traci.simulation.getArrivedIDList()
        total_departed += len(departed)
        total_arrived += len(arrived)
        total_teleports += traci.simulation.getStartingTeleportNumber() + traci.simulation.getEndingTeleportNumber()
        total_collisions += len(traci.simulation.getCollisions())

        for vehicle_id in departed:
            if vehicle_id in processed_vehicles:
                continue
            processed_vehicles.add(vehicle_id)
            route_id = traci.vehicle.getRouteID(vehicle_id)
            if route_id not in route_catalog.routes:
                continue
            route = route_catalog.route(route_id)
            congestion_state = {
                "active": activated and not restored,
                "zone_id": congestion_spec.zone_id,
                "activation_seconds": congestion_spec.activation_seconds,
                "deactivation_seconds": congestion_spec.deactivation_seconds,
            }
            context = PolicyContext(
                simulation_time=current_time,
                congestion_state=congestion_state,
                network_metadata=network_metadata,
                vehicle_state={
                    "departed": total_departed,
                    "arrived": total_arrived,
                    "teleports": total_teleports,
                    "collisions": total_collisions,
                },
                route_state={
                    "route_id": route_id,
                    "entrance": route.entrance,
                    "exit": route.exit,
                    "movement": route.movement,
                },
                config=config,
            )
            if policy.should_rewrite(route, route_catalog, context):
                replacement_route_id = policy.replacement_route_id(route, route_catalog, context, rng)
                if replacement_route_id is None:
                    policy_actions.append(
                        PolicyAction(
                            time_s=current_time,
                            policy=policy.name,
                            vehicle_id=vehicle_id,
                            restriction=policy.restriction_label(route),
                            original_route=route_id,
                            replacement_route=None,
                            route_valid=False,
                            outcome="blocked_no_alternative",
                        )
                    )
                    continue
                replacement = route_catalog.route(replacement_route_id)
                traci.vehicle.setRoute(vehicle_id, list(replacement.route_edges))
                route_valid = bool(traci.vehicle.isRouteValid(vehicle_id))
                policy_actions.append(
                    PolicyAction(
                        time_s=current_time,
                        policy=policy.name,
                        vehicle_id=vehicle_id,
                        restriction=policy.restriction_label(route),
                        original_route=route_id,
                        replacement_route=replacement_route_id,
                        route_valid=route_valid,
                        outcome="replaced_valid" if route_valid else "replaced_invalid",
                    )
                )

        diagnostics.extend(
            _sample_detector_diagnostics(
                current_time=current_time,
                detector_ids=detector_ids,
                scenario=policy_name,
            )
        )

    if not restored:
        _restore_congestion(original_state)
    traci.close()

    tripinfo_rows = _parse_tripinfo(tripinfo_path)
    vehicle_route_map = _load_vehicle_route_map(route_path)
    vehicle_rows = _build_vehicle_rows(tripinfo_rows, vehicle_route_map, route_catalog)
    route_rows = _build_route_rows(vehicle_rows, route_catalog)
    summary = _summarize_tripinfo_rows(tripinfo_rows)
    summary.update(_summarize_diagnostic_rows(diagnostics))
    summary.update(
        {
            "policy": policy_name,
            "demand_level": demand_level,
            "seed": seed,
            "teleports": total_teleports,
            "collisions": total_collisions,
            "vehicles_departed": total_departed,
            "vehicles_arrived": total_arrived,
            "scheduled_vehicles": scheduled_vehicles,
            "unfinished_trips": max(0, scheduled_vehicles - total_arrived),
            "vehicles_entering_zone_ab": _count_zone_entries(route_catalog, route_path, congestion_spec),
            "congestion_neighbouring_roads": _count_neighbouring_routes(route_path, congestion_spec),
            "simulation_capped": simulation_limit_hit,
            "simulation_limit_configured": max_simulation_time is not None,
            "simulation_stop_time_s": int(current_time),
            "wall_clock_capped": wall_clock_timeout_hit,
            "wall_clock_limit_configured": max_wall_clock_seconds is not None,
            "wall_clock_timeout_hit": wall_clock_timeout_hit,
            "wall_clock_seconds_elapsed": round(time.monotonic() - start_wall_clock, 3),
        }
    )

    _write_csv(interventions_path, [asdict(action) for action in policy_actions], fieldnames=list(PolicyAction.__annotations__.keys()))
    _write_csv(
        vehicle_csv_path,
        vehicle_rows,
        fieldnames=[
            "vehicle_id",
            "route_id",
            "entrance",
            "exit",
            "movement",
            "duration",
            "waiting_time",
            "time_loss",
            "route_length",
            "avg_speed",
            "depart",
            "arrival",
        ],
    )
    _write_csv(
        route_csv_path,
        route_rows,
        fieldnames=[
            "route_id",
            "entrance",
            "exit",
            "movement",
            "vehicle_count",
            "mean_travel_time_s",
            "median_travel_time_s",
            "mean_waiting_time_s",
            "mean_time_loss_s",
            "mean_speed_mps",
            "route_length_m",
        ],
    )
    _write_csv(
        diagnostics_csv_path,
        diagnostics,
        fieldnames=["time_s", "scenario", "detector_id", "role", "mean_speed_mps", "vehicle_number", "queue_length_m"],
    )
    config_snapshot_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    summary_payload = {
        "summary": summary,
        "files": {
            "tripinfo": str(tripinfo_path),
            "interventions": str(interventions_path),
            "vehicle_csv": str(vehicle_csv_path),
            "route_csv": str(route_csv_path),
            "diagnostics_csv": str(diagnostics_csv_path),
            "detector_output": str(detector_output_path),
            "route_file": str(route_path),
            "config_snapshot": str(config_snapshot_path),
        },
        "policy_actions": [asdict(action) for action in policy_actions],
        "vehicle_rows": vehicle_rows,
        "route_rows": route_rows,
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2, sort_keys=True), encoding="utf-8")
    return summary_payload


def _build_paths(root: Path, output_dir: str | Path | None) -> dict[str, Any]:
    if output_dir is None:
        base_dir = root / "results"
    else:
        base_dir = Path(output_dir)
    return {
        "network_xml": root / "network" / "generated" / "city.net.xml",
        "signals_xml": root / "network" / "generated" / "city.tll.xml",
        "network_metadata_json": root / "network" / "metadata" / "city_metadata.json",
        "route_metadata_json": root / "routes" / "summaries" / "route_metadata.json",
        "raw_dir": base_dir / "raw",
        "processed_dir": base_dir / "processed",
        "logs_dir": base_dir / "logs",
    }


def _build_policy(policy_name: str):
    try:
        return POLICY_REGISTRY[policy_name]()
    except KeyError as exc:
        raise ValueError(f"Unknown policy {policy_name!r}") from exc


def _initialize_congestion_state(net: Any, spec: CongestionSpec) -> dict[str, Any]:
    affected_lane_map = _expand_affected_lane_map(net, spec)
    affected_lane_ids = [lane_id for lane_ids in affected_lane_map.values() for lane_id in lane_ids]
    original_lanes = {
        lane_id: {
            "speed": traci.lane.getMaxSpeed(lane_id),
            "disallowed": tuple(traci.lane.getDisallowed(lane_id)),
        }
        for lane_id in affected_lane_ids
    }
    original_edges = {edge_id: net.getEdge(edge_id).getSpeed() for edge_id in spec.affected_edges}
    return {
        "affected_lane_map": affected_lane_map,
        "original_state": {
            "lane_speeds": {lane_id: data["speed"] for lane_id, data in original_lanes.items()},
            "lane_disallowed": {lane_id: data["disallowed"] for lane_id, data in original_lanes.items()},
            "edge_speeds": original_edges,
        },
    }


def _apply_congestion_activation(spec: CongestionSpec, incident_state: dict[str, Any]) -> None:
    affected_lane_map = incident_state["affected_lane_map"]
    open_lane_index = 1 if 1 in spec.affected_lane_indices else spec.affected_lane_indices[0]
    for edge_id in spec.affected_edges:
        traci.edge.setMaxSpeed(edge_id, spec.reduced_speed_mps)
    for edge_id, lane_ids in affected_lane_map.items():
        for lane_index, lane_id in enumerate(lane_ids):
            traci.lane.setMaxSpeed(lane_id, spec.reduced_speed_mps)
            if lane_index != open_lane_index:
                traci.lane.setDisallowed(lane_id, ["passenger"])


def _restore_congestion(original_state: dict[str, Any]) -> None:
    for edge_id, speed in original_state["edge_speeds"].items():
        traci.edge.setMaxSpeed(edge_id, speed)
    for lane_id, speed in original_state["lane_speeds"].items():
        traci.lane.setMaxSpeed(lane_id, speed)
    for lane_id, disallowed in original_state["lane_disallowed"].items():
        traci.lane.setDisallowed(lane_id, list(disallowed))


def _expand_affected_lane_map(net: Any, spec: CongestionSpec) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for edge_id in spec.affected_edges:
        edge = net.getEdge(edge_id)
        mapping[edge_id] = [lane.getID() for lane in _selected_lanes(edge, spec.affected_lane_indices)]
    return mapping


def _selected_lanes(edge: Any, lane_indices: list[int]) -> list[Any]:
    lanes = list(edge.getLanes())
    return [lanes[index] for index in lane_indices if index < len(lanes)]


def _parse_tripinfo(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    rows: list[dict[str, Any]] = []
    for trip in root.findall("tripinfo"):
        rows.append(
            {
                "id": trip.attrib.get("id", ""),
                "duration": float(trip.attrib.get("duration", 0.0)),
                "waiting_time": float(trip.attrib.get("waitingTime", 0.0)),
                "time_loss": float(trip.attrib.get("timeLoss", 0.0)),
                "route_length": float(trip.attrib.get("routeLength", 0.0)),
                "arrival_time": float(trip.attrib.get("arrival", 0.0)),
            }
        )
    return rows


def _summarize_tripinfo_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "mean_travel_time_s": 0.0,
            "median_travel_time_s": 0.0,
            "mean_delay_s": 0.0,
            "mean_waiting_time_s": 0.0,
            "mean_time_loss_s": 0.0,
            "mean_speed_mps": 0.0,
            "completed_trips": 0,
        "unfinished_trips": 0,
        }
    durations = [row["duration"] for row in rows]
    waiting = [row["waiting_time"] for row in rows]
    time_loss = [row["time_loss"] for row in rows]
    speeds = [row["route_length"] / row["duration"] if row["duration"] > 0 else 0.0 for row in rows]
    return {
        "mean_travel_time_s": mean(durations),
        "median_travel_time_s": median(durations),
        "mean_delay_s": mean(time_loss),
        "mean_waiting_time_s": mean(waiting),
        "mean_time_loss_s": mean(time_loss),
        "mean_speed_mps": mean(speeds),
        "completed_trips": len(rows),
        "unfinished_trips": 0,
    }


def _load_vehicle_route_map(route_path: Path) -> dict[str, str]:
    root = ET.parse(route_path).getroot()
    mapping: dict[str, str] = {}
    for vehicle in root.findall("vehicle"):
        vehicle_id = vehicle.attrib.get("id", "")
        route_id = vehicle.attrib.get("route", "")
        if vehicle_id and route_id:
            mapping[vehicle_id] = route_id
    return mapping


def _build_vehicle_rows(
    tripinfo_rows: list[dict[str, Any]],
    vehicle_route_map: dict[str, str],
    route_catalog: RouteCatalog,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trip in tripinfo_rows:
        vehicle_id = str(trip["id"])
        route_id = vehicle_route_map.get(vehicle_id, _infer_route_id(vehicle_id))
        route = route_catalog.routes.get(route_id)
        rows.append(
            {
                "vehicle_id": vehicle_id,
                "route_id": route_id,
                "entrance": route.entrance if route else "",
                "exit": route.exit if route else "",
                "movement": route.movement if route else "",
                "duration": trip["duration"],
                "waiting_time": trip["waiting_time"],
                "time_loss": trip["time_loss"],
                "route_length": trip["route_length"],
                "avg_speed": trip["route_length"] / trip["duration"] if trip["duration"] > 0 else 0.0,
                "depart": trip.get("depart", 0.0),
                "arrival": trip.get("arrival_time", 0.0),
            }
        )
    return rows


def _build_route_rows(vehicle_rows: list[dict[str, Any]], route_catalog: RouteCatalog) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in vehicle_rows:
        grouped.setdefault(row["route_id"], []).append(row)
    rows: list[dict[str, Any]] = []
    for route_id, items in grouped.items():
        route = route_catalog.routes.get(route_id)
        durations = [float(item["duration"]) for item in items]
        waiting = [float(item["waiting_time"]) for item in items]
        time_loss = [float(item["time_loss"]) for item in items]
        route_length = float(items[0]["route_length"]) if items else 0.0
        rows.append(
            {
                "route_id": route_id,
                "entrance": route.entrance if route else "",
                "exit": route.exit if route else "",
                "movement": route.movement if route else "",
                "vehicle_count": len(items),
                "mean_travel_time_s": mean(durations) if durations else 0.0,
                "median_travel_time_s": median(durations) if durations else 0.0,
                "mean_waiting_time_s": mean(waiting) if waiting else 0.0,
                "mean_time_loss_s": mean(time_loss) if time_loss else 0.0,
                "mean_speed_mps": mean(
                    float(item["route_length"]) / float(item["duration"]) if float(item["duration"]) > 0 else 0.0
                    for item in items
                )
                if items
                else 0.0,
                "route_length_m": route_length,
            }
        )
    rows.sort(key=lambda item: item["route_id"])
    return rows


def _infer_route_id(vehicle_id: str) -> str:
    if "_" not in vehicle_id:
        return vehicle_id
    return vehicle_id.rsplit("_", 1)[0]


def _summarize_diagnostic_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "mean_queue_length_m": 0.0,
            "max_queue_length_m": 0.0,
            "mean_detector_speed_mps": 0.0,
        }
    observed_speeds = [
        float(item["mean_speed_mps"])
        for item in rows
        if float(item["mean_speed_mps"]) >= 0.0
    ]
    return {
        "mean_queue_length_m": mean(float(item["queue_length_m"]) for item in rows),
        "max_queue_length_m": max(float(item["queue_length_m"]) for item in rows),
        # SUMO reports -1 when a detector has no vehicle in the current step;
        # that sentinel is not a physical speed and must not enter the mean.
        "mean_detector_speed_mps": mean(observed_speeds) if observed_speeds else 0.0,
    }


def _detector_ids_from_file(detectors_xml: Path) -> list[str]:
    root = ET.parse(detectors_xml).getroot()
    return [node.attrib["id"] for node in root.findall("laneAreaDetector")]


def _detector_role(detector_id: str) -> str:
    parts = detector_id.split("_")
    if len(parts) < 3:
        return "unknown"
    return parts[2]


def _sample_detector_diagnostics(*, current_time: int, detector_ids: list[str], scenario: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for detector_id in detector_ids:
        records.append(
            {
                "time_s": current_time,
                "scenario": scenario,
                "detector_id": detector_id,
                "role": _detector_role(detector_id),
                "mean_speed_mps": traci.lanearea.getLastStepMeanSpeed(detector_id),
                "vehicle_number": traci.lanearea.getLastStepVehicleNumber(detector_id),
                "queue_length_m": traci.lanearea.getJamLengthMeters(detector_id),
            }
        )
    return records


def _count_zone_entries(catalog: RouteCatalog, route_path: Path, spec: CongestionSpec) -> int:
    root = ET.parse(route_path).getroot()
    route_edges: dict[str, list[str]] = {
        route.attrib["id"]: route.attrib.get("edges", "").split()
        for route in root.findall("route")
    }
    count = 0
    for vehicle in root.findall("vehicle"):
        route_id = vehicle.attrib.get("route", "")
        edges = route_edges.get(route_id, [])
        if any(edge in spec.affected_edges for edge in edges):
            count += 1
    return count


def _count_scheduled_vehicles(route_path: Path) -> int:
    root = ET.parse(route_path).getroot()
    return len(root.findall("vehicle"))


def _count_neighbouring_routes(route_path: Path, spec: CongestionSpec) -> int:
    root = ET.parse(route_path).getroot()
    route_edges: dict[str, list[str]] = {
        route.attrib["id"]: route.attrib.get("edges", "").split()
        for route in root.findall("route")
    }
    neighbours = set(spec.detector_edges.get("alternative_north", [])) | set(
        spec.detector_edges.get("alternative_south", [])
    )
    count = 0
    for vehicle in root.findall("vehicle"):
        route_id = vehicle.attrib.get("route", "")
        edges = route_edges.get(route_id, [])
        if any(edge in neighbours for edge in edges):
            count += 1
    return count


def _write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a single SUMO policy simulation.")
    parser.add_argument("--policy", choices=sorted(POLICY_REGISTRY), required=True)
    parser.add_argument("--demand", choices=["low", "medium", "heavy"], required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--gui", default="false")
    parser.add_argument("--root", default=".")
    parser.add_argument("--route-file", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--config", default="config/experiment.yaml")
    parser.add_argument("--max-simulation-time", type=float, default=None)
    parser.add_argument("--max-wall-clock-seconds", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_experiment_config(args.config).data
    result = run_policy_simulation(
        config,
        args.root,
        args.policy,
        args.demand,
        args.seed,
        gui=str(args.gui).lower() in {"1", "true", "yes", "on"},
        route_file=args.route_file,
        output_dir=args.output_dir,
        max_simulation_time=args.max_simulation_time,
        max_wall_clock_seconds=args.max_wall_clock_seconds,
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
