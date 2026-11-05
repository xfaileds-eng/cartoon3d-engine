"""Bộ test chung: mọi engine import file này (`from contract_suite import *`) và cung cấp hai fixture:

- `chunk_sample`: dict của tests/fixtures/chunk_sample.json;
- `engine_output`: dict {"render_output": dict, "out_dir": Path} sau khi engine chạy chunk_sample.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from PIL import Image

from adapters_mock import MockAdapter
from ports import PORTS, PortClient, validate_envelope

from .helpers import burned_caption_words, extract_frame, ffprobe_stream, is_blank

CONTRACTS = Path(__file__).resolve().parents[2]
EXPECTED_FRAMES = 126  # 4,2 s × 30 fps


def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _format() -> dict:
    return json.loads((CONTRACTS / "format.json").read_text(encoding="utf-8"))


def test_input_schema_valid(chunk_sample):
    jsonschema.validate(chunk_sample, _schema("chunk_input"))


def test_output_schema_valid(engine_output):
    jsonschema.validate(engine_output["render_output"], _schema("render_output"))
    assert engine_output["render_output"]["status"] == "done"


def test_frame_count_exact(engine_output):
    info = ffprobe_stream(Path(engine_output["render_output"]["video_path"]))
    assert info["frames"] == EXPECTED_FRAMES
    assert engine_output["render_output"]["frames"] == EXPECTED_FRAMES


def test_format(engine_output, chunk_sample):
    fmt = _format()
    info = ffprobe_stream(Path(engine_output["render_output"]["video_path"]))
    size = fmt["aspects"][chunk_sample["aspect"]]
    assert info["fps"] == fmt["fps"]
    assert (info["width"], info["height"]) == (size["width"], size["height"])
    assert info["codec"] == fmt["codec"] and info["pix_fmt"] == fmt["pix_fmt"]


def test_no_black_frames(engine_output, tmp_path):
    video = Path(engine_output["render_output"]["video_path"])
    for i in range(0, EXPECTED_FRAMES, 5):
        png = extract_frame(video, i, tmp_path / f"f{i}.png")
        assert not is_blank(Image.open(png)), f"khung {i} đen/trắng trơn"


def test_no_burned_captions(engine_output, chunk_sample, tmp_path):
    video = Path(engine_output["render_output"]["video_path"])
    png = extract_frame(video, EXPECTED_FRAMES // 2, tmp_path / "mid.png")
    assert burned_caption_words(png, chunk_sample["text"]) == []


def test_port_mock_roundtrip():
    requests = {
        "image_provider": {"prompt": "x", "style": "flat", "size": [64, 64], "seed": 1},
        "video_provider": {"prompt_slices": ["x"], "refs": [], "duration_s": 4.2, "aspect": "16:9"},
        "model3d_provider": {"prompt": "x"},
        "llm_provider": {"messages": [{"role": "user", "content": "x"}],
                         "response_schema": {"type": "object", "examples": [{"ok": True}]}},
        "data_provider": {"query": "x"},
    }
    assert set(requests) == set(PORTS)
    for port, req in requests.items():
        env = PortClient(port, [MockAdapter()]).call(req)
        assert validate_envelope(env) == [], port
        assert env["status"] == "ok" and env["provider"] == "mock"
    env = PortClient("llm_provider", [MockAdapter()]).call(requests["llm_provider"])
    assert env["data"] == {"ok": True}


def test_port_rate_limit_policy():
    now = [0.0]
    primary = MockAdapter("gemini_web", status_script=["rate_limited"])
    backup = MockAdapter("comfyui_local")
    client = PortClient("image_provider", [primary, backup], clock=lambda: now[0], sleep=lambda s: None)
    req = {"prompt": "x", "style": "flat", "size": [64, 64], "seed": 1}

    env = client.call(req)
    assert env["status"] == "ok" and env["provider"] == "comfyui_local"
    assert client.cooldown_until["gemini_web"] == 7200  # Gemini cooldown 2 giờ

    now[0] = 3600.0  # còn trong cooldown → không gọi lại gemini_web
    client.call(req)
    assert len(primary.calls) == 1

    now[0] = 7201.0  # hết cooldown → quay lại adapter chính
    env = client.call(req)
    assert env["provider"] == "gemini_web" and len(primary.calls) == 2
