from __future__ import annotations

import json
from pathlib import Path

import scripts.reproduce_all as reproduce_all


def test_reproduce_all_runs_expected_command_sequence(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    monkeypatch.setattr(reproduce_all, "validate_environment", lambda: {"sumo": "sumo"})
    monkeypatch.setattr(reproduce_all, "save_aggregated_outputs", lambda output_dir: {"summary_csv": str(output_dir / "processed" / "aggregated_summary.csv")})
    monkeypatch.setattr(reproduce_all, "save_policy_comparison_plots", lambda output_dir: {"travel_time": str(output_dir / "figures" / "travel_time.png")})
    monkeypatch.setattr(reproduce_all, "_run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(reproduce_all.sys, "argv", ["reproduce_all.py"])

    exit_code = reproduce_all.main()

    assert exit_code == 0
    assert any("generate_network.py" in part for cmd in calls for part in cmd)
    assert any("generate_signals.py" in part for cmd in calls for part in cmd)
    assert any("generate_routes.py" in part for cmd in calls for part in cmd)
    assert any("run_experiments.py" in part for cmd in calls for part in cmd)
    assert any("validate_project.py" in part for cmd in calls for part in cmd)
    assert any(cmd[:3] == [reproduce_all.sys.executable, "-m", "pytest"] for cmd in calls)


def test_view_gui_builds_sumo_gui_command(monkeypatch, tmp_path):
    import scripts.view_gui as view_gui

    captured: dict[str, object] = {}

    def fake_execvpe(program: str, argv: list[str], env: dict[str, str]) -> None:
        captured["argv"] = argv
        captured["env"] = env
        raise SystemExit(0)

    monkeypatch.setattr(view_gui.os, "execvpe", fake_execvpe)
    monkeypatch.setattr(view_gui.shutil, "which", lambda name: "/usr/local/bin/sumo-gui")
    monkeypatch.setattr(view_gui.sys, "argv", ["view_gui.py"])
    monkeypatch.delenv("DISPLAY", raising=False)

    network_dir = tmp_path / "network" / "generated"
    routes_dir = tmp_path / "routes" / "generated"
    network_dir.mkdir(parents=True, exist_ok=True)
    routes_dir.mkdir(parents=True, exist_ok=True)
    (network_dir / "city.net.xml").write_text("<net />", encoding="utf-8")
    (network_dir / "city.tll.xml").write_text("<additional />", encoding="utf-8")
    (routes_dir / "heavy.rou.xml").write_text("<routes />", encoding="utf-8")

    monkeypatch.setattr(view_gui, "PROJECT_ROOT", tmp_path)

    try:
        view_gui.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured["argv"][0].endswith("sumo-gui")
    assert "-n" in captured["argv"]
    assert "-r" in captured["argv"]
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["DISPLAY"] == ":0.0"
    assert env["LIBGL_ALWAYS_INDIRECT"] == "1"
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
