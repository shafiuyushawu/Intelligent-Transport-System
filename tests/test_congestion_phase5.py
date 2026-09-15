from __future__ import annotations

import copy
from pathlib import Path
from xml.etree import ElementTree as ET

from simulation.config import load_experiment_config
from simulation.congestion import generate_congestion_detectors, run_congestion_comparison
from simulation.network_builder import generate_network_artifacts
from simulation.signals import generate_signal_programs


def _write_micro_route_file(path: Path, *, vehicle_count: int = 30, depart_step: int = 2) -> None:
    root = ET.Element("routes")
    ET.SubElement(root, "vType", {"id": "micro", "accel": "2.6", "decel": "4.5", "length": "5.0"})
    route_edges = [
        "e_west_r3__r3c0",
        "e_r3c0__r3c1",
        "e_r3c1__r3c2",
        "e_r3c2__r3c3",
        "e_r3c3__r3c4",
        "e_r3c4__r3c5",
        "e_r3c5__r3c6",
        "e_r3c6__east_r3",
    ]
    ET.SubElement(root, "route", {"id": "micro_route", "edges": " ".join(route_edges)})
    for index in range(vehicle_count):
        ET.SubElement(
            root,
            "vehicle",
            {
                "id": f"veh_{index:03d}",
                "type": "micro",
                "route": "micro_route",
                "depart": str(index * depart_step),
                "departLane": "best",
                "departSpeed": "max",
            },
        )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")  # type: ignore[attr-defined]
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _phase5_test_config(config: dict) -> dict:
    cfg = copy.deepcopy(config)
    cfg["simulation"]["route_generation_horizon_seconds"] = 180
    cfg["congestion"]["warmup_seconds"] = 0
    cfg["congestion"]["activation_seconds"] = 0
    cfg["congestion"]["deactivation_seconds"] = 600
    cfg["congestion"]["incident_duration_seconds"] = 600
    cfg["congestion"]["reduced_speed_kph"] = 2
    return cfg


def test_congestion_zone_reduces_speed_and_increases_queue(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    test_config = _phase5_test_config(config.data)
    generate_network_artifacts(test_config, tmp_path)
    generate_signal_programs(test_config, tmp_path)
    generate_congestion_detectors(test_config, tmp_path)

    route_file = tmp_path / "routes" / "generated" / "micro.rou.xml"
    route_file.parent.mkdir(parents=True, exist_ok=True)
    _write_micro_route_file(route_file)

    comparison = run_congestion_comparison(
        test_config,
        tmp_path,
        route_file,
        output_prefix="phase5_micro",
    )

    baseline = comparison["baseline"]["summary"]
    incident = comparison["incident"]["summary"]

    assert incident["mean_speed_mps"] < baseline["mean_speed_mps"]
    assert incident["mean_waiting_time_s"] >= baseline["mean_waiting_time_s"]
    assert incident["mean_queue_length_m"] >= baseline["mean_queue_length_m"]
    assert incident["mean_travel_time_s"] >= baseline["mean_travel_time_s"]
    assert Path(comparison["plots"]["png"]).exists()
    assert Path(comparison["plots"]["pdf"]).exists()
