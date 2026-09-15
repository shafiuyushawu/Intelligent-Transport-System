from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from simulation.bootstrap import ensure_sumo_tools_on_path

ensure_sumo_tools_on_path()


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch SUMO-GUI for visual inspection.")
    parser.add_argument("--config", default=PROJECT_ROOT / "config" / "experiment.yaml", type=Path)
    parser.add_argument("--root", default=PROJECT_ROOT, type=Path)
    parser.add_argument("--demand", choices=["low", "medium", "heavy"], default="heavy")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.root.resolve()

    launch_env = _build_launch_env()
    if not _has_display(launch_env):
        print("GUI skipped: no graphical display is available. Start XQuartz and set DISPLAY to use make gui.")
        return 0

    sumo_gui = shutil.which("sumo-gui")
    if not sumo_gui:
        raise FileNotFoundError("sumo-gui is not on PATH")

    network = root / "network" / "generated" / "city.net.xml"
    signals = root / "network" / "generated" / "city.tll.xml"
    routes = root / "routes" / "generated" / f"{args.demand}.rou.xml"

    cmd = [sumo_gui, "-n", str(network), "-a", str(signals)]
    if routes.exists():
        cmd.extend(["-r", str(routes)])

    os.execvpe(cmd[0], cmd, launch_env)
    return 0


def _build_launch_env() -> dict[str, str]:
    env = os.environ.copy()
    if sys.platform == "darwin":
        display = env.get("DISPLAY", "").strip()
        if not display or display == ":0":
            env["DISPLAY"] = ":0.0"
        env.setdefault("LIBGL_ALWAYS_INDIRECT", "1")
        env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    return env


def _has_display(env: dict[str, str]) -> bool:
    display = env.get("DISPLAY", "").strip()
    wayland = env.get("WAYLAND_DISPLAY", "").strip()
    return bool(display or wayland)


if __name__ == "__main__":
    raise SystemExit(main())
