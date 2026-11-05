"""Công cụ đo dùng chung cho test và cổng kiểm của mọi engine: ffprobe, thống kê khung, OCR."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


def ffprobe_stream(video: Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,pix_fmt,width,height,r_frame_rate,nb_read_frames",
         "-of", "json", str(video)], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return {"codec": s["codec_name"], "pix_fmt": s["pix_fmt"], "width": int(s["width"]), "height": int(s["height"]),
            "fps": num / den, "frames": int(s["nb_read_frames"])}


def extract_frame(video: Path, index: int, out_png: Path) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select=eq(n\\,{index})",
                    "-vframes", "1", str(out_png)], check=True)
    return out_png


def is_blank(img: Image.Image, low: float = 8.0, high: float = 247.0, std_max: float = 3.0) -> bool:
    st = ImageStat.Stat(img.convert("L"))
    mean, std = st.mean[0], st.stddev[0]
    return std < std_max and (mean < low or mean > high)


def normalize_word(w: str) -> str:
    w = unicodedata.normalize("NFC", w).lower()
    return re.sub(r"[^\w]", "", w)


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_words(img_path: Path, langs: str = "eng+vie") -> list[str]:
    if not ocr_available():
        raise RuntimeError("thiếu tesseract: cài tesseract-ocr (+ tesseract-ocr-vie)")
    with tempfile.TemporaryDirectory() as td:
        # Phóng to 2x giúp OCR bắt chữ nhỏ; psm 11 = tìm chữ rời rạc khắp khung.
        img = Image.open(img_path).convert("L")
        big = img.resize((img.width * 2, img.height * 2))
        p = Path(td) / "ocr.png"
        big.save(p)
        out = subprocess.run(["tesseract", str(p), "stdout", "-l", langs, "--psm", "11"],
                             capture_output=True, text=True).stdout
    return [normalize_word(t) for t in out.split() if normalize_word(t)]


def burned_caption_words(img_path: Path, text: str, min_len: int = 3) -> list[str]:
    """Các từ của lời thoại (dài ≥ min_len) mà OCR đọc được trong khung. Rỗng = không có phụ đề in cứng."""
    target = {normalize_word(w) for w in text.split()}
    target = {w for w in target if len(w) >= min_len}
    return sorted(set(ocr_words(img_path)) & target)
