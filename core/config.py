"""Đường dẫn và mặc định riêng của engine. fps, độ phân giải, codec lấy từ engine-contracts/format.json."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
ASSETS_DIR = REPO_ROOT / "assets"
STYLES_DIR = REPO_ROOT / "styles"
OUT_DIR = Path(os.environ.get("CARTOON3D_OUT", REPO_ROOT / "out"))
REGISTRY_PATH = ASSETS_DIR / "registry.json"
CAPABILITY_CARD_PATH = REPO_ROOT / "capability_card.json"
PROVIDERS_PATH = Path(os.environ.get("PROVIDERS_CONFIG", REPO_ROOT / "providers.yaml"))

ENGINE_ID = "cartoon3d"
DEFAULT_BACKEND = os.environ.get("CARTOON3D_BACKEND", "threejs")
# Phong cách mặc định: dòng vụ án dùng voxel (anh Vinh chốt 05/11/2026). Đổi theo máy bằng CARTOON3D_STYLE.
DEFAULT_STYLE = os.environ.get("CARTOON3D_STYLE", "voxel")
# Chạy xem trước: render ở 1/3 độ phân giải chuẩn, không xuất render_output.
PREVIEW_SCALE = 1 / 3

# Máy quay phải cách tâm mọi nhân vật đang hiện ít nhất chừng này (G5).
CAMERA_MIN_DISTANCE_M = 0.5
# Cho phép chủ thể ló ra ngoài khung một chút vẫn tính là "trong khung" (G5).
FRAMING_TOLERANCE = 1.15
# Ngưỡng khung đen/trắng (C-visual, G6): độ sáng trung bình 0..255 và độ lệch chuẩn.
BLANK_FRAME_MEAN_LOW = 8.0
BLANK_FRAME_MEAN_HIGH = 247.0
BLANK_FRAME_STD_MAX = 3.0
# Số khung lấy mẫu cho OCR ở G8 (C-no-captions chỉ đọc khung giữa, theo test chung).
OCR_SAMPLE_FRAMES = 5

FRAME_PATTERN = "frame_%05d.png"
