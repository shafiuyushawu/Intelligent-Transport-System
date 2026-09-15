from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.aggregate import save_aggregated_outputs
from analysis.plots import save_policy_comparison_plots


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate saved Phase 7 experiment outputs.")
    parser.add_argument("--results-dir", default=Path("results"), type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    results_dir = args.results_dir.resolve()
    aggregate_payload = save_aggregated_outputs(results_dir)
    plot_payload = save_policy_comparison_plots(results_dir)
    print(json.dumps({"aggregate": aggregate_payload, "plots": plot_payload}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
