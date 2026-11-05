"""Phụ đề từng chữ: lập kế hoạch (từ → khung, hộp chữ) rồi vẽ lên khung hình bằng Pillow.

Chạy sau render, chung cho mọi backend. Kế hoạch được ghi ra captions_plan.json để cổng G8 so với SRT.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import config
from ..timing import ms_to_frame

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
WORDS_PER_LINE = 5
HIGHLIGHT = (255, 214, 64)
NORMAL = (255, 255, 255)
SHADOW = (0, 0, 0)


def find_font() -> str | None:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    path = find_font()
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _group_lines(words: list[dict[str, Any]]) -> list[list[int]]:
    """Gom chỉ số từ thành từng dòng ≤ WORDS_PER_LINE, ngắt sớm ở cuối câu."""
    lines: list[list[int]] = []
    cur: list[int] = []
    for i, w in enumerate(words):
        cur.append(i)
        ends_sentence = w["w"].rstrip().endswith((".", "!", "?", "…"))
        if len(cur) >= WORDS_PER_LINE or ends_sentence:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return lines


def build_caption_plan(chunk: dict[str, Any], fps: int, width: int, height: int, n_frames: int,
                       mode: str = "word_pop", position: str = "bottom") -> dict[str, Any]:
    """Kế hoạch phụ đề: mỗi từ có start_frame/end_frame (so với đầu chunk) và hộp chữ đã đo."""
    words = chunk.get("words") or []
    plan: dict[str, Any] = {"mode": mode, "fps": fps, "width": width, "height": height,
                            "safe_area_pct": config.SAFE_AREA_PCT, "items": [], "lines": []}
    if mode == "none" or not words:
        plan["mode"] = "none"
        return plan

    margin_x = width * config.SAFE_AREA_PCT / 100.0
    margin_y = height * config.SAFE_AREA_PCT / 100.0
    base_size = max(12, int(height * 0.062))
    gap = int(base_size * 0.35)
    start = chunk["start_ms"]

    lines = _group_lines(words)
    for li, idxs in enumerate(lines):
        size = base_size
        while True:
            font = _font(size)
            widths = [font.getlength(words[i]["w"]) for i in idxs]
            total = sum(widths) + gap * (len(idxs) - 1)
            if total <= width - 2 * margin_x or size <= 10:
                break
            size -= 2
        ascent, descent = font.getmetrics()
        line_h = ascent + descent
        if position == "top":
            y0 = margin_y
        else:
            y0 = height - margin_y - line_h * 1.25  # chừa chỗ cho chữ "pop" to hơn
        x = (width - total) / 2
        l_start = ms_to_frame(words[idxs[0]]["start_ms"] - start, fps)
        l_end = ms_to_frame(words[idxs[-1]]["end_ms"] - start, fps)
        if li == len(lines) - 1:
            l_end = max(l_end, n_frames)
        plan["lines"].append({"index": li, "words": idxs, "font_size": size,
                              "start_frame": max(0, l_start), "end_frame": min(n_frames, l_end)})
        for i, w_px in zip(idxs, widths):
            w = words[i]
            sf = max(0, ms_to_frame(w["start_ms"] - start, fps))
            ef = min(n_frames, ms_to_frame(w["end_ms"] - start, fps))
            box = [round(x), round(y0), round(x + w_px), round(y0 + line_h)]
            plan["items"].append({"index": i, "word": w["w"], "start_frame": sf, "end_frame": max(sf + 1, ef),
                                  "line": li, "box": box, "font_size": size})
            x += w_px + gap
    return plan


def _active_line(plan: dict[str, Any], frame: int) -> dict[str, Any] | None:
    for line in plan["lines"]:
        if line["start_frame"] <= frame < line["end_frame"]:
            return line
    return None


def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill) -> None:
    x, y = xy
    o = max(1, font.size // 14) if hasattr(font, "size") else 1
    for dx, dy in ((-o, 0), (o, 0), (0, -o), (0, o), (o, o), (-o, -o)):
        draw.text((x + dx, y + dy), text, font=font, fill=SHADOW)
    draw.text((x, y), text, font=font, fill=fill)


def composite_captions(frames_dir: Path, plan: dict[str, Any], n_frames: int,
                       pattern: str = config.FRAME_PATTERN) -> None:
    """Vẽ phụ đề thẳng vào các khung trong frames_dir (ghi đè tại chỗ)."""
    if plan.get("mode") == "none":
        return
    items_by_line: dict[int, list[dict[str, Any]]] = {}
    for it in plan["items"]:
        items_by_line.setdefault(it["line"], []).append(it)
    fonts: dict[int, Any] = {}

    for f in range(n_frames):
        line = _active_line(plan, f)
        if line is None:
            continue
        path = frames_dir / (pattern % f)
        img = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(img)
        size = line["font_size"]
        fonts.setdefault(size, _font(size))
        pop_size = int(size * 1.15)
        fonts.setdefault(pop_size, _font(pop_size))
        for it in items_by_line.get(line["index"], []):
            x0, y0, x1, y1 = it["box"]
            is_current = it["start_frame"] <= f < it["end_frame"]
            spoken = f >= it["start_frame"]
            if plan["mode"] == "word_pop" and is_current:
                font = fonts[pop_size]
                w_px = font.getlength(it["word"])
                cx = (x0 + x1) / 2
                _draw_text(draw, (cx - w_px / 2, y0 - (pop_size - size) * 0.8), it["word"], font, HIGHLIGHT)
            else:
                fill = NORMAL if spoken or plan["mode"] == "line" else (170, 170, 170)
                _draw_text(draw, (x0, y0), it["word"], fonts[size], fill)
        img.save(path)


def write_plan(plan: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
