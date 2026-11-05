import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures" / "cheese_bank"


@pytest.fixture
def chunk():
    return json.loads((FIX / "chunk_input.json").read_text(encoding="utf-8"))


@pytest.fixture
def chunk_sensitive():
    return json.loads((FIX / "chunk_sensitive.json").read_text(encoding="utf-8"))


@pytest.fixture
def shot_example():
    return json.loads((FIX / "shot_example.json").read_text(encoding="utf-8"))


def has_e2e_tools() -> bool:
    if not (shutil.which("node") and shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return False
    import subprocess
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True)
    return r.returncode == 0
