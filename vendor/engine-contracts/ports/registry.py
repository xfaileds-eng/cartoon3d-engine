"""Năm port của brief: tên, trường vào bắt buộc, dạng dữ liệu ra."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortSpec:
    name: str
    request_keys: tuple[str, ...]
    output: str


PORTS: dict[str, PortSpec] = {
    "image_provider": PortSpec("image_provider", ("prompt", "style", "size", "seed"), "PNG + meta"),
    "video_provider": PortSpec("video_provider", ("prompt_slices", "refs", "duration_s", "aspect"), "MP4 + meta"),
    "model3d_provider": PortSpec("model3d_provider", ("prompt",), "GLB + giấy phép"),
    "llm_provider": PortSpec("llm_provider", ("messages", "response_schema"), "JSON đúng schema"),
    "data_provider": PortSpec("data_provider", ("query",), "CSV + source_url"),
}
