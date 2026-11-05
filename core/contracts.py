"""Đọc hợp đồng chung từ repo engine-contracts: schema, format.json, look, ports.

chunk_input và render_output KHÔNG copy vào repo này. Thứ tự tìm thư mục engine-contracts:
  1. biến môi trường ENGINE_CONTRACTS_DIR
  2. repo anh em ../engine-contracts (clone cạnh repo này, đúng luật $HOME/<repo>)
  3. vendor/engine-contracts — bản chép tạm từ brief, xoá khi repo thật có trên GitHub
"""
from __future__ import annotations

import functools
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_SCHEMAS = ("shot", "asset")  # hai schema riêng của engine, nằm trong specs/


@functools.lru_cache(maxsize=1)
def contracts_dir() -> Path:
    candidates = []
    if os.environ.get("ENGINE_CONTRACTS_DIR"):
        candidates.append(Path(os.environ["ENGINE_CONTRACTS_DIR"]))
    candidates += [REPO_ROOT.parent / "engine-contracts", REPO_ROOT / "vendor" / "engine-contracts"]
    for c in candidates:
        if (c / "schemas" / "chunk_input.schema.json").exists():
            return c.resolve()
    raise FileNotFoundError("không tìm thấy engine-contracts: đặt ENGINE_CONTRACTS_DIR hoặc clone ../engine-contracts")


def is_vendored() -> bool:
    return contracts_dir() == (REPO_ROOT / "vendor" / "engine-contracts").resolve()


def ensure_import_path() -> None:
    """Cho phép `import ports`, `import policies`, `import adapters_mock`, `import common.*` của engine-contracts."""
    for p in (contracts_dir(), contracts_dir() / "tests"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def schema_path(name: str) -> Path:
    if name in LOCAL_SCHEMAS:
        return REPO_ROOT / "specs" / f"{name}.schema.json"
    return contracts_dir() / "schemas" / f"{name}.schema.json"


@functools.lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    return json.loads(schema_path(name).read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def load_format() -> dict[str, Any]:
    return json.loads((contracts_dir() / "format.json").read_text(encoding="utf-8"))


def frame_size(aspect: str) -> tuple[int, int]:
    fmt = load_format()
    if aspect not in fmt["aspects"]:
        raise ValueError(f"aspect '{aspect}' không có trong format.json")
    s = fmt["aspects"][aspect]
    return int(s["width"]), int(s["height"])


@functools.lru_cache(maxsize=None)
def load_look(look_id: str) -> dict[str, Any]:
    path = contracts_dir() / "looks" / f"{look_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"look '{look_id}' không có trong engine-contracts/looks/")
    return json.loads(path.read_text(encoding="utf-8"))
