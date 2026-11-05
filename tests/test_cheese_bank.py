"""Hai test riêng trong mục "Bài test khởi động" của spec cartoon3d."""
import json
import subprocess
from pathlib import Path

from core.qa_gates.gates import ROUND_SHAPES
from core.registry import Registry, load_style

ALL_GATES = ["C-schema", "C-duration", "C-format", "C-visual", "C-no-captions", "C-license",
             "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]


def _frames(video: str) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                          "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", video],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def test_cheese_bank_fixture(cheese_bank_output):
    ro = cheese_bank_output["render_output"]
    assert ro["status"] == "done", ro.get("reason")
    assert ro["frames"] == 126 and ro["fps"] == 30
    assert _frames(ro["video_path"]) == 126
    gates = {g["id"]: g for g in ro["qa_report"]["gates"]}
    assert list(gates) == ALL_GATES
    assert all(g["passed"] for g in gates.values()), [g for g in gates.values() if not g["passed"]]
    assert Path(ro["qa_report"]["contact_sheet"]).exists()
    shots = sorted((cheese_bank_output["out_dir"] / "shots").glob("*.json"))
    assert json.loads(shots[0].read_text())["set"] == "cheese_vault"


def test_round_segments():
    """Mọi vật tròn trong thư viện tài sản có từ 32 mặt trở lên, và mọi phong cách khai min_segments ≥ 32."""
    reg = Registry()
    bad = []
    for row in reg.all_rows():
        data = reg.load(row["asset_id"])
        objs = list(data.get("objects", [])) + [dict(v, name=k) for k, v in data.get("parts", {}).items()]
        for o in objs:
            if o.get("shape") in ROUND_SHAPES and int(o.get("segments", 0)) < 32:
                bad.append(f"{row['asset_id']}/{o.get('name')}: {o.get('segments')}")
    assert bad == []
    for style_id in ("toon", "voxel", "pixel3d"):
        style = load_style(style_id)
        assert style["geometry"]["min_segments"] >= 32
        assert style["geometry"]["crease_angle_deg"] == 140
