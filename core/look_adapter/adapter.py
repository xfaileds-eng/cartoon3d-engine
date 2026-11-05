"""look_adapter: dịch token của look (engine-contracts/looks/<look_id>.json) sang màu vật liệu và nét viền.

Lớp đầu vào của Look system. Engine chỉ dịch các token sau; phần còn lại do look_pass ở khâu ghép làm
(LUT, hạt, vignette, chuyển cảnh, phụ đề), engine KHÔNG làm lại để tránh áp hai lần:
  palette.bg                        → nền cảnh
  emotion_map.<emotion>.hue_shift   → xoay sắc độ toàn bộ màu vật liệu (độ)
  palette.shadow (nếu có)           → màu nét viền
  stroke.width_scale (nếu có)       → hệ số độ dày nét viền (look chưa có token này thì 1.0)
  motion.default_interp             → nội suy mặc định của máy quay (trừ move `cut`)
Màu được đổi ngay trong Python trước khi ghi scene_bundle, nên hai backend ra cùng một màu.
"""
from __future__ import annotations

import colorsys
import copy
from typing import Any


def shift_hue(hex_color: str, degrees: float) -> str:
    """Xoay sắc độ (HLS) của một màu #rrggbb; màu xám giữ nguyên."""
    if not degrees:
        return hex_color.lower()
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((hue + degrees / 360.0) % 1.0, light, sat)
    return "#{:02x}{:02x}{:02x}".format(*(round(v * 255) for v in (r, g, b)))


def build_look_profile(look: dict[str, Any], emotion: str) -> dict[str, Any]:
    emo = look.get("emotion_map", {}).get(emotion, {})
    palette = look.get("palette", {})
    return {
        "look_id": look["look_id"],
        "background": palette.get("bg"),
        "accent": palette.get("accent"),
        "outline_color": palette.get("shadow"),
        "outline_width_scale": float(look.get("stroke", {}).get("width_scale", 1.0)),
        "hue_shift": float(emo.get("hue_shift", 0)),
        "tempo": float(emo.get("tempo", 1.0)),
        "cut_rate": float(emo.get("cut_rate", 1.0)),
        "default_interp": look.get("motion", {}).get("default_interp"),
    }


def _recolor(objs: list[dict[str, Any]], deg: float) -> None:
    for o in objs:
        for key in ("color", "emissive"):
            if isinstance(o.get(key), str) and o[key].startswith("#"):
                o[key] = shift_hue(o[key], deg)


def apply_look(profile: dict[str, Any], style: dict[str, Any], set_data: dict[str, Any],
               characters: dict[str, Any], props: dict[str, Any]) -> tuple[dict, dict, dict, dict]:
    """Trả về bản sao đã dịch look của (style, set, characters, props); không sửa dữ liệu gốc."""
    style, set_data = copy.deepcopy(style), copy.deepcopy(set_data)
    characters, props = copy.deepcopy(characters), copy.deepcopy(props)
    deg = profile["hue_shift"]

    if profile.get("background"):
        style["renderer"]["background"] = profile["background"]
    outline = style.get("material", {}).get("outline")
    if outline:
        if profile.get("outline_color"):
            outline["color"] = profile["outline_color"]
        if "width" in outline:
            outline["width"] = round(outline["width"] * profile["outline_width_scale"], 5)

    _recolor(set_data.get("objects", []), deg)
    for prop in props.values():
        _recolor(prop.get("objects", []), deg)
    for ch in characters.values():
        _recolor(list(ch.get("parts", {}).values()), deg)
        if "face" in ch:
            ch["face"] = {k: shift_hue(v, deg) if isinstance(v, str) else v for k, v in ch["face"].items()}
        if "voxels" in ch:
            ch["voxels"] = [[x, y, z, shift_hue(c, deg)] for x, y, z, c in ch["voxels"]]
    return style, set_data, characters, props
