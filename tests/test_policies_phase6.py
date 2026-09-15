from __future__ import annotations

import copy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from simulation.config import load_experiment_config
from simulation.network_builder import generate_network_artifacts
from simulation.routes import generate_route_artifacts
from simulation.runner import run_policy_simulation
from simulation.signals import generate_signal_programs


def _policy_test_config(config: dict) -> dict:
    cfg = copy.deepcopy(config)
    cfg["simulation"]["route_generation_horizon_seconds"] = 40
    cfg["congestion"]["warmup_seconds"] = 0
    cfg["congestion"]["activation_seconds"] = 0
    cfg["congestion"]["deactivation_seconds"] = 20
    cfg["congestion"]["incident_duration_seconds"] = 20
    cfg["congestion"]["reduced_speed_kph"] = 2
    return cfg


def _write_policy_route_file(path: Path, routes: dict[str, list[str]]) -> None:
    root = ET.Element("routes")
    ET.SubElement(root, "vType", {"id": "micro", "accel": "2.6", "decel": "4.5", "length": "5.0"})
    for route_id, edges in routes.items():
        ET.SubElement(root, "route", {"id": route_id, "edges": " ".join(edges)})
    sequence = ["straight", "turn", "straight", "turn"]
    for index, kind in enumerate(sequence):
        route_id = "low_I4" if kind == "straight" else "low_I1"
        ET.SubElement(
            root,
            "vehicle",
            {
                "id": f"veh_{index:03d}",
                "type": "micro",
                "route": route_id,
                "depart": str(index * 2),
                "departLane": "best",
                "departSpeed": "max",
            },
        )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    tree.write(path, encoding="utf-8", xml_declaration=True)


@pytest.mark.integration
def test_policies_rewrite_routes_and_keep_straight_movement(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    test_config = _policy_test_config(config.data)
    generate_network_artifacts(test_config, tmp_path)
    generate_signal_programs(test_config, tmp_path)
    route_metadata = generate_route_artifacts(test_config, tmp_path, seed=11, demand_level="low")

    low_mapping = route_metadata["mapping"]["low"]["I"]
    route_edges = {item["route_id"]: item["route_edges"] for item in low_mapping if item["route_id"] in {"low_I1", "low_I4"}}
    route_file = tmp_path / "routes" / "generated" / "policy_phase6.rou.xml"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    _write_policy_route_file(route_file, route_edges)

    normal = run_policy_simulation(
        test_config,
        tmp_path,
        "normal",
        "low",
        seed=11,
        route_file=route_file,
        max_simulation_time=20,
    )
    long = run_policy_simulation(
        test_config,
        tmp_path,
        "long",
        "low",
        seed=11,
        route_file=route_file,
        max_simulation_time=20,
    )
    huang = run_policy_simulation(
        test_config,
        tmp_path,
        "huang",
        "low",
        seed=11,
        route_file=route_file,
        max_simulation_time=20,
    )

    assert normal["policy_actions"] == []
    assert normal["summary"]["teleports"] == 0
    assert normal["summary"]["simulation_capped"] is True

    long_actions = long["policy_actions"]
    assert any(action["original_route"] == "low_I4" for action in long_actions)
    assert all(action["restriction"] == "ban straight movement through zone_ab" for action in long_actions)
    assert any(action["replacement_route"] != "low_I4" for action in long_actions if action["replacement_route"] is not None)
    assert all(action["route_valid"] for action in long_actions if action["replacement_route"] is not None)

    huang_actions = huang["policy_actions"]
    assert any(action["original_route"] == "low_I1" for action in huang_actions)
    assert all(action["restriction"] == "ban side-turn movement feeding zone_ab" for action in huang_actions)
    assert all(action["replacement_route"] == "low_I4" for action in huang_actions if action["replacement_route"] is not None)
    assert all(action["route_valid"] for action in huang_actions if action["replacement_route"] is not None)
    assert all(action["original_route"] != "low_I4" for action in huang_actions)

    for result in [normal, long, huang]:
        assert result["summary"]["teleports"] == 0
        assert result["summary"]["simulation_capped"] is True
