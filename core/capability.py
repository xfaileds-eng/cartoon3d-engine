"""Thẻ năng lực của engine: nhạc trưởng đọc để phân vai; engine tự kiểm để trả `rejected` sớm."""
from __future__ import annotations

import json
from typing import Any

from . import config


def load_capability_card() -> dict[str, Any]:
    return json.loads(config.CAPABILITY_CARD_PATH.read_text(encoding="utf-8"))


def check_capability(card: dict[str, Any], chunk: dict[str, Any]) -> str | None:
    """None = engine nhận chunk; chuỗi = lý do từ chối (status `rejected`)."""
    duration = chunk["end_ms"] - chunk["start_ms"]
    if duration < card["min_ms"]:
        return f"thời lượng {duration} ms < min_ms {card['min_ms']}"
    if duration > card["max_ms"]:
        return f"thời lượng {duration} ms > max_ms {card['max_ms']}"
    if chunk["aspect"] not in card["aspects"]:
        return f"aspect {chunk['aspect']} không thuộc {card['aspects']}"
    return None
