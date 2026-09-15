from pathlib import Path

from simulation.config import load_experiment_config


def test_load_experiment_config():
    config = load_experiment_config(Path("config/experiment.yaml"))
    assert config["project"]["name"] == "traffic-congestion-replication"
    assert config["simulation"]["random_seeds"] == [11, 22, 33, 44, 55]

