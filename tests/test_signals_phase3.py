from pathlib import Path

from simulation.config import load_experiment_config
from simulation.network_builder import generate_network_artifacts
from simulation.signals import generate_signal_programs


def test_generate_signal_programs(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    generate_network_artifacts(config.data, tmp_path)
    metadata = generate_signal_programs(config.data, tmp_path)

    assert len(metadata["traffic_lights"]) == 49
    types = {item["intersection_type"] for item in metadata["traffic_lights"]}
    assert types == {"A", "B", "C"}


def test_signal_cycle_lengths(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    generate_network_artifacts(config.data, tmp_path)
    metadata = generate_signal_programs(config.data, tmp_path)

    by_type = {}
    for item in metadata["traffic_lights"]:
        by_type.setdefault(item["intersection_type"], set()).add(item["cycle_length"])

    assert by_type["A"] == {180.0}
    assert by_type["B"] == {120.0}
    assert by_type["C"] == {90.0}


def test_type_c_serves_straight_movements_in_two_phases(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    generate_network_artifacts(config.data, tmp_path)
    metadata = generate_signal_programs(config.data, tmp_path)

    for signal in metadata["traffic_lights"]:
        if signal["intersection_type"] != "C":
            continue
        controlled = {
            movement["link_index"]
            for movement in signal["movements"]
            if movement["movement"] == "straight"
        }
        served = {
            link_index
            for phase in signal["phases"]
            for link_index in phase["allowed_links"]
        }
        assert served == controlled


def test_transition_phases_stay_inside_published_cycle_budget(tmp_path):
    config = load_experiment_config(Path("config/lecturer_demo.yaml"))
    generate_network_artifacts(config.data, tmp_path)
    metadata = generate_signal_programs(config.data, tmp_path)

    by_type = {}
    for item in metadata["traffic_lights"]:
        by_type.setdefault(item["intersection_type"], set()).add(item["cycle_length"])

    assert by_type["A"] == {180.0}
    assert by_type["B"] == {120.0}
    assert by_type["C"] == {90.0}
