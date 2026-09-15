from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ExperimentConfig:
    data: dict[str, Any]
    source_path: Path

    def __getitem__(self, item: str) -> Any:
        return self.data[item]


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        data = _resolve_env_vars(yaml.safe_load(handle) or {})
    return ExperimentConfig(data=data, source_path=source)


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_vars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        import os

        return os.environ.get(value[2:-1], value)
    return value
