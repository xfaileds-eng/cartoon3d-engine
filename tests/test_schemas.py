import json

from core import config
from core.qa_gates.gates import validate


def test_fixtures_match_schemas(chunk, chunk_sensitive, shot_example):
    assert validate("chunk_input", chunk) == []
    assert validate("chunk_input", chunk_sensitive) == []
    assert validate("shot", shot_example) == []


def test_registry_rows_match_asset_schema():
    rows = json.loads((config.REGISTRY_PATH).read_text(encoding="utf-8"))["assets"]
    for row in rows:
        assert validate("asset", row) == [], row["asset_id"]


def test_chunk_id_convention(chunk):
    bad = dict(chunk, chunk_id="4200_2")
    assert any("chunk_id" in e for e in validate("chunk_input", bad))


def test_interp_must_use_blender_names(shot_example):
    bad = json.loads(json.dumps(shot_example))
    bad["camera"]["interp"] = "easeInOutQuad"  # tên After Effects → bị chặn
    assert any("interp" in e for e in validate("shot", bad))


def test_sensitivity_device_enum(shot_example):
    bad = json.loads(json.dumps(shot_example))
    bad["sensitivity_device"] = "blur"
    assert validate("shot", bad)
