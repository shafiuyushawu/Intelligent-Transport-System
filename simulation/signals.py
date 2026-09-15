from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from simulation.bootstrap import ensure_sumo_tools_on_path

ensure_sumo_tools_on_path()

from sumolib import net as sumo_net  # type: ignore  # noqa: E402


@dataclass(frozen=True)
class SignalConfig:
    yellow_seconds: float = 3.0
    all_red_seconds: float = 1.0


@dataclass(frozen=True)
class SignalPaths:
    root: Path
    net_xml: Path
    additional_xml: Path
    metadata_json: Path


def build_signal_paths(root: str | Path) -> SignalPaths:
    root_path = Path(root)
    return SignalPaths(
        root=root_path,
        net_xml=root_path / "network" / "generated" / "city.net.xml",
        additional_xml=root_path / "network" / "generated" / "city.tll.xml",
        metadata_json=root_path / "network" / "metadata" / "signal_metadata.json",
    )


def generate_signal_programs(config: dict[str, Any], root: str | Path) -> dict[str, Any]:
    paths = build_signal_paths(root)
    net = sumo_net.readNet(str(paths.net_xml))
    signal_cfg = SignalConfig(
        yellow_seconds=float(config["signals"]["yellow_seconds"]),
        all_red_seconds=float(config["signals"]["all_red_seconds"]),
    )
    include_transitions = bool(config["signals"].get("include_transition_phases", False))

    tls_metadata: list[dict[str, Any]] = []
    root_xml = ET.Element("additional")

    for node in net.getNodes():
        if not node.getType() == "traffic_light":
            continue
        if node.getID().startswith(("west_", "east_", "south_", "north_")):
            continue
        if node.getID() not in _expected_signal_ids():
            continue

        intersection_type = _intersection_type_from_id(node.getID())
        movements = _collect_movements(node)
        phases = _build_program_for_type(
            node,
            intersection_type,
            movements,
            signal_cfg,
            include_transitions,
        )
        tl_elem = ET.SubElement(
            root_xml,
            "tlLogic",
            {
                "id": node.getID(),
                "type": "static",
                "programID": f"{intersection_type}_fixed",
                "offset": "0",
            },
        )
        for phase in phases:
            ET.SubElement(
                tl_elem,
                "phase",
                {
                    "duration": f"{phase['duration']:.0f}",
                    "state": phase["state"],
                },
            )
        tls_metadata.append(
            {
                "id": node.getID(),
                "intersection_type": intersection_type,
                "phase_count": len(phases),
                "cycle_length": sum(phase["duration"] for phase in phases),
                "controlled_links": len(phases[0]["state"]) if phases else 0,
                "movements": movements,
                "phases": phases,
            }
        )

    _write_xml(paths.additional_xml, root_xml)
    metadata = {
        "files": {
            "additional_xml": str(paths.additional_xml),
            "net_xml": str(paths.net_xml),
        },
        "traffic_lights": tls_metadata,
    }
    _write_json(paths.metadata_json, metadata)
    _validate_signal_programs(paths.net_xml, paths.additional_xml, tls_metadata)
    return metadata


def _expected_signal_ids() -> set[str]:
    return {f"r{row}c{col}" for row in range(7) for col in range(7)}


def _intersection_type_from_id(node_id: str) -> str:
    row = int(node_id[1])
    col = int(node_id[3])
    if row == 3 and col == 3:
        return "A"
    if row == 3 or col == 3:
        return "B"
    return "C"


def _collect_movements(node: Any) -> list[dict[str, Any]]:
    movements: list[dict[str, Any]] = []
    for connection in node.getConnections():
        if connection.getTLSID() != node.getID():
            continue
        movement = connection.getDirection()
        if movement not in {"s", "l", "r"}:
            continue
        link_index = connection.getTLLinkIndex()
        movements.append(
            {
                "link_index": int(link_index),
                "incoming_edge": connection.getFrom().getID(),
                "outgoing_edge": connection.getTo().getID(),
                "movement": {"s": "straight", "l": "left", "r": "right"}[movement],
                "delta_deg": None,
            }
        )
    movements.sort(key=lambda item: item["link_index"])
    return movements


def _build_program_for_type(
    node: Any,
    intersection_type: str,
    movements: list[dict[str, Any]],
    signal_cfg: SignalConfig,
    include_transitions: bool,
) -> list[dict[str, Any]]:
    state_len = max(m["link_index"] for m in movements) + 1 if movements else 0
    templates = {
        "A": [
            ("straight_ns", 15.0),
            ("straight_ew", 25.0),
            ("left_ns", 25.0),
            ("left_ew", 25.0),
            ("right_ns", 15.0),
            ("right_ew", 25.0),
            ("all_red_1", 25.0),
            ("all_red_2", 25.0),
        ],
        "B": [
            ("straight_ns", 15.0),
            ("straight_ew", 30.0),
            ("left_ns", 15.0),
            ("left_ew", 15.0),
            ("right_ns", 30.0),
            ("right_ew", 15.0),
        ],
        "C": [
            ("straight_ns", 45.0),
            ("straight_ew", 45.0),
        ],
    }
    phases: list[dict[str, Any]] = []
    for movement_key, base_duration in templates[intersection_type]:
        state = ["r"] * state_len
        allowed = _allowed_links_for_phase(movement_key, movements)
        for link_index in allowed:
            state[link_index] = "G"
        transition_budget = 0.0
        if include_transitions:
            transition_budget = signal_cfg.yellow_seconds + signal_cfg.all_red_seconds
        green_duration = base_duration - transition_budget
        if green_duration <= 0:
            raise ValueError(
                f"Transition time {transition_budget}s exhausts phase {movement_key} "
                f"budget of {base_duration}s"
            )
        phases.append(
            {
                "name": movement_key,
                "duration": green_duration,
                "state": "".join(state),
                "allowed_links": allowed,
            }
        )
        if include_transitions and signal_cfg.yellow_seconds > 0:
            phases.append(
                {
                    "name": f"{movement_key}_yellow",
                    "duration": signal_cfg.yellow_seconds,
                    "state": _yellow_state(state, allowed),
                    "allowed_links": allowed,
                }
            )
        if include_transitions and signal_cfg.all_red_seconds > 0:
            phases.append(
                {
                    "name": f"{movement_key}_all_red",
                    "duration": signal_cfg.all_red_seconds,
                    "state": "r" * state_len,
                    "allowed_links": [],
                }
            )

    if not include_transitions:
        return _compress_phases(phases, intersection_type)
    return phases


def _allowed_links_for_phase(movement_key: str, movements: list[dict[str, Any]]) -> list[int]:
    if movement_key.startswith("all_red"):
        return []
    movement_class = None
    if movement_key.startswith("straight"):
        movement_class = "straight"
    elif movement_key.startswith("left"):
        movement_class = "left"
    elif movement_key.startswith("right"):
        movement_class = "right"

    if movement_key.endswith("ns"):
        orientation = {"north", "south"}
    elif movement_key.endswith("ew"):
        orientation = {"east", "west"}
    else:
        orientation = {"north", "south", "east", "west"}

    allowed: list[int] = []
    for movement in movements:
        if movement_class is not None and movement["movement"] != movement_class:
            continue
        incoming_dir = _edge_direction(movement["incoming_edge"])
        outgoing_dir = _edge_direction(movement["outgoing_edge"])
        if incoming_dir in orientation or outgoing_dir in orientation:
            allowed.append(movement["link_index"])
    return sorted(set(allowed))


def _edge_direction(edge_id: str) -> str:
    if edge_id.startswith("e_west_") or "__west_" in edge_id:
        return "west"
    if edge_id.startswith("e_east_") or "__east_" in edge_id:
        return "east"
    if edge_id.startswith("e_south_") or "__south_" in edge_id:
        return "south"
    if edge_id.startswith("e_north_") or "__north_" in edge_id:
        return "north"
    if "__r" in edge_id:
        left, right = edge_id.split("__", 1)
        fr = left.split("_")[-1]
        to = right.split("_")[-1]
        if fr.startswith("r") and to.startswith("r"):
            fr_row, fr_col = _parse_node_id(fr)
            to_row, to_col = _parse_node_id(to)
            if fr_row == to_row:
                return "east" if to_col > fr_col else "west"
            return "north" if to_row > fr_row else "south"
    return "unknown"


def _parse_node_id(node_id: str) -> tuple[int, int]:
    row = int(node_id.split("c")[0][1:])
    col = int(node_id.split("c")[1])
    return row, col


def _yellow_state(state: list[str], allowed: list[int]) -> str:
    yellow = state[:]
    for idx in allowed:
        yellow[idx] = "y"
    return "".join(yellow)


def _compress_phases(phases: list[dict[str, Any]], intersection_type: str) -> list[dict[str, Any]]:
    return [phase for phase in phases if not phase["name"].endswith(("yellow", "all_red"))]


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_signal_programs(net_xml: Path, additional_xml: Path, metadata: list[dict[str, Any]]) -> None:
    cmd = [
        "sumo",
        "-n",
        str(net_xml),
        "-a",
        str(additional_xml),
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
        "--end",
        "1",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        raise RuntimeError(
            "Signal validation run failed",
            {"stdout": proc.stdout, "stderr": proc.stderr, "cmd": cmd},
        )
