import copy
import json

import pytest
from PIL import Image, ImageDraw, ImageFont

from core import contracts
from core.capability import check_capability, load_capability_card
from core.look_adapter import build_look_profile, shift_hue
from core.pipeline import run_chunk
from core.qa_gates import GateContext, run_pre_render_gates
from core.qa_gates.gates import g7_sensitivity, no_captions_in_frames, validate
from core.registry import Registry, RegistryError
from core.scene_bundle import build_bundle
from core.sensitivity import allowed_devices, default_device, is_allowed
from core.shot_planner import plan_chunk, split_sentences
from core.timing import allocate_frames

FPS = 30


def _bundles(chunk, shots, w=640, h=360):
    look = contracts.load_look(chunk["look_id"])
    return [build_bundle(s, chunk, n, look=look, width=w, height=h, fps=FPS)
            for s, n in zip(shots, allocate_frames([s["duration_ms"] for s in shots], FPS))]


# ---------------------------------------------------------------- shot_planner
def test_plan_cheese_bank_matches_spec_example(chunk, shot_example, mock_llm):
    shots = plan_chunk(chunk, llm=mock_llm)
    assert len(shots) == 1
    s = shots[0]
    assert validate("shot", s) == []
    assert s["shot_id"] == shot_example["shot_id"]
    assert s["set"] == "cheese_vault" and s["look_id"] == "test_warm"
    assert s["cast"][0]["action"] == "walk_carry" and s["cast"][0]["props"] == ["cheese_wheel"]
    assert s["camera"]["move"] == "dolly" and s["camera"]["interp"] == "ease_in_out"
    assert s["sensitivity_device"] == "none"
    assert "captions" not in s


def test_default_style_is_voxel_for_crime_series(chunk, mock_llm):
    """Anh chốt 05/11/2026: dòng vụ án dùng voxel làm mặc định."""
    assert plan_chunk(chunk, llm=mock_llm)[0]["style"] == "voxel"


def test_style_override_still_possible(chunk, mock_llm):
    assert plan_chunk(chunk, llm=mock_llm, style="toon")[0]["style"] == "toon"


def test_plan_sample_chunk_without_cast_picks_set_from_text(chunk_sample, mock_llm):
    shots = plan_chunk(chunk_sample, llm=mock_llm)
    assert shots[0]["set"] == "bank_hall"  # "This bank keeps its gold in cheese."
    assert shots[0]["cast"] == []
    assert sum(s["duration_ms"] for s in shots) == 4200


def test_planner_goes_through_llm_port(chunk, mock_llm):
    plan_chunk(chunk, llm=mock_llm)
    adapter = mock_llm.adapters[0]
    assert len(adapter.calls) == 1
    port, req = adapter.calls[0]
    assert port == "llm_provider" and req["response_schema"]["examples"]


def test_planner_uses_llm_revision_when_valid(chunk):
    from adapters_mock import MockAdapter
    from ports import PortClient

    def revise(port, req):
        draft = copy.deepcopy(req["response_schema"]["examples"][0])
        draft["shots"][0]["camera"]["interp"] = "linear"
        return draft

    shots = plan_chunk(chunk, llm=PortClient("llm_provider", [MockAdapter(responder=revise)]))
    assert shots[0]["camera"]["interp"] == "linear"


def test_planner_falls_back_to_draft_on_invalid_llm_answer(chunk):
    from adapters_mock import MockAdapter
    from ports import PortClient

    llm = PortClient("llm_provider", [MockAdapter(responder=lambda p, r: {"shots": [{"shot_id": "x"}]})])
    shots = plan_chunk(chunk, llm=llm)
    assert validate("shot", shots[0]) == []


def test_planner_without_llm_adapter_uses_draft(chunk):
    from ports import PortClient

    shots = plan_chunk(chunk, llm=PortClient("llm_provider", []))
    assert validate("shot", shots[0]) == []


def test_plan_splits_long_chunk_at_sentences(chunk, mock_llm):
    long = dict(chunk, end_ms=chunk["start_ms"] + 9000, words=[],
                text="Câu một khá dài. Câu hai cũng dài. Câu ba kết thúc.")
    shots = plan_chunk(long, llm=mock_llm)
    assert 2 <= len(shots) <= 3
    assert sum(s["duration_ms"] for s in shots) == 9000
    assert [s["shot_id"] for s in shots] == [f"{chunk['chunk_id']}_s{i + 1}" for i in range(len(shots))]


def test_split_sentences():
    assert split_sentences("A. B! C? D") == ["A.", "B!", "C?", "D"]


# ---------------------------------------------------------------- sensitivity
def test_sensitive_chunk_hides_cast_and_picks_offscreen(chunk_sensitive, mock_llm):
    shots = plan_chunk(chunk_sensitive, llm=mock_llm)
    assert shots[0]["sensitivity_device"] == "offscreen_sound"
    assert all(m["action"] == "hidden" for m in shots[0]["cast"])


def test_sensitivity_table_uses_contract_levels():
    assert default_device("none") == "none" and default_device("high") == "offscreen_sound"
    assert "none" not in allowed_devices("medium")
    assert is_allowed("low", "cut_away") and not is_allowed("high", "none")
    with pytest.raises(ValueError):
        default_device("extreme")


def test_g7_rejects_wrong_device(chunk_sensitive, mock_llm):
    shots = plan_chunk(chunk_sensitive, llm=mock_llm)
    shots[0]["sensitivity_device"] = "none"
    assert not g7_sensitivity(GateContext(chunk_sensitive, shots, [], FPS)).passed


# ---------------------------------------------------------------- look
def test_look_profile_translates_tokens(chunk):
    look = contracts.load_look("test_warm")
    prof = build_look_profile(look, "tense")
    assert prof["background"] == look["palette"]["bg"]
    assert prof["hue_shift"] == look["emotion_map"]["tense"]["hue_shift"]
    assert prof["default_interp"] == "ease_in_out"
    assert build_look_profile(look, "unknown_emotion")["hue_shift"] == 0


def test_shift_hue():
    assert shift_hue("#ff0000", 0) == "#ff0000"
    assert shift_hue("#ff0000", 120) == "#00ff00"
    assert shift_hue("#808080", 90) == "#808080"  # màu xám không đổi


def test_bundle_applies_look(chunk, mock_llm):
    shots = plan_chunk(dict(chunk, emotion="tense"), llm=mock_llm)
    b = _bundles(dict(chunk, emotion="tense"), shots)[0]
    look = contracts.load_look("test_warm")
    assert b["style"]["renderer"]["background"] == look["palette"]["bg"]
    raw = Registry().load("cheese_vault", "set")["objects"][0]["color"]
    assert b["set"]["objects"][0]["color"] == shift_hue(raw, look["emotion_map"]["tense"]["hue_shift"])


# ---------------------------------------------------------------- gates
def test_registry_blocks_unlisted_and_noncommercial(tmp_path):
    reg = Registry()
    with pytest.raises(RegistryError):
        reg.require("unicorn")
    rows = reg.all_rows()
    rows[0] = dict(rows[0], commercial_ok=False)
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"assets": rows}), encoding="utf-8")
    with pytest.raises(RegistryError):
        Registry(p).require(rows[0]["asset_id"])


def test_pre_render_gates_pass_on_fixtures(chunk, chunk_sensitive, chunk_sample, mock_llm):
    for c in (chunk, chunk_sensitive, chunk_sample):
        shots = plan_chunk(c, llm=mock_llm)
        res = run_pre_render_gates(GateContext(c, shots, _bundles(c, shots), FPS))
        assert all(r.passed for r in res), [(r.id, r.details) for r in res if not r.passed]


def test_g5_catches_camera_through_character(chunk, mock_llm):
    shots = plan_chunk(chunk, llm=mock_llm)
    shots[0]["camera"] = {"move": "dolly", "from": [0.25, 0.9, 0.8], "to": [0.25, 0.9, -9.5],
                          "look_at": "target_empty", "interp": "linear"}
    res = {r.id: r for r in run_pre_render_gates(GateContext(chunk, shots, _bundles(chunk, shots), FPS))}
    assert not res["G5"].passed


def test_g4_requires_32_segments(chunk, mock_llm):
    shots = plan_chunk(chunk, llm=mock_llm)
    b = _bundles(chunk, shots)
    b[0]["set"]["objects"][5]["segments"] = 12
    res = {r.id: r for r in run_pre_render_gates(GateContext(chunk, shots, b, FPS))}
    assert not res["G4"].passed


def test_no_captions_gate_detects_burned_text(tmp_path, chunk_sample):
    from common.helpers import ocr_available

    if not ocr_available():
        pytest.skip("thiếu tesseract")
    img = Image.new("RGB", (1920, 1080), (60, 50, 40))
    ImageDraw.Draw(img).text((500, 900), "This bank keeps its gold", fill=(255, 255, 255),
                             font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72))
    img.save(tmp_path / "frame_00000.png")
    Image.new("RGB", (1920, 1080), (60, 50, 40)).save(tmp_path / "frame_00001.png")
    found = no_captions_in_frames(tmp_path, [0, 1], chunk_sample["text"])
    assert found and "bank" in found[0][1]


def test_bundle_tracks_cover_every_frame(chunk, mock_llm):
    b = _bundles(chunk, plan_chunk(chunk, llm=mock_llm))[0]
    n = b["render"]["n_frames"]
    assert len(b["tracks"]["camera"]) == n
    assert all(len(t) == n for t in b["tracks"]["cast"].values())
    assert b["tracks"]["visible_cast"] == ["cheesemaker"]


# ---------------------------------------------------------------- capability / rejected
def test_capability_rejects_out_of_range_chunk(chunk):
    card = load_capability_card()
    assert check_capability(card, chunk) is None
    too_long = dict(chunk, end_ms=chunk["start_ms"] + card["max_ms"] + 1)
    assert "max_ms" in check_capability(card, too_long)


def test_run_chunk_returns_rejected_without_rendering(chunk, tmp_path, mock_llm):
    card = load_capability_card()
    p = tmp_path / "long.json"
    p.write_text(json.dumps(dict(chunk, end_ms=chunk["start_ms"] + card["max_ms"] + 1)), encoding="utf-8")
    ro = run_chunk(p, out_root=tmp_path / "out", llm=mock_llm)
    assert ro["status"] == "rejected" and ro["video_path"] is None and ro["frames"] == 0
    assert validate("render_output", ro) == []
    assert not list((tmp_path / "out").rglob("*.mp4"))
