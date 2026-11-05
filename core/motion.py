"""Vị trí gốc (chân) và hướng quay của từng nhân vật theo khung, tính trước khi render."""
from __future__ import annotations

import math
from typing import Any

from .timing import frame_time

MOVING_ACTIONS = {"walk", "walk_carry"}


def _polyline_length(pts: list[list[float]]) -> tuple[float, list[float]]:
    seg = []
    for a, b in zip(pts, pts[1:]):
        seg.append(math.dist(a, b))
    return sum(seg), seg


def point_on_path(pts: list[list[float]], s: float) -> tuple[list[float], float]:
    """Điểm cách đầu đường s (m) và góc quay (độ, quanh Y) theo hướng đi."""
    total, seg = _polyline_length(pts)
    s = min(max(0.0, s), total)
    acc = 0.0
    for (a, b), length in zip(zip(pts, pts[1:]), seg):
        if acc + length >= s or length == 0:
            f = 0.0 if length == 0 else (s - acc) / length
            p = [a[k] + (b[k] - a[k]) * f for k in range(3)]
            yaw = math.degrees(math.atan2(b[0] - a[0], b[2] - a[2]))
            return p, yaw
        acc += length
    last = pts[-1]
    a, b = pts[-2], pts[-1]
    return list(last), math.degrees(math.atan2(b[0] - a[0], b[2] - a[2]))


def cast_track(member: dict[str, Any], set_data: dict[str, Any], n_frames: int) -> list[dict[str, Any]]:
    """[{position, yaw_deg, phase}] mỗi khung. phase = pha bước chân 0..1 để backend vung tay chân."""
    action = member["action"]
    track = []
    if action in MOVING_ACTIONS:
        path_name = member.get("path")
        paths = set_data.get("paths", {})
        if not path_name or path_name not in paths:
            raise KeyError(f"nhân vật '{member['id']}' hành động {action} cần 'path' có trong set.paths {sorted(paths)}")
        pts = paths[path_name]
        total, _ = _polyline_length(pts)
        stride = 0.7  # m mỗi bước
        for i in range(n_frames):
            t = frame_time(i, n_frames)
            p, yaw = point_on_path(pts, t * total)
            track.append({"position": [round(v, 5) for v in p], "yaw_deg": round(yaw, 3),
                          "phase": round((t * total / stride) % 1.0, 5)})
        return track

    # Đứng yên: điểm 'at' trong set, hoặc đầu đường 'path', hoặc điểm 'entry', hoặc gốc.
    points = set_data.get("points", {})
    if member.get("at"):
        if member["at"] not in points:
            raise KeyError(f"'{member['at']}' không có trong set.points")
        p = list(points[member["at"]])
    elif member.get("path") and member["path"] in set_data.get("paths", {}):
        p = list(set_data["paths"][member["path"]][0])
    elif "entry" in points:
        p = list(points["entry"])
    else:
        p = [0.0, 0.0, 0.0]
    p[1] = 0.0 if action != "sit" else 0.0
    yaw = float(member.get("face", 180.0))
    for i in range(n_frames):
        track.append({"position": [round(v, 5) for v in p], "yaw_deg": yaw,
                      "phase": round(frame_time(i, n_frames), 5)})
    return track
