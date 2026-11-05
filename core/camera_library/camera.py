"""Thư viện máy quay: nội suy theo tên của Blender và tính vị trí máy từng khung.

Python là nguồn sự thật: track máy quay được tính ở đây, ghi vào scene_bundle, và cả
Three.js lẫn Blender chỉ đọc lại. Nhờ vậy cổng G5 kiểm đúng cái đã render.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

Vec3 = tuple[float, float, float]

_MOVES_PATH = Path(__file__).with_name("moves.json")
MOVES: dict[str, Any] = json.loads(_MOVES_PATH.read_text(encoding="utf-8"))


def _ease_in(t: float) -> float:
    return t * t


def _ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def _ease_in_out(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2


def _constant(t: float) -> float:
    return 1.0 if t >= 1.0 else 0.0


def _bounce(t: float) -> float:
    # Blender "bounce" ease-out (Robert Penner): nảy tắt dần về 1.
    n1, d1 = 7.5625, 2.75
    if t < 1 / d1:
        return n1 * t * t
    if t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


INTERP: dict[str, Callable[[float], float]] = {
    "linear": lambda t: t,
    "ease_in": _ease_in,
    "ease_out": _ease_out,
    "ease_in_out": _ease_in_out,
    "constant": _constant,
    "bounce": _bounce,
}


def interp(name: str, t: float) -> float:
    """f(t) với t ∈ [0, 1]. Tên theo Blender; tên lạ → lỗi ngay, không âm thầm dùng linear."""
    if name not in INTERP:
        raise ValueError(f"interp '{name}' không có trong thư viện; dùng tên của Blender: {sorted(INTERP)}")
    t = min(1.0, max(0.0, t))
    return INTERP[name](t)


def lerp3(a: Sequence[float], b: Sequence[float], f: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


@dataclass
class CameraPose:
    position: Vec3
    look_at: Vec3
    fov_deg: float

    def as_dict(self) -> dict[str, Any]:
        return {"position": [round(v, 5) for v in self.position],
                "look_at": [round(v, 5) for v in self.look_at],
                "fov_deg": self.fov_deg}


def resolve_point(ref: Any, set_data: dict[str, Any], cast_centers: dict[str, Vec3]) -> Vec3:
    """look_at / điểm đứng: toạ độ, tên điểm trong set.points, hoặc id nhân vật (tâm thân)."""
    if isinstance(ref, (list, tuple)):
        if len(ref) != 3:
            raise ValueError(f"toạ độ phải có 3 thành phần: {ref}")
        return (float(ref[0]), float(ref[1]), float(ref[2]))
    if isinstance(ref, str):
        if ref in cast_centers:
            return cast_centers[ref]
        points = set_data.get("points", {})
        if ref in points:
            p = points[ref]
            return (float(p[0]), float(p[1]), float(p[2]))
        raise KeyError(f"'{ref}' không phải điểm của set '{set_data.get('asset_id')}' cũng không phải nhân vật trong shot")
    raise TypeError(f"look_at không hợp lệ: {ref!r}")


def fill_from_preset(camera: dict[str, Any], set_data: dict[str, Any]) -> dict[str, Any]:
    """Điền tham số còn thiếu từ camera_presets của set rồi từ mặc định của move."""
    move = camera["move"]
    if move not in MOVES["moves"]:
        raise ValueError(f"move '{move}' không có trong camera_library")
    out = dict(camera)
    preset = set_data.get("camera_presets", {}).get(move, {})
    for k, v in preset.items():
        out.setdefault(k, v)
    for k, v in MOVES["moves"][move]["defaults"].items():
        out.setdefault(k, v)
    missing = [p for p in MOVES["moves"][move]["params"] if p not in out and p not in ("cut_at_ms", "target")]
    if missing:
        raise ValueError(f"camera {move} thiếu tham số {missing} (không có trong shot lẫn camera_presets của set)")
    return out


def camera_track(
    camera: dict[str, Any],
    set_data: dict[str, Any],
    cast_tracks: dict[str, list[dict[str, Any]]],
    cast_heights: dict[str, float],
    n_frames: int,
    duration_ms: int,
) -> list[CameraPose]:
    """Vị trí + điểm nhìn của máy quay cho từng khung của shot.

    cast_tracks: id → [{position:[x,y,z]} mỗi khung], vị trí chân nhân vật.
    cast_heights: id → chiều cao (m) để lấy tâm thân = chân + 0.5·cao.
    """
    from ..timing import frame_time

    cam = fill_from_preset(camera, set_data)
    move = cam["move"]
    f = cam["interp"]
    fov = float(cam.get("fov_deg", 45))
    poses: list[CameraPose] = []

    def centers_at(i: int) -> dict[str, Vec3]:
        out: dict[str, Vec3] = {}
        for cid, track in cast_tracks.items():
            p = track[i]["position"]
            out[cid] = (p[0], p[1] + 0.5 * cast_heights.get(cid, 1.7), p[2])
        return out

    for i in range(n_frames):
        t = frame_time(i, n_frames)
        centers = centers_at(i)
        if move == "dolly":
            pos = lerp3(cam["from"], cam["to"], interp(f, t))
            look = resolve_point(cam["look_at"], set_data, centers)
        elif move == "orbit":
            a = math.radians(cam["start_deg"] + (cam["end_deg"] - cam["start_deg"]) * interp(f, t))
            c = cam["center"]
            pos = (c[0] + cam["radius"] * math.cos(a), float(cam["height"]), c[2] + cam["radius"] * math.sin(a))
            look = resolve_point(cam.get("look_at", c), set_data, centers)
        elif move == "track_to":
            target = cam.get("target") or next(iter(cast_tracks), None)
            if target is None or target not in cast_tracks:
                raise ValueError("track_to cần 'target' là một nhân vật có trong shot")
            root = cast_tracks[target][i]["position"]
            off = cam["offset"]
            pos = (root[0] + off[0], root[1] + off[1], root[2] + off[2])
            look = centers[target] if cam.get("look_at") in (None, target) else resolve_point(cam["look_at"], set_data, centers)
        elif move == "cut":
            positions = cam["positions"]
            cuts = cam.get("cut_at_ms")
            if not cuts:
                cuts = [round(k * duration_ms / len(positions)) for k in range(len(positions))]
            ms = t * duration_ms
            k = 0
            for idx, c_ms in enumerate(cuts):
                if ms >= c_ms:
                    k = idx
            k = min(k, len(positions) - 1)
            p = positions[k]
            pos = (float(p[0]), float(p[1]), float(p[2]))
            look = resolve_point(cam["look_at"], set_data, centers)
        else:  # pragma: no cover
            raise ValueError(move)
        poses.append(CameraPose(pos, look, fov))
    return poses
