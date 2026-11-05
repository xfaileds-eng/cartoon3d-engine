import copy
import json

from core import config, contracts
from core.qa_gates.gates import validate


def test_fixtures_match_contracts(chunk, chunk_sensitive, chunk_sample, shot_example):
    for c in (chunk, chunk_sensitive, chunk_sample):
        assert validate("chunk_input", c) == [], c["chunk_id"]
    assert validate("shot", shot_example) == []


def test_shared_schemas_come_from_engine_contracts():
    """chunk_input và render_output lấy từ engine-contracts, không có bản copy trong specs/."""
    assert not (config.REPO_ROOT / "specs" / "chunk_input.schema.json").exists()
    assert not (config.REPO_ROOT / "specs" / "render_output.schema.json").exists()
    assert contracts.schema_path("chunk_input").is_relative_to(contracts.contracts_dir())


def test_registry_rows_match_asset_schema():
    rows = json.loads(config.REGISTRY_PATH.read_text(encoding="utf-8"))["assets"]
    for row in rows:
        assert validate("asset", row) == [], row["asset_id"]


def test_capability_card_matches_contract():
    card = json.loads((config.REPO_ROOT / "capability_card.json").read_text(encoding="utf-8"))
    assert validate("capability_card", card) == []
    assert card["engine_id"] == config.ENGINE_ID
    assert "llm_provider" in card["needs"]


def test_chunk_id_convention(chunk):
    assert any("chunk_id" in e for e in validate("chunk_input", dict(chunk, chunk_id="4200_2")))


def test_interp_must_use_blender_names(shot_example):
    bad = copy.deepcopy(shot_example)
    bad["camera"]["interp"] = "easeInOutQuad"  # tên kiểu After Effects → bị chặn
    assert any("interp" in e for e in validate("shot", bad))


def test_shot_has_no_captions_field(shot_example):
    bad = dict(shot_example, captions={"mode": "word_pop"})
    assert validate("shot", bad), "shot không được mang trường phụ đề: phụ đề in ở khâu ghép"


def test_sensitivity_device_enum(shot_example):
    assert validate("shot", dict(shot_example, sensitivity_device="blur"))
