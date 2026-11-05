"""Phong bì kết quả chung của mọi port."""
from __future__ import annotations

from typing import Any, TypedDict

STATUSES = ("ok", "blocked", "rate_limited", "failed")
REQUIRED_KEYS = ("status", "provider", "cost_usd", "latency_ms", "license", "data")


class Envelope(TypedDict):
    status: str
    provider: str
    cost_usd: float
    latency_ms: int
    license: str | None
    data: Any


def make_envelope(status: str, provider: str, data: Any = None, *, cost_usd: float = 0.0,
                  latency_ms: int = 0, license: str | None = None, error: str | None = None) -> dict[str, Any]:
    env: dict[str, Any] = {"status": status, "provider": provider, "cost_usd": float(cost_usd),
                           "latency_ms": int(latency_ms), "license": license, "data": data}
    if error:
        env["error"] = error
    return env


def validate_envelope(env: Any) -> list[str]:
    """Trả về danh sách lỗi; rỗng = phong bì hợp lệ."""
    if not isinstance(env, dict):
        return ["phong bì phải là object"]
    errs = [f"thiếu khoá '{k}'" for k in REQUIRED_KEYS if k not in env]
    if env.get("status") not in STATUSES:
        errs.append(f"status '{env.get('status')}' không thuộc {STATUSES}")
    if not isinstance(env.get("cost_usd", 0), (int, float)) or env.get("cost_usd", 0) < 0:
        errs.append("cost_usd phải là số ≥ 0")
    if not isinstance(env.get("latency_ms", 0), int) or env.get("latency_ms", 0) < 0:
        errs.append("latency_ms phải là số nguyên ≥ 0")
    return errs
