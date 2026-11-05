"""Luật tốc độ nằm ở lớp port, không nằm trong engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).with_name("default.json")


def load_policy(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
