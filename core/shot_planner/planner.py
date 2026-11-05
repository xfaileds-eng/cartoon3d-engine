"""shot_planner: chunk_input.json → danh sách shot.json.

Bản này là bộ luật tất định (deterministic) làm nền; Claude có thể sửa tay shot.json
trước khi render, miễn vẫn qua schema và 8 cổng. Mọi tham số máy quay được điền đủ
từ camera_presets của set để shot.json tự đứng được, không phụ thuộc planner.
"""
from __future__ import annotations

import re
from typing import Any

from ..camera_library import MOVES, fill_from_preset
from ..registry import Registry
from ..sensitivity import default_device, device_spec

MIN_SHOT_MS = 1500
SPLIT_ABOVE_MS = 6000
MAX_SHOTS = 3
_SENT_RE = re.compile(r"[^.!?…]+[.!?…]*")


def split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENT_RE.findall(text)]
    return [p for p in parts if p]


def _sentence_boundaries_ms(chunk: dict[str, Any], sentences: list[str]) -> list[int]:
    """Mốc kết thúc (tương đối) của từng câu; dùng timeline từ nếu có, không thì theo số chữ."""
    start, end = chunk["start_ms"], chunk["end_ms"]
    duration = end - start
    words = chunk.get("words") or []
    if words:
        # Ghép từ theo thứ tự vào từng câu theo số từ của câu.
        bounds, idx = [], 0
        for s in sentences:
            n = len(s.split())
            idx = min(idx + n, len(words))
            bounds.append(min(duration, max(0, words[idx - 1]["end_ms"] - start)))
        bounds[-1] = duration
        return bounds
    total_chars = sum(len(s) for s in sentences) or 1
    acc, bounds = 0, []
    for s in sentences:
        acc += len(s)
        bounds.append(round(duration * acc / total_chars))
    bounds[-1] = duration
    return bounds


def _segments(chunk: dict[str, Any]) -> list[tuple[int, str]]:
    """[(duration_ms, text)] cho từng shot."""
    duration = chunk["end_ms"] - chunk["start_ms"]
    sentences = split_sentences(chunk["text"])
    if duration <= SPLIT_ABOVE_MS or len(sentences) < 2:
        return [(duration, chunk["text"])]
    bounds = _sentence_boundaries_ms(chunk, sentences)
    segs: list[tuple[int, str]] = []
    prev = 0
    for s, b in zip(sentences, bounds):
        d = b - prev
        if segs and d < MIN_SHOT_MS:
            pd, pt = segs[-1]
            segs[-1] = (pd + d, pt + " " + s)
        else:
            segs.append((d, s))
        prev = b
    while len(segs) > MAX_SHOTS:
        # Gộp hai shot ngắn nhất kề nhau.
        i = min(range(len(segs) - 1), key=lambda k: segs[k][0] + segs[k + 1][0])
        segs[i : i + 2] = [(segs[i][0] + segs[i + 1][0], segs[i][1] + " " + segs[i + 1][1])]
    if segs[0][0] < MIN_SHOT_MS and len(segs) > 1:
        segs[0:2] = [(segs[0][0] + segs[1][0], segs[0][1] + " " + segs[1][1])]
    return segs


def _pick_set(chunk: dict[str, Any], characters: dict[str, dict[str, Any]]) -> str:
    if chunk.get("set_hint"):
        return chunk["set_hint"]
    for cid in chunk["cast_refs"]:
        if characters[cid].get("default_set"):
            return characters[cid]["default_set"]
    raise ValueError("chunk không có set_hint và nhân vật không có default_set: không chọn được bối cảnh")


def _cast_for(chunk: dict[str, Any], characters: dict[str, Any], set_data: dict[str, Any],
              device: str, shot_index: int) -> list[dict[str, Any]]:
    spec = device_spec(device)
    hide = bool(spec.get("hide_cast"))
    paths = list(set_data.get("paths", {}).keys())
    points = set_data.get("points", {})
    cast = []
    for k, cid in enumerate(chunk["cast_refs"]):
        ch = characters[cid]
        member: dict[str, Any] = {"id": cid}
        if hide:
            member["action"] = "hidden"
        elif k == 0 and paths and ch.get("rig") != "voxel_static":
            member["action"] = "walk_carry" if ch.get("default_props") else "walk"
            member["path"] = paths[0]
            if member["action"] == "walk_carry":
                member["props"] = list(ch["default_props"][:1])
        else:
            member["action"] = "idle" if shot_index == 0 else "talk"
            marks = [p for p in points if p != "entry"]
            if marks:
                member["at"] = marks[k % len(marks)]
            member["face"] = 180.0
        cast.append(member)
    return cast


def _camera_for(move: str, set_data: dict[str, Any], cast: list[dict[str, Any]], device: str) -> dict[str, Any]:
    cam: dict[str, Any] = {"move": move}
    visible = [c["id"] for c in cast if c["action"] != "hidden"]
    if device == "cut_away":
        visible = []  # máy quay rời chủ thể: nhìn vào điểm của bối cảnh, không bám nhân vật
    if move == "track_to":
        if not visible:
            cam = {"move": "dolly"}
        else:
            cam["target"] = visible[0]
            cam["look_at"] = visible[0]
    elif move == "cut" and visible:
        # Cắt cảnh nhiều góc: máy luôn nhìn vào nhân vật đầu tiên để chủ thể không rơi khỏi khung (G5).
        cam["look_at"] = visible[0]
    cam = fill_from_preset(cam, set_data)
    if "look_at" not in cam:
        cam["look_at"] = next(iter(set_data.get("points", {"origin": [0, 1, 0]})))
    # Chỉ giữ tham số của move này để shot.json gọn và qua schema.
    keep = set(MOVES["moves"][cam["move"]]["params"]) | {"move", "look_at", "interp", "fov_deg", "target", "cut_at_ms"}
    return {k: v for k, v in cam.items() if k in keep}


def plan_chunk(chunk: dict[str, Any], registry: Registry | None = None) -> list[dict[str, Any]]:
    registry = registry or Registry()
    characters = {cid: registry.load(cid, "character") for cid in chunk["cast_refs"]}
    set_id = _pick_set(chunk, characters)
    set_data = registry.load(set_id, "set")
    level = int(chunk["sensitivity"])
    device = default_device(level)
    base_move = MOVES["emotion_to_move"].get(chunk["emotion"], "dolly")
    override = device_spec(device).get("camera_override")
    if override == "cut":
        base_move = "cut"
    moves_cycle = [base_move, "track_to", "orbit"]
    has_words = bool(chunk.get("words"))

    shots = []
    for i, (dur, text) in enumerate(_segments(chunk)):
        cast = _cast_for(chunk, characters, set_data, device, i)
        move = moves_cycle[i % len(moves_cycle)] if i else base_move
        if override == "cut":
            move = "cut"
        shots.append({
            "shot_id": f"{chunk['chunk_id']}_s{i + 1}",
            "duration_ms": int(dur),
            "style": chunk["style"],
            "set": set_id,
            "cast": cast,
            "camera": _camera_for(move, set_data, cast, device),
            "captions": {"mode": "word_pop" if has_words else "none"},
            "sensitivity_device": device,
            "notes": text,
        })
    assert sum(s["duration_ms"] for s in shots) == chunk["end_ms"] - chunk["start_ms"]
    return shots
