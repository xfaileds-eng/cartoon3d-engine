import json

import pytest

from core.captions import build_caption_plan
from core.qa_gates import GateContext, run_pre_render_gates
from core.qa_gates.gates import g7_sensitivity, g8_captions, validate
from core.registry import Registry, RegistryError
from core.scene_bundle import build_bundle
from core.sensitivity import allowed_devices, default_device, is_allowed
from core.shot_planner import plan_chunk, split_sentences
from core.timing import allocate_frames, frames_for


def _bundles(chunk, shots, w=640, h=360):
    fps = chunk.get("fps", 24)
    return [build_bundle(s, chunk, n, width=w, height=h, fps=fps)
            for s, n in zip(shots, allocate_frames([s["duration_ms"] for s in shots], fps))]


def test_plan_cheese_bank_matches_spec_example(chunk, shot_example):
    shots = plan_chunk(chunk)
    assert len(shots) == 1
    s = shots[0]
    assert validate("shot", s) == []
    assert s["shot_id"] == shot_example["shot_id"]
    assert s["set"] == "cheese_vault" and s["style"] == "toon"
    assert s["cast"][0]["action"] == "walk_carry" and s["cast"][0]["props"] == ["cheese_wheel"]
    assert s["camera"]["move"] == "dolly" and s["camera"]["interp"] == "ease_in_out"
    assert s["captions"]["mode"] == "word_pop" and s["sensitivity_device"] == "none"


def test_plan_splits_long_chunk_at_sentences(chunk):
    long = dict(chunk, end_ms=chunk["start_ms"] + 9000, words=None,
                text="Câu một khá dài. Câu hai cũng dài. Câu ba kết thúc.")
    long.pop("words")
    shots = plan_chunk(long)
    assert 2 <= len(shots) <= 3
    assert sum(s["duration_ms"] for s in shots) == 9000
    assert [s["shot_id"] for s in shots] == [f"{chunk['chunk_id']}_s{i + 1}" for i in range(len(shots))]


def test_split_sentences():
    assert split_sentences("A. B! C? D") == ["A.", "B!", "C?", "D"]


def test_sensitive_chunk_hides_cast_and_picks_offscreen(chunk_sensitive):
    shots = plan_chunk(chunk_sensitive)
    assert shots[0]["sensitivity_device"] == "offscreen_sound"
    assert all(m["action"] == "hidden" for m in shots[0]["cast"])


def test_sensitivity_table():
    assert default_device(0) == "none" and default_device(3) == "offscreen_sound"
    assert "none" not in allowed_devices(2)
    assert is_allowed(1, "cut_away") and not is_allowed(3, "none")
    with pytest.raises(ValueError):
        default_device(7)


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


def test_pre_render_gates_pass_on_fixtures(chunk, chunk_sensitive):
    for c in (chunk, chunk_sensitive):
        shots = plan_chunk(c)
        res = run_pre_render_gates(GateContext(c, shots, _bundles(c, shots), c["fps"]))
        assert all(r.passed for r in res), [(r.id, r.details) for r in res if not r.passed]


def test_g7_rejects_wrong_device(chunk_sensitive):
    shots = plan_chunk(chunk_sensitive)
    shots[0]["sensitivity_device"] = "none"
    r = g7_sensitivity(GateContext(chunk_sensitive, shots, [], 24))
    assert not r.passed


def test_g5_catches_camera_through_character(chunk):
    shots = plan_chunk(chunk)
    # Máy quay đặt đúng vị trí nhân vật đang đi → xuyên người
    shots[0]["camera"] = {"move": "dolly", "from": [0.25, 0.9, 0.8], "to": [0.25, 0.9, -9.5],
                          "look_at": "target_empty", "interp": "linear"}
    res = {r.id: r for r in run_pre_render_gates(GateContext(chunk, shots, _bundles(chunk, shots), 24))}
    assert not res["G5"].passed


def test_g4_requires_32_segments(chunk):
    shots = plan_chunk(chunk)
    b = _bundles(chunk, shots)
    b[0]["set"]["objects"][5]["segments"] = 12
    res = {r.id: r for r in run_pre_render_gates(GateContext(chunk, shots, b, 24))}
    assert not res["G4"].passed


def test_caption_plan_matches_srt_and_safe_area(chunk):
    n = frames_for(chunk["end_ms"] - chunk["start_ms"], 24)
    plan = build_caption_plan(chunk, 24, 1920, 1080, n)
    assert len(plan["items"]) == len(chunk["words"])
    ctx = GateContext(chunk, plan_chunk(chunk), [], 24, caption_plan=plan)
    r = g8_captions(ctx)
    assert r.passed, r.details
    assert plan["items"][0]["start_frame"] == 0
    assert all(it["end_frame"] <= n for it in plan["items"])


def test_bundle_tracks_cover_every_frame(chunk):
    shots = plan_chunk(chunk)
    b = _bundles(chunk, shots)[0]
    n = b["render"]["n_frames"]
    assert len(b["tracks"]["camera"]) == n
    assert all(len(t) == n for t in b["tracks"]["cast"].values())
    assert b["tracks"]["visible_cast"] == ["cheesemaker"]
