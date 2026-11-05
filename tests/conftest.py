import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import contracts  # noqa: E402

contracts.ensure_import_path()  # ports, policies, adapters_mock, tests/common của engine-contracts

FIX = ROOT / "tests" / "fixtures" / "cheese_bank"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def has_render_tools() -> bool:
    if not (shutil.which("node") and shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


needs_render = pytest.mark.skipif(not has_render_tools(), reason="cần node + playwright + Chromium + ffmpeg")


@pytest.fixture(scope="session")
def chunk_sample():
    return _load(contracts.contracts_dir() / "tests" / "fixtures" / "chunk_sample.json")


@pytest.fixture
def chunk():
    return _load(FIX / "chunk_input.json")


@pytest.fixture
def chunk_sensitive():
    return _load(FIX / "chunk_sensitive.json")


@pytest.fixture
def shot_example():
    return _load(FIX / "shot_example.json")


@pytest.fixture
def mock_llm():
    """Port llm_provider cắm adapter mock: trả lại bản nháp của planner (không gọi Claude thật)."""
    from adapters_mock import MockAdapter
    from ports import PortClient

    return PortClient("llm_provider", [MockAdapter()], sleep=lambda s: None)


def _render(chunk_path: Path, out_root: Path) -> dict:
    from adapters_mock import MockAdapter
    from core.pipeline import run_chunk
    from ports import PortClient

    llm = PortClient("llm_provider", [MockAdapter()], sleep=lambda s: None)
    ro = run_chunk(chunk_path, out_root=out_root, backend="threejs", llm=llm)
    return {"render_output": ro, "out_dir": out_root / json.loads(chunk_path.read_text())["chunk_id"]}


@pytest.fixture(scope="session")
def engine_output(tmp_path_factory):
    if not has_render_tools():
        pytest.skip("cần node + playwright + Chromium + ffmpeg")
    return _render(contracts.contracts_dir() / "tests" / "fixtures" / "chunk_sample.json",
                   tmp_path_factory.mktemp("sample"))


@pytest.fixture(scope="session")
def cheese_bank_output(tmp_path_factory):
    if not has_render_tools():
        pytest.skip("cần node + playwright + Chromium + ffmpeg")
    return _render(FIX / "chunk_input.json", tmp_path_factory.mktemp("cheese_bank"))
