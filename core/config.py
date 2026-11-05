"""Đường dẫn và mặc định của engine. Mọi module đọc từ đây, không hard-code."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
ASSETS_DIR = REPO_ROOT / "assets"
STYLES_DIR = REPO_ROOT / "styles"
OUT_DIR = Path(os.environ.get("CARTOON3D_OUT", REPO_ROOT / "out"))
REGISTRY_PATH = ASSETS_DIR / "registry.json"

DEFAULT_FPS = 24
DEFAULT_WIDTH = int(os.environ.get("CARTOON3D_WIDTH", 1920))
DEFAULT_HEIGHT = int(os.environ.get("CARTOON3D_HEIGHT", 1080))
DEFAULT_BACKEND = os.environ.get("CARTOON3D_BACKEND", "threejs")

# Vùng an toàn cho phụ đề: phần trăm chiều rộng/cao chừa ra mỗi cạnh (G8).
SAFE_AREA_PCT = 5.0
# Máy quay phải cách tâm mọi nhân vật đang hiện ít nhất chừng này (G5).
CAMERA_MIN_DISTANCE_M = 0.5
# Cho phép chủ thể ló ra ngoài khung một chút vẫn tính là "trong khung" (G5).
FRAMING_TOLERANCE = 1.15
# Ngưỡng khung đen/trắng (G6): độ sáng trung bình 0..255 và độ lệch chuẩn.
BLANK_FRAME_MEAN_LOW = 8.0
BLANK_FRAME_MEAN_HIGH = 247.0
BLANK_FRAME_STD_MAX = 3.0

FRAME_PATTERN = "frame_%05d.png"
