"""Adapter mock cho test: không gọi dịch vụ thật, trả phong bì đúng hợp đồng."""
from __future__ import annotations

import base64
from typing import Any, Callable

from ports.envelope import make_envelope

# PNG 1x1 trong suốt — đủ để kiểm đường đi của image_provider.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class MockAdapter:
    """status_script: danh sách status trả lần lượt (hết thì 'ok'); responder: hàm tự sinh data theo request."""

    def __init__(self, provider: str = "mock", status_script: list[str] | None = None,
                 responder: Callable[[str, dict[str, Any]], Any] | None = None):
        self.provider = provider
        self.status_script = list(status_script or [])
        self.responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, port: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((port, request))
        status = self.status_script.pop(0) if self.status_script else "ok"
        if status != "ok":
            return make_envelope(status, self.provider, error=f"mock {status}")
        data = self.responder(port, request) if self.responder else default_response(port, request)
        return make_envelope("ok", self.provider, data, license="mock")


def default_response(port: str, request: dict[str, Any]) -> Any:
    if port == "llm_provider":
        # Trả ví dụ đầu tiên của response_schema nếu có: "mô hình đồng ý với bản nháp".
        examples = request["response_schema"].get("examples") or [{}]
        return examples[0]
    if port == "image_provider":
        return {"png_base64": base64.b64encode(_PNG_1X1).decode(), "meta": {"seed": request.get("seed")}}
    if port == "video_provider":
        return {"mp4_path": None, "meta": {"duration_s": request.get("duration_s")}}
    if port == "model3d_provider":
        return {"glb_path": None, "license": "mock"}
    if port == "data_provider":
        return {"csv": "x,y\n0,0\n", "source_url": "mock://data"}
    raise ValueError(f"port '{port}' không có trong mock")
