from __future__ import annotations

import csv
import json
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from simulation.bootstrap import ensure_sumo_tools_on_path

ensure_sumo_tools_on_path()

from sumolib import net as sumo_net  # type: ignore  # noqa: E402


@dataclass(frozen=True)
class RoutePaths:
    root: Path
    generated_dir: Path
    summaries_dir: Path
    net_xml: Path
    metadata_json: Path


@dataclass(frozen=True)
class RouteSpec:
    normalization_mode: str
    demand_levels: dict[str, int]
    minor_demand_ratio: float
    canonical_entrances: dict[str, str]
    canonical_exits: dict[str, list[str]]
    raw_exit_weights: dict[str, list[float]]
    route_generation_horizon_seconds: int


def build_route_paths(root: str | Path) -> RoutePaths:
    root_path = Path(root)
    return RoutePaths(
        root=root_path,
        generated_dir=root_path / "routes" / "generated",
        summaries_dir=root_path / "routes" / "summaries",
        net_xml=root_path / "network" / "generated" / "city.net.xml",
        metadata_json=root_path / "routes" / "summaries" / "route_metadata.json",
    )


def load_route_spec(config: dict[str, Any]) -> RouteSpec:
    routes = config["routes"]
    return RouteSpec(
        normalization_mode=str(routes["normalization_mode"]),
        demand_levels={k: int(v) for k, v in routes["demand_levels"].items()},
        minor_demand_ratio=float(routes["minor_demand_ratio"]),
        canonical_entrances={k: str(v) for k, v in routes["canonical_entrances"].items()},
        canonical_exits={k: [str(item) for item in v] for k, v in routes["canonical_exits"].items()},
        raw_exit_weights={k: [float(item) for item in v] for k, v in routes["raw_exit_weights"].items()},
        route_generation_horizon_seconds=int(config["simulation"]["route_generation_horizon_seconds"]),
    )


def generate_route_artifacts(
    config: dict[str, Any],
    root: str | Path,
    demand_level: str | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    paths = build_route_paths(root)
    spec = load_route_spec(config)
    _ensure_directories(paths)

    levels = [demand_level] if demand_level else list(spec.demand_levels.keys())
    net = sumo_net.readNet(str(paths.net_xml))
    metadata = {
        "seed": seed,
        "route_generation_horizon_seconds": spec.route_generation_horizon_seconds,
        "normalization_mode": spec.normalization_mode,
        "levels": {},
        "mapping": {},
    }

    for level in levels:
        level_path = paths.generated_dir / f"{level}.rou.xml"
        level_summary = _generate_level(
            net=net,
            spec=spec,
            level=level,
            seed=seed,
            output_path=level_path,
            root=root,
        )
        summary_path = paths.summaries_dir / f"{level}_summary.csv"
        _write_summary_csv(summary_path, level_summary["summary_rows"])
        metadata["levels"][level] = {
            "route_file": str(level_path),
            "summary_csv": str(summary_path),
            "vehicles": level_summary["vehicle_count"],
            "routes": level_summary["route_count"],
        }
        metadata["mapping"][level] = level_summary["mapping"]

    _write_json(paths.metadata_json, metadata)
    _validate_routes(paths.net_xml, [paths.generated_dir / f"{level}.rou.xml" for level in levels])
    return metadata


def _ensure_directories(paths: RoutePaths) -> None:
    paths.generated_dir.mkdir(parents=True, exist_ok=True)
    paths.summaries_dir.mkdir(parents=True, exist_ok=True)


def _generate_level(
    *,
    net: Any,
    spec: RouteSpec,
    level: str,
    seed: int,
    output_path: Path,
    root: str | Path,
) -> dict[str, Any]:
    rng = random.Random(f"{seed}:{level}")
    entrance_counts = {
        "I": spec.demand_levels[level],
        "J": round(spec.demand_levels[level] * spec.minor_demand_ratio),
        "K": round(spec.demand_levels[level] * spec.minor_demand_ratio),
    }

    routes_by_entrance: dict[str, list[dict[str, Any]]] = {}
    summary_rows: list[dict[str, Any]] = []

    for entrance_name, origin_node in spec.canonical_entrances.items():
        origin_edge = _origin_edge(net, origin_node)
        destination_nodes = spec.canonical_exits[entrance_name]
        destination_edges = [_exit_edge(net, node_id) for node_id in destination_nodes]
        weights_raw = spec.raw_exit_weights[entrance_name]
        weights = _normalize_weights(weights_raw) if spec.normalization_mode == "normalize" else list(weights_raw)
        allocations = _allocate_counts(entrance_counts[entrance_name], weights)

        routes_by_entrance[entrance_name] = []
        for idx, (dest_node, dest_edge, weight_raw, weight_norm, count) in enumerate(
            zip(destination_nodes, destination_edges, weights_raw, weights, allocations),
            start=1,
        ):
            route_edges, route_length = _shortest_route(net, origin_edge, dest_edge)
            route_id = f"{level}_{entrance_name}{idx}"
            routes_by_entrance[entrance_name].append(
                {
                    "route_id": route_id,
                    "entrance": entrance_name,
                    "exit": str(idx),
                    "origin_edge": origin_edge.getID(),
                    "destination_edge": dest_edge.getID(),
                    "destination_node": dest_node,
                    "weight_raw": weight_raw,
                    "weight_normalized": weight_norm,
                    "vehicle_count": count,
                    "route_length_m": route_length,
                    "route_edges": [edge.getID() for edge in route_edges],
                }
            )
            summary_rows.append(
                {
                    "level": level,
                    "entrance": entrance_name,
                    "exit": idx,
                    "route_id": route_id,
                    "raw_weight": weight_raw,
                    "normalized_weight": weight_norm,
                    "vehicle_count": count,
                    "route_length_m": route_length,
                }
            )
    vehicles = _materialize_vehicles(routes_by_entrance, rng, spec.route_generation_horizon_seconds)
    type_id = f"passenger_{level}"
    _write_route_file(output_path, vehicles, type_id=type_id)
    return {
        "vehicle_count": len(vehicles),
        "route_count": sum(len(v) for v in routes_by_entrance.values()),
        "mapping": routes_by_entrance,
        "summary_rows": summary_rows,
    }


def _origin_edge(net: Any, node_id: str):
    node = net.getNode(node_id)
    outgoing = [edge for edge in node.getOutgoing() if not edge.getID().startswith(":")]
    if not outgoing:
        raise RuntimeError(f"No origin edge found for {node_id}")
    return outgoing[0]


def _exit_edge(net: Any, node_id: str):
    node = net.getNode(node_id)
    incoming = [edge for edge in node.getIncoming() if not edge.getID().startswith(":")]
    if not incoming:
        raise RuntimeError(f"No exit edge found for {node_id}")
    return incoming[0]


def _shortest_route(net: Any, origin_edge: Any, destination_edge: Any):
    result = net.getShortestPath(origin_edge, destination_edge)
    if not result:
        raise RuntimeError(f"No route from {origin_edge.getID()} to {destination_edge.getID()}")
    edges, cost = result
    return list(edges), float(cost)


def _normalize_weights(weights: list[float]) -> list[float]:
    total = sum(weights)
    if total <= 0:
        raise ValueError("Weights must sum to a positive number")
    return [weight / total for weight in weights]


def _allocate_counts(total: int, weights: list[float]) -> list[int]:
    if total < 0:
        raise ValueError("Total count must be non-negative")
    if not weights:
        return []
    raw = [total * weight for weight in weights]
    floored = [int(value) for value in raw]
    remainder = total - sum(floored)
    order = sorted(
        range(len(weights)),
        key=lambda idx: (raw[idx] - floored[idx], -idx),
        reverse=True,
    )
    for idx in order[:remainder]:
        floored[idx] += 1
    return floored


def _materialize_vehicles(
    routes_by_entrance: dict[str, list[dict[str, Any]]],
    rng: random.Random,
    horizon_seconds: int,
) -> list[dict[str, Any]]:
    vehicles: list[dict[str, Any]] = []
    for entrance, routes in routes_by_entrance.items():
        for route in routes:
            for idx in range(route["vehicle_count"]):
                depart = rng.uniform(0, horizon_seconds)
                vehicles.append(
                    {
                        "id": f"{route['route_id']}_{idx:05d}",
                        "route_id": route["route_id"],
                        "depart": depart,
                        "origin": entrance,
                        "exit": route["exit"],
                        "route_edges": route["route_edges"],
                    }
                )
    vehicles.sort(key=lambda item: (item["depart"], item["id"]))
    return vehicles


def _write_route_file(path: Path, vehicles: list[dict[str, Any]], *, type_id: str) -> None:
    root = ET.Element("routes")
    ET.SubElement(root, "vType", {"id": type_id, "accel": "2.6", "decel": "4.5", "length": "5.0"})
    routes_seen: dict[str, list[str]] = {}
    for vehicle in vehicles:
        route_id = vehicle["route_id"]
        routes_seen.setdefault(route_id, vehicle["route_edges"])
    for route_id, edges in routes_seen.items():
        ET.SubElement(root, "route", {"id": route_id, "edges": " ".join(edges)})
    for vehicle in vehicles:
        ET.SubElement(
            root,
            "vehicle",
            {
                "id": vehicle["id"],
                "type": type_id,
                "route": vehicle["route_id"],
                "depart": f"{vehicle['depart']:.2f}",
                "departLane": "best",
                "departSpeed": "max",
            },
        )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "level",
                "entrance",
                "exit",
                "route_id",
                "raw_weight",
                "normalized_weight",
                "vehicle_count",
                "route_length_m",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_routes(net_xml: Path, route_files: list[Path]) -> None:
    cmd = [
        "sumo",
        "-n",
        str(net_xml),
        "-r",
        ",".join(str(path) for path in route_files),
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
        "--time-to-teleport",
        "-1",
        "--quit-on-end",
        "true",
        "--end",
        "1",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            "Route validation run failed",
            {"stdout": proc.stdout, "stderr": proc.stderr, "cmd": cmd},
        )
