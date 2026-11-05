"""shot_planner: chunk_input.json → danh sách shot.json.

Hai bước:
  1. Bản nháp tất định (luật): chia câu, chọn bối cảnh, máy quay, thủ pháp nhạy cảm.
  2. Gửi bản nháp qua port `llm_provider` (Claude ở máy thật, mock trong test) để chỉnh. Câu trả lời phải
     đúng shot.schema.json và giữ tổng thời lượng; sai thì giữ bản nháp. Không gọi thẳng API nào.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from typing import Any

from .. import config, contracts
from ..camera_library import MOVES, fill_from_preset
from ..look_adapter import build_look_profile
from ..registry import Registry
from ..sensitivity import default_device, device_spec

MIN_SHOT_MS = 1500
SPLIT_ABOVE_MS = 6000
MAX_SHOTS = 3
_SENT_RE = re.compile(r"[^.!?…]+[.!?…]*")

SYSTEM_PROMPT = (
    "Bạn là đạo diễn hình ảnh của một engine hoạt hình 3D dựng bằng code. Nhận chunk lời thoại và bản nháp "
    "danh sách shot. Chỉ được chỉnh máy quay (move, interp, look_at), hành động nhân vật và bối cảnh trong "
    "thư viện có sẵn; giữ nguyên shot_id, duration_ms, look_id và sensitivity_device. Trả về JSON đúng schema."
)


def _log(msg: str) -> None:
    print(f"[cartoon3d] {msg}", file=sys.stderr, flush=True)


def split_sentences(text: str) -> list[str]:
    return [p for p in (s.strip() for s in _SENT_RE.findall(text)) if p]


def _sentence_boundaries_ms(chunk: dict[str, Any], sentences: list[str]) -> list[int]:
    start, duration = chunk["start_ms"], chunk["end_ms"] - chunk["start_ms"]
    words = chunk.get("words") or []
    if words:
        bounds, idx = [], 0
        for s in sentences:
            idx = min(idx + len(s.split()), len(words))
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
    duration = chunk["end_ms"] - chunk["start_ms"]
    sentences = split_sentences(chunk["text"])
    if duration <= SPLIT_ABOVE_MS or len(sentences) < 2:
        return [(duration, chunk["text"])]
    segs: list[tuple[int, str]] = []
    prev = 0
    for s, b in zip(sentences, _sentence_boundaries_ms(chunk, sentences)):
        d = b - prev
        if segs and d < MIN_SHOT_MS:
            segs[-1] = (segs[-1][0] + d, segs[-1][1] + " " + s)
        else:
            segs.append((d, s))
        prev = b
    while len(segs) > MAX_SHOTS:
        i = min(range(len(segs) - 1), key=lambda k: segs[k][0] + segs[k + 1][0])
        segs[i:i + 2] = [(segs[i][0] + segs[i + 1][0], segs[i][1] + " " + segs[i + 1][1])]
    if segs[0][0] < MIN_SHOT_MS and len(segs) > 1:
        segs[0:2] = [(segs[0][0] + segs[1][0], segs[0][1] + " " + segs[1][1])]
    return segs


def pick_set(chunk: dict[str, Any], characters: dict[str, dict[str, Any]], registry: Registry) -> str:
    """Bối cảnh: default_set của nhân vật đầu; không có nhân vật thì khớp từ khoá của set với lời thoại."""
    for cid in chunk["cast_refs"]:
        if characters[cid].get("default_set"):
            return characters[cid]["default_set"]
    text = chunk["text"].lower()
    best: tuple[int, int, str] | None = None
    sets = [r["asset_id"] for r in registry.all_rows() if r["kind"] == "set"]
    for sid in sets:
        hits = [text.find(k.lower()) for k in registry.load(sid, "set").get("keywords", []) if k.lower() in text]
        if hits:
            key = (-len(hits), min(hits), sid)  # nhiều từ khoá hơn thắng, hoà thì từ xuất hiện sớm hơn
            best = key if best is None or key < best else best
    if best:
        return best[2]
    if not sets:
        raise ValueError("registry không có bối cảnh nào")
    return sets[0]


def _cast_for(chunk, characters, set_data, device: str, shot_index: int) -> list[dict[str, Any]]:
    hide = bool(device_spec(device).get("hide_cast"))
    paths = list(set_data.get("paths", {}))
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


def _camera_for(move: str, set_data, cast, device: str, look_interp: str | None) -> dict[str, Any]:
    visible = [] if device == "cut_away" else [c["id"] for c in cast if c["action"] != "hidden"]
    cam: dict[str, Any] = {"move": move}
    if move == "track_to":
        if visible:
            cam.update(target=visible[0], look_at=visible[0])
        else:
            cam = {"move": "dolly"}
    elif move == "cut" and visible:
        cam["look_at"] = visible[0]  # cắt nhiều góc nhưng luôn nhìn chủ thể (G5)
    if look_interp and cam["move"] != "cut":
        cam["interp"] = look_interp
    cam = fill_from_preset(cam, set_data)
    if "look_at" not in cam:
        cam["look_at"] = next(iter(set_data.get("points", {"origin": [0, 1, 0]})))
    keep = set(MOVES["moves"][cam["move"]]["params"]) | {"move", "look_at", "interp", "fov_deg", "target", "cut_at_ms"}
    return {k: v for k, v in cam.items() if k in keep}


def draft_plan(chunk: dict[str, Any], registry: Registry | None = None,
               style: str = config.DEFAULT_STYLE) -> list[dict[str, Any]]:
    registry = registry or Registry()
    characters = {cid: registry.load(cid, "character") for cid in chunk["cast_refs"]}
    set_id = pick_set(chunk, characters, registry)
    set_data = registry.load(set_id, "set")
    device = default_device(chunk["sensitivity"])
    profile = build_look_profile(contracts.load_look(chunk["look_id"]), chunk["emotion"])
    base_move = MOVES["emotion_to_move"].get(chunk["emotion"], MOVES["default_move"])
    if device_spec(device).get("camera_override") == "cut":
        base_move = "cut"
    cycle = [base_move, "track_to", "orbit"]

    shots = []
    for i, (dur, text) in enumerate(_segments(chunk)):
        cast = _cast_for(chunk, characters, set_data, device, i)
        move = "cut" if base_move == "cut" else cycle[i % len(cycle)]
        shots.append({
            "shot_id": f"{chunk['chunk_id']}_s{i + 1}",
            "duration_ms": int(dur),
            "style": style,
            "set": set_id,
            "cast": cast,
            "camera": _camera_for(move, set_data, cast, device, profile["default_interp"]),
            "look_id": chunk["look_id"],
            "sensitivity_device": device,
            "notes": text,
        })
    assert sum(s["duration_ms"] for s in shots) == chunk["end_ms"] - chunk["start_ms"]
    return shots


def _response_schema(draft: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["shots"],
        "properties": {"shots": {"type": "array", "minItems": 1, "items": contracts.load_schema("shot")}},
        "examples": [{"shots": copy.deepcopy(draft)}],
    }


def _accept(chunk: dict[str, Any], draft: list[dict[str, Any]], answer: Any, registry: Registry) -> list[str]:
    """Lý do không nhận câu trả lời của LLM; rỗng = nhận."""
    from ..qa_gates.gates import validate

    if not isinstance(answer, dict) or not isinstance(answer.get("shots"), list) or not answer["shots"]:
        return ["câu trả lời không có danh sách shots"]
    errs = []
    for s in answer["shots"]:
        errs += [f"{s.get('shot_id', '?')}: {e}" for e in validate("shot", s)]
    if errs:
        return errs
    shots = answer["shots"]
    if sum(s["duration_ms"] for s in shots) != chunk["end_ms"] - chunk["start_ms"]:
        errs.append("tổng duration_ms lệch thời lượng chunk")
    if [s["shot_id"] for s in shots] != [s["shot_id"] for s in draft]:
        errs.append("shot_id bị đổi")
    for s, d in zip(shots, draft):
        for key in ("look_id", "sensitivity_device"):
            if s[key] != d[key]:
                errs.append(f"{s['shot_id']}: không được đổi {key}")
        try:
            registry.require(s["set"], "set")
            for m in s["cast"]:
                registry.require(m["id"], "character")
        except KeyError as e:
            errs.append(str(e))
    return errs


def plan_chunk(chunk: dict[str, Any], registry: Registry | None = None, *, llm=None,
               style: str = config.DEFAULT_STYLE) -> list[dict[str, Any]]:
    """llm: PortClient của port llm_provider; None → tự dựng theo providers.yaml."""
    registry = registry or Registry()
    draft = draft_plan(chunk, registry, style)
    if llm is None:
        from ..providers import port_client

        llm = port_client("llm_provider")
    request = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"chunk": chunk, "draft": draft}, ensure_ascii=False)},
        ],
        "response_schema": _response_schema(draft),
    }
    env = llm.call(request)
    if env["status"] != "ok":
        _log(f"llm_provider {env['status']} ({env.get('error', env['provider'])}): dùng bản nháp tất định")
        return draft
    errs = _accept(chunk, draft, env["data"], registry)
    if errs:
        _log(f"llm_provider trả shot không hợp lệ, giữ bản nháp: {errs[:3]}")
        return draft
    return env["data"]["shots"]
