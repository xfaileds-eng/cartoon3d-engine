"""Nối port của engine-contracts với adapter theo providers.yaml (mỗi máy một file, không đưa lên Git).

providers.yaml:
  llm_provider: [claude_api, mock]     # chuỗi dự phòng, theo thứ tự
Adapter thật nằm ở repo provider-adapters (package `provider_adapters`); adapter `mock` nằm ở engine-contracts.
Không có file hoặc không import được adapter nào → port không có adapter, planner dùng bản nháp tất định.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import yaml

from . import config, contracts


def _log(msg: str) -> None:
    print(f"[cartoon3d] {msg}", file=sys.stderr, flush=True)


def load_providers_config(path: Path | None = None) -> dict[str, list[str]]:
    path = Path(path or config.PROVIDERS_PATH)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: list(v or []) for k, v in data.items()}


def _make_adapter(name: str) -> Any | None:
    contracts.ensure_import_path()
    if name == "mock":
        from adapters_mock import MockAdapter

        return MockAdapter()
    try:
        module = importlib.import_module(f"provider_adapters.{name}")
    except ImportError:
        _log(f"bỏ qua adapter '{name}': chưa cài provider-adapters")
        return None
    return module.make_adapter()


def port_client(port: str, cfg: dict[str, list[str]] | None = None):
    contracts.ensure_import_path()
    from ports import PortClient

    cfg = load_providers_config() if cfg is None else cfg
    adapters = [a for a in (_make_adapter(n) for n in cfg.get(port, [])) if a is not None]
    return PortClient(port, adapters)
