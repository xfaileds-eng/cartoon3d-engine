"""PortClient: gọi một port qua chuỗi adapter, áp luật tốc độ ở lớp port (retry, cooldown, dự phòng)."""
from __future__ import annotations

import time
from typing import Any, Callable, Protocol

from .envelope import make_envelope, validate_envelope
from .registry import PORTS


class Adapter(Protocol):
    provider: str

    def call(self, port: str, request: dict[str, Any]) -> dict[str, Any]: ...


class PortClient:
    def __init__(self, port: str, adapters: list[Adapter], policy: dict[str, Any] | None = None, *,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        if port not in PORTS:
            raise ValueError(f"port '{port}' không có; chọn trong {sorted(PORTS)}")
        from policies import load_policy  # noqa: PLC0415 — policies nằm cạnh ports trong engine-contracts

        self.port = port
        self.adapters = list(adapters)
        self.policy = policy or load_policy()
        self.clock = clock
        self.sleep = sleep
        self.cooldown_until: dict[str, float] = {}
        self.log: list[dict[str, Any]] = []

    def _cooldown_s(self, provider: str) -> float:
        per = self.policy.get("cooldown_s", {})
        return float(per.get(provider, per.get("default", 60)))

    def in_cooldown(self, provider: str) -> bool:
        return self.clock() < self.cooldown_until.get(provider, float("-inf"))

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        spec = PORTS[self.port]
        missing = [k for k in spec.request_keys if k not in request]
        if missing:
            return make_envelope("failed", "port", error=f"{self.port} thiếu trường {missing}")
        if not self.adapters:
            return make_envelope("failed", "port", error=f"{self.port}: chưa cấu hình adapter nào")
        retry = self.policy.get("retry", {})
        max_attempts = int(retry.get("max_attempts", 3))
        backoff = [float(s) for s in retry.get("backoff_s", [2, 4, 8])]
        last = make_envelope("failed", "port", error="mọi adapter đang cooldown")
        for adapter in self.adapters:
            if self.in_cooldown(adapter.provider):
                self.log.append({"provider": adapter.provider, "skipped": "cooldown"})
                continue
            for attempt in range(max_attempts):
                t0 = self.clock()
                env = adapter.call(self.port, request)
                errs = validate_envelope(env)
                if errs:
                    env = make_envelope("failed", adapter.provider, error="phong bì sai: " + "; ".join(errs))
                env.setdefault("latency_ms", int((self.clock() - t0) * 1000))
                self.log.append({"provider": adapter.provider, "attempt": attempt + 1, "status": env["status"]})
                last = env
                if env["status"] == "ok":
                    return env
                if env["status"] == "rate_limited":
                    self.cooldown_until[adapter.provider] = self.clock() + self._cooldown_s(adapter.provider)
                    break  # sang adapter dự phòng
                if env["status"] == "blocked":
                    break  # nội dung bị chặn: thử adapter khác, không retry cùng chỗ
                if attempt + 1 < max_attempts:
                    self.sleep(backoff[min(attempt, len(backoff) - 1)])
        return last
