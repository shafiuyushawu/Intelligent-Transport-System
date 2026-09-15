import sys

import pytest

from simulation.bootstrap import ensure_sumo_tools_on_path, get_sumo_home, sumo_tools_path


def test_get_sumo_home_requires_env(monkeypatch):
    monkeypatch.delenv("SUMO_HOME", raising=False)
    with pytest.raises(EnvironmentError):
        get_sumo_home()


def test_sumo_tools_path_exists():
    assert sumo_tools_path().exists()


def test_ensure_sumo_tools_on_path():
    tools = ensure_sumo_tools_on_path()
    assert str(tools) in sys.path
    assert tools.exists()

