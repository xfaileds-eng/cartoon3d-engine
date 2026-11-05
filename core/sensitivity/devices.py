"""Bảng quy đổi mức nhạy cảm → thủ pháp hình ảnh. Engine chỉ nhận mức đã gắn sẵn từ thượng nguồn."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TABLE: dict[str, Any] = json.loads(Path(__file__).with_name("table.json").read_text(encoding="utf-8"))


def _level(level: int) -> dict[str, Any]:
    try:
        return TABLE["levels"][str(int(level))]
    except KeyError:
        raise ValueError(f"mức nhạy cảm {level} không có trong bảng (0..3)") from None


def allowed_devices(level: int) -> list[str]:
    return list(_level(level)["allowed"])


def default_device(level: int) -> str:
    return _level(level)["default"]


def is_allowed(level: int, device: str) -> bool:
    return device in _level(level)["allowed"]


def device_spec(device: str) -> dict[str, Any]:
    try:
        return TABLE["devices"][device]
    except KeyError:
        raise ValueError(f"thủ pháp '{device}' không có trong bảng") from None
