"""scene_bundle: gom shot + tài sản + phong cách + track từng khung thành MỘT file JSON.

Cả hai backend chỉ đọc bundle này; cổng G4/G5 cũng đọc nó trước khi render.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .camera_library import camera_track
from .camera_library.camera import CameraPose
from .look_adapter import apply_look, build_look_profile
from .motion import cast_track
from .registry import Registry, load_style
from .sensitivity import device_spec

BUNDLE_VERSION = 1


def _top_down_track(set_data: dict[str, Any], cast_tracks: dict[str, Any], n_frames: int) -> list[CameraPose]:
    """Thủ pháp top_down_diagram: máy treo ngay trên nhân vật đầu tiên (bám theo từng khung), nhìn thẳng xuống."""
    height = set_data["bounds"]["max"][1] - 0.3
    if cast_tracks:
        first = next(iter(cast_tracks.values()))
        poses = []
        for i in range(n_frames):
            cx, cz = first[i]["position"][0], first[i]["position"][2]
            poses.append(CameraPose((cx, height, cz + 0.001), (cx, 0.0, cz), 60.0))
        return poses
    b = set_data["bounds"]
    cx, cz = (b["min"][0] + b["max"][0]) / 2, (b["min"][2] + b["max"][2]) / 2
    return [CameraPose((cx, height, cz + 0.001), (cx, 0.0, cz), 60.0) for _ in range(n_frames)]


def build_bundle(
    shot: dict[str, Any],
    chunk: dict[str, Any],
    n_frames: int,
    *,
    look: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    registry: Registry | None = None,
) -> dict[str, Any]:
    registry = registry or Registry()
    set_data = registry.load(shot["set"], "set")
    style = load_style(shot["style"])
    characters = {m["id"]: registry.load(m["id"], "character") for m in shot["cast"]}
    props: dict[str, Any] = {}
    for m in shot["cast"]:
        for pid in m.get("props", []):
            props[pid] = registry.load(pid, "prop")
    device = shot["sensitivity_device"]
    spec = device_spec(device)
    if spec.get("symbol") and props == {}:
        # symbol_object cần một đồ vật tượng trưng: lấy default_props của nhân vật đầu.
        for m in shot["cast"]:
            for pid in characters[m["id"]].get("default_props", []):
                props[pid] = registry.load(pid, "prop")
                break
            if props:
                break

    tracks_cast = {m["id"]: cast_track(m, set_data, n_frames) for m in shot["cast"]}
    heights = {cid: float(ch.get("height_m", 1.7)) for cid, ch in characters.items()}
    visible_tracks = {cid: tr for cid, tr in tracks_cast.items()
                      if next(m for m in shot["cast"] if m["id"] == cid)["action"] != "hidden"}

    if spec.get("camera_override") == "top_down":
        cam_poses = _top_down_track(set_data, tracks_cast, n_frames)
    else:
        cam_poses = camera_track(shot["camera"], set_data, tracks_cast, heights, n_frames, shot["duration_ms"])

    profile = build_look_profile(look, chunk["emotion"])
    style, set_data, characters, props = apply_look(profile, style, set_data, characters, props)

    return {
        "bundle_version": BUNDLE_VERSION,
        "chunk_id": chunk["chunk_id"],
        "shot": shot,
        "render": {"fps": fps, "width": width, "height": height, "n_frames": n_frames,
                   "aspect": width / height},
        "style": style,
        "set": set_data,
        "characters": characters,
        "props": props,
        "look": profile,
        "sensitivity": {"level": chunk["sensitivity"], "device": device, "spec": spec},
        "tracks": {
            "camera": [p.as_dict() for p in cam_poses],
            "cast": tracks_cast,
            "visible_cast": sorted(visible_tracks),
        },
    }


def write_bundle(bundle: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path
