"""Luồng trọn vẹn với backend Three.js trong Chromium headless. Bỏ qua khi thiếu node/playwright/ffmpeg."""
import json
import shutil

import pytest

from core.pipeline import run_chunk
from tests.conftest import FIX, has_e2e_tools

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(not has_e2e_tools(), reason="cần node + playwright + Chromium + ffmpeg")
def test_cheese_bank_renders_and_passes_8_gates(tmp_path):
    out = run_chunk(FIX / "chunk_input.json", out_root=tmp_path, backend="threejs", width=320, height=180)
    assert out["qa_report"]["passed"]
    assert [g["id"] for g in out["qa_report"]["gates"]] == [f"G{i}" for i in range(1, 9)]
    assert out["frames"] == 101
    assert (tmp_path / "000004200_002" / "000004200_002.mp4").exists()
    assert (tmp_path / "000004200_002" / "contact_sheet.png").exists()
    ro = json.loads((tmp_path / "000004200_002" / "render_output.json").read_text(encoding="utf-8"))
    assert ro["chunk_id"] == "000004200_002"


@pytest.mark.skipif(not has_e2e_tools(), reason="cần node + playwright + Chromium + ffmpeg")
def test_sensitive_chunk_renders_offscreen(tmp_path):
    out = run_chunk(FIX / "chunk_sensitive.json", out_root=tmp_path, backend="threejs", width=320, height=180)
    assert out["qa_report"]["passed"]
    assert out["frames"] == 132
