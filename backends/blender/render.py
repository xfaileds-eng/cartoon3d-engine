"""render.py — backend Blender: dựng cảnh từ scene_bundle.json, keyframe máy quay/nhân vật theo track, xuất PNG.

Hai cách gọi:
  (1) từ pipeline:  render_bundle(bundle_path, frames_dir)  → tự gọi blender --background
  (2) trong Blender: blender --background --python backends/blender/render.py -- --bundle B --out DIR
Yêu cầu Blender ≥ 4.0 trên PATH hoặc biến CARTOON3D_BLENDER. Giai đoạn P3 của lộ trình.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def render_bundle(bundle_path: Path, frames_dir: Path, *, timeout_s: int = 3600) -> dict:
    exe = os.environ.get("CARTOON3D_BLENDER") or shutil.which("blender")
    if not exe:
        raise RuntimeError("không tìm thấy Blender: đặt CARTOON3D_BLENDER hoặc thêm blender vào PATH (hoặc dùng --backend threejs)")
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "--background", "--python", str(HERE / "render.py"), "--",
           "--bundle", str(Path(bundle_path).resolve()), "--out", str(frames_dir.resolve())]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise RuntimeError(f"blender thoát mã {proc.returncode}:\n{proc.stderr[-4000:]}")
    n = len(list(frames_dir.glob("frame_*.png")))
    return {"frames": n}


# ------------------------------------------------------------------ chạy trong Blender
def _main_in_blender() -> None:
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore

    sys.path.insert(0, str(HERE))
    from build_scene import build_from_bundle  # type: ignore

    argv = sys.argv[sys.argv.index("--") + 1:]
    bundle_path = Path(argv[argv.index("--bundle") + 1])
    out_dir = Path(argv[argv.index("--out") + 1])
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    R, tracks = bundle["render"], bundle["tracks"]

    roots = build_from_bundle(bundle)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if hasattr(bpy.types, "SceneEEVEE") and bpy.app.version >= (4, 2) else "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = R["width"], R["height"]
    scene.render.resolution_percentage = int(100 * float(bundle["style"]["renderer"].get("internal_scale", 1)))
    scene.render.fps = R["fps"]
    scene.frame_start, scene.frame_end = 0, R["n_frames"] - 1
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out_dir / "frame_")
    scene.render.use_file_extension = True

    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam
    cam_data.sensor_fit = "VERTICAL"

    def to_blender(v):  # Three.js (x, y lên, z) → Blender (x, -z, y)
        return Vector((v[0], -v[2], v[1]))

    for i, pose in enumerate(tracks["camera"]):
        pos, look = to_blender(pose["position"]), to_blender(pose["look_at"])
        cam.location = pos
        cam.rotation_euler = (look - pos).to_track_quat("-Z", "Y").to_euler()
        cam_data.angle_y = math.radians(pose["fov_deg"])
        cam.keyframe_insert("location", frame=i)
        cam.keyframe_insert("rotation_euler", frame=i)
        cam_data.keyframe_insert("angle_y", frame=i)
        for cid, root in roots.items():
            tr = tracks["cast"].get(cid)
            if not tr:
                continue
            root.location = to_blender(tr[i]["position"])
            root.rotation_euler = (0, 0, math.radians(tr[i].get("yaw_deg", 0)))
            root.keyframe_insert("location", frame=i)
            root.keyframe_insert("rotation_euler", frame=i)
    # Nội suy đã nằm trong track từng khung: keyframe mỗi khung, Blender dùng CONSTANT để không làm mềm thêm.
    for obj in [cam, *roots.values()]:
        if obj.animation_data and obj.animation_data.action:
            for fc in obj.animation_data.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "CONSTANT"

    # Đặt tên file theo FRAME_PATTERN frame_%05d.png (Blender tự thêm 4 chữ số → đổi tên sau)
    bpy.ops.render.render(animation=True)
    for p in sorted(out_dir.glob("frame_*.png")):
        num = int(p.stem.split("_")[-1])
        p.rename(out_dir / f"frame_{num:05d}.png")


if __name__ == "__main__":
    if "bpy" in sys.modules or any(a.endswith("blender") or "blender" in a.lower() for a in sys.argv[:1]):
        _main_in_blender()
    else:
        import argparse

        ap = argparse.ArgumentParser(description="Render một scene_bundle.json bằng Blender (chạy blender --background)")
        ap.add_argument("bundle", type=Path)
        ap.add_argument("out", type=Path)
        a = ap.parse_args()
        print(json.dumps(render_bundle(a.bundle, a.out)))
