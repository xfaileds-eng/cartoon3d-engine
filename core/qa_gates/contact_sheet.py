"""Contact sheet: lưới ảnh thu nhỏ của các khung để agent tự xem (G6)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .. import config


def make_contact_sheet(frames_dir: Path, n_frames: int, out_path: Path, cols: int = 6, rows: int = 4,
                       thumb_w: int = 320, pattern: str = config.FRAME_PATTERN) -> Path:
    k = cols * rows
    idxs = sorted({round(i * (n_frames - 1) / max(1, k - 1)) for i in range(k)}) if n_frames > 1 else [0]
    first = Image.open(frames_dir / (pattern % idxs[0]))
    thumb_h = round(thumb_w * first.height / first.width)
    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for n, i in enumerate(idxs):
        img = Image.open(frames_dir / (pattern % i)).convert("RGB").resize((thumb_w, thumb_h))
        x, y = (n % cols) * thumb_w, (n // cols) * thumb_h
        sheet.paste(img, (x, y))
        draw.rectangle([x, y, x + 46, y + 16], fill=(0, 0, 0))
        draw.text((x + 3, y + 2), f"#{i}", fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
