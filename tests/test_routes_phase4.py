from pathlib import Path

from simulation.config import load_experiment_config
from simulation.network_builder import generate_network_artifacts
from simulation.routes import generate_route_artifacts


def test_generate_all_route_artifacts(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    generate_network_artifacts(config.data, tmp_path)
    metadata = generate_route_artifacts(config.data, tmp_path, seed=11)

    assert set(metadata["levels"].keys()) == {"low", "medium", "heavy"}
    assert Path(metadata["levels"]["low"]["route_file"]).exists()
    assert Path(metadata["levels"]["medium"]["route_file"]).exists()
    assert Path(metadata["levels"]["heavy"]["route_file"]).exists()


def test_route_counts_and_mapping(tmp_path):
    config = load_experiment_config(Path("config/experiment.yaml"))
    generate_network_artifacts(config.data, tmp_path)
    metadata = generate_route_artifacts(config.data, tmp_path, seed=11, demand_level="low")

    low = metadata["levels"]["low"]
    assert low["routes"] == 21
    assert low["vehicles"] > 0
    mapping = metadata["mapping"]["low"]
    assert set(mapping.keys()) == {"I", "J", "K"}
    assert len(mapping["I"]) == 7
    assert len(mapping["J"]) == 7
    assert len(mapping["K"]) == 7

