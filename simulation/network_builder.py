from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from simulation.bootstrap import ensure_sumo_tools_on_path

ensure_sumo_tools_on_path()

from sumolib import net as sumo_net  # type: ignore  # noqa: E402


@dataclass(frozen=True)
class NetworkPaths:
    root: Path
    source_dir: Path
    generated_dir: Path
    metadata_dir: Path
    nodes_xml: Path
    edges_xml: Path
    net_xml: Path
    metadata_json: Path


@dataclass(frozen=True)
class GridSpec:
    grid_size: int
    block_spacing_x_m: float
    block_spacing_y_m: float
    west_east_stub_m: float
    north_south_stub_m: float
    main_lanes: int
    minor_lanes: int
    main_speed_kph: float
    minor_speed_kph: float

    @property
    def center_index(self) -> int:
        return self.grid_size // 2

    @property
    def main_speed_mps(self) -> float:
        return self.main_speed_kph / 3.6

    @property
    def minor_speed_mps(self) -> float:
        return self.minor_speed_kph / 3.6


def build_paths(root: str | Path) -> NetworkPaths:
    root_path = Path(root)
    source_dir = root_path / "network" / "source"
    generated_dir = root_path / "network" / "generated"
    metadata_dir = root_path / "network" / "metadata"
    return NetworkPaths(
        root=root_path,
        source_dir=source_dir,
        generated_dir=generated_dir,
        metadata_dir=metadata_dir,
        nodes_xml=source_dir / "city.nod.xml",
        edges_xml=source_dir / "city.edg.xml",
        net_xml=generated_dir / "city.net.xml",
        metadata_json=metadata_dir / "city_metadata.json",
    )


def load_grid_spec(config: dict[str, Any]) -> GridSpec:
    network = config["network"]
    speed_limits = network["speed_limits_kph"]
    return GridSpec(
        grid_size=int(network["grid_size"]),
        block_spacing_x_m=float(network["block_spacing_m"]["horizontal"]),
        block_spacing_y_m=float(network["block_spacing_m"]["vertical"]),
        west_east_stub_m=float(network["boundary_stub_m"]["horizontal"]),
        north_south_stub_m=float(network["boundary_stub_m"]["vertical"]),
        main_lanes=int(network["lane_counts"]["main"]),
        minor_lanes=int(network["lane_counts"]["minor"]),
        main_speed_kph=float(speed_limits["main"]),
        minor_speed_kph=float(speed_limits["minor"]),
    )


def generate_network_artifacts(config: dict[str, Any], root: str | Path) -> dict[str, Any]:
    paths = build_paths(root)
    spec = load_grid_spec(config)
    _ensure_directories(paths)

    nodes = _build_nodes(spec)
    edges = _build_edges(spec)
    _write_plain_nodes(paths.nodes_xml, nodes)
    _write_plain_edges(paths.edges_xml, edges)
    _compile_net(paths)

    metadata = _build_metadata(spec, nodes, edges, paths)
    _write_json(paths.metadata_json, metadata)
    _validate_connectivity(paths.net_xml, metadata)
    return metadata


def _ensure_directories(paths: NetworkPaths) -> None:
    for directory in [paths.source_dir, paths.generated_dir, paths.metadata_dir]:
        directory.mkdir(parents=True, exist_ok=True)


def _build_nodes(spec: GridSpec) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for row in range(spec.grid_size):
        for col in range(spec.grid_size):
            node_id = f"r{row}c{col}"
            nodes.append(
                {
                    "id": node_id,
                    "x": col * spec.block_spacing_x_m,
                    "y": row * spec.block_spacing_y_m,
                    "type": "traffic_light",
                    "kind": "intersection",
                    "row": row,
                    "col": col,
                    "intersection_type": _intersection_type(spec, row, col),
                }
            )

    for row in range(spec.grid_size):
        nodes.append(
            {
                "id": f"west_r{row}",
                "x": -spec.west_east_stub_m,
                "y": row * spec.block_spacing_y_m,
                "type": "priority",
                "kind": "boundary",
            }
        )
        nodes.append(
            {
                "id": f"east_r{row}",
                "x": (spec.grid_size - 1) * spec.block_spacing_x_m + spec.west_east_stub_m,
                "y": row * spec.block_spacing_y_m,
                "type": "priority",
                "kind": "boundary",
            }
        )

    for col in range(spec.grid_size):
        nodes.append(
            {
                "id": f"south_c{col}",
                "x": col * spec.block_spacing_x_m,
                "y": -spec.north_south_stub_m,
                "type": "priority",
                "kind": "boundary",
            }
        )
        nodes.append(
            {
                "id": f"north_c{col}",
                "x": col * spec.block_spacing_x_m,
                "y": (spec.grid_size - 1) * spec.block_spacing_y_m + spec.north_south_stub_m,
                "type": "priority",
                "kind": "boundary",
            }
        )
    return nodes


def _build_edges(spec: GridSpec) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for row in range(spec.grid_size):
        for col in range(spec.grid_size - 1):
            road_class = "main" if row == spec.center_index else "minor"
            lanes = spec.main_lanes if road_class == "main" else spec.minor_lanes
            speed = spec.main_speed_mps if road_class == "main" else spec.minor_speed_mps
            left = f"r{row}c{col}"
            right = f"r{row}c{col + 1}"
            _add_bidirectional_edge_pair(
                edges,
                left,
                right,
                road_class=road_class,
                lanes=lanes,
                speed=speed,
                length=spec.block_spacing_x_m,
                orientation="horizontal",
            )

    for col in range(spec.grid_size):
        for row in range(spec.grid_size - 1):
            road_class = "main" if col == spec.center_index else "minor"
            lanes = spec.main_lanes if road_class == "main" else spec.minor_lanes
            speed = spec.main_speed_mps if road_class == "main" else spec.minor_speed_mps
            south = f"r{row}c{col}"
            north = f"r{row + 1}c{col}"
            _add_bidirectional_edge_pair(
                edges,
                south,
                north,
                road_class=road_class,
                lanes=lanes,
                speed=speed,
                length=spec.block_spacing_y_m,
                orientation="vertical",
            )

    for row in range(spec.grid_size):
        road_class = "main" if row == spec.center_index else "minor"
        lanes = spec.main_lanes if road_class == "main" else spec.minor_lanes
        speed = spec.main_speed_mps if road_class == "main" else spec.minor_speed_mps
        _add_bidirectional_edge_pair(
            edges,
            f"west_r{row}",
            f"r{row}c0",
            road_class=road_class,
            lanes=lanes,
            speed=speed,
            length=spec.west_east_stub_m,
            orientation="horizontal",
            boundary=True,
        )
        _add_bidirectional_edge_pair(
            edges,
            f"r{row}c{spec.grid_size - 1}",
            f"east_r{row}",
            road_class=road_class,
            lanes=lanes,
            speed=speed,
            length=spec.west_east_stub_m,
            orientation="horizontal",
            boundary=True,
        )

    for col in range(spec.grid_size):
        road_class = "main" if col == spec.center_index else "minor"
        lanes = spec.main_lanes if road_class == "main" else spec.minor_lanes
        speed = spec.main_speed_mps if road_class == "main" else spec.minor_speed_mps
        _add_bidirectional_edge_pair(
            edges,
            f"south_c{col}",
            f"r0c{col}",
            road_class=road_class,
            lanes=lanes,
            speed=speed,
            length=spec.north_south_stub_m,
            orientation="vertical",
            boundary=True,
        )
        _add_bidirectional_edge_pair(
            edges,
            f"r{spec.grid_size - 1}c{col}",
            f"north_c{col}",
            road_class=road_class,
            lanes=lanes,
            speed=speed,
            length=spec.north_south_stub_m,
            orientation="vertical",
            boundary=True,
        )
    return edges


def _add_bidirectional_edge_pair(
    edges: list[dict[str, Any]],
    node_a: str,
    node_b: str,
    *,
    road_class: str,
    lanes: int,
    speed: float,
    length: float,
    orientation: str,
    boundary: bool = False,
) -> None:
    edges.append(
        {
            "id": f"e_{node_a}__{node_b}",
            "from": node_a,
            "to": node_b,
            "road_class": road_class,
            "lanes": lanes,
            "speed_mps": speed,
            "length_m": length,
            "orientation": orientation,
            "direction": "forward",
            "boundary": boundary,
        }
    )
    edges.append(
        {
            "id": f"e_{node_b}__{node_a}",
            "from": node_b,
            "to": node_a,
            "road_class": road_class,
            "lanes": lanes,
            "speed_mps": speed,
            "length_m": length,
            "orientation": orientation,
            "direction": "reverse",
            "boundary": boundary,
        }
    )


def _intersection_type(spec: GridSpec, row: int, col: int) -> str:
    if row == spec.center_index and col == spec.center_index:
        return "A"
    if row == spec.center_index or col == spec.center_index:
        return "B"
    return "C"


def _write_plain_nodes(path: Path, nodes: list[dict[str, Any]]) -> None:
    root = ET.Element("nodes")
    for node in nodes:
        attrs = {
            "id": node["id"],
            "x": f"{node['x']:.3f}",
            "y": f"{node['y']:.3f}",
            "type": node["type"],
        }
        ET.SubElement(root, "node", attrs)
    _write_xml(path, root)


def _write_plain_edges(path: Path, edges: list[dict[str, Any]]) -> None:
    root = ET.Element("edges")
    for edge in edges:
        attrs = {
            "id": edge["id"],
            "from": edge["from"],
            "to": edge["to"],
            "numLanes": str(edge["lanes"]),
            "speed": f"{edge['speed_mps']:.6f}",
            "length": f"{edge['length_m']:.3f}",
        }
        ET.SubElement(root, "edge", attrs)
    _write_xml(path, root)


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _compile_net(paths: NetworkPaths) -> None:
    cmd = [
        "netconvert",
        "-n",
        str(paths.nodes_xml),
        "-e",
        str(paths.edges_xml),
        "-o",
        str(paths.net_xml),
        "--no-turnarounds",
        "true",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "netconvert failed",
            {"cmd": cmd, "stdout": result.stdout, "stderr": result.stderr},
        )


def _build_metadata(
    spec: GridSpec,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    paths: NetworkPaths,
) -> dict[str, Any]:
    intersections = [node for node in nodes if node["kind"] == "intersection"]
    boundary_nodes = [node for node in nodes if node["kind"] == "boundary"]
    counts = {
        "A": sum(1 for node in intersections if node["intersection_type"] == "A"),
        "B": sum(1 for node in intersections if node["intersection_type"] == "B"),
        "C": sum(1 for node in intersections if node["intersection_type"] == "C"),
    }
    return {
        "spec": {
            "grid_size": spec.grid_size,
            "block_spacing_x_m": spec.block_spacing_x_m,
            "block_spacing_y_m": spec.block_spacing_y_m,
            "west_east_stub_m": spec.west_east_stub_m,
            "north_south_stub_m": spec.north_south_stub_m,
            "main_lanes": spec.main_lanes,
            "minor_lanes": spec.minor_lanes,
            "main_speed_kph": spec.main_speed_kph,
            "minor_speed_kph": spec.minor_speed_kph,
        },
        "counts": {
            "intersections": len(intersections),
            "boundary_nodes": len(boundary_nodes),
            "intersection_types": counts,
            "edges": len(edges),
        },
        "files": {
            "nodes_xml": str(paths.nodes_xml),
            "edges_xml": str(paths.edges_xml),
            "net_xml": str(paths.net_xml),
        },
        "intersections": intersections,
        "boundary_nodes": boundary_nodes,
        "edges": edges,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_connectivity(net_path: Path, metadata: dict[str, Any]) -> None:
    net = sumo_net.readNet(str(net_path))
    graph: dict[str, set[str]] = {}
    for edge in net.getEdges():
        graph.setdefault(edge.getFromNode().getID(), set()).add(edge.getToNode().getID())

    start = "west_r3"
    goal = "east_r3"
    if not _has_path(graph, start, goal):
        raise RuntimeError(f"No path found between {start} and {goal}")


def _has_path(graph: dict[str, set[str]], start: str, goal: str) -> bool:
    if start == goal:
        return True
    visited = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for neighbor in graph.get(current, set()):
            if neighbor == goal:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return False
