from pathlib import Path

import pytest

from simulation.config import load_experiment_config
from simulation.network_builder import generate_network_artifacts


@pytest.mark.integration
def test_generate_network_artifacts(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    metadata = generate_network_artifacts(config.data, tmp_path)

    assert metadata["counts"]["intersection_types"] == {"A": 1, "B": 12, "C": 36}
    assert metadata["counts"]["intersections"] == 49
    assert metadata["counts"]["edges"] > 0
    assert Path(metadata["files"]["net_xml"]).exists()


@pytest.mark.integration
def test_network_lane_counts_and_geometry(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    metadata = generate_network_artifacts(config.data, tmp_path)

    intersections = metadata["intersections"]
    center = [node for node in intersections if node["intersection_type"] == "A"]
    assert len(center) == 1
    assert center[0]["row"] == 3
    assert center[0]["col"] == 3

    main_edges = [edge for edge in metadata["edges"] if edge["road_class"] == "main"]
    minor_edges = [edge for edge in metadata["edges"] if edge["road_class"] == "minor"]
    assert all(edge["lanes"] == 3 for edge in main_edges)
    assert all(edge["lanes"] == 2 for edge in minor_edges)


@pytest.mark.integration
def test_network_connectivity(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    metadata = generate_network_artifacts(config.data, tmp_path)
    assert metadata["counts"]["intersections"] == 49
    assert metadata["counts"]["intersection_types"]["B"] == 12

