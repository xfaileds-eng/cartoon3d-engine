"""Luồng xử lý một chunk: plan → bundle → cổng trước render → render → ghép → phụ đề → đóng gói → cổng sau render.

Dùng:
  python -m core.pipeline run  --chunk tests/fixtures/cheese_bank/chunk_input.json [--backend threejs] [--width 640 --height 360]
  python -m core.pipeline plan --chunk ... [--out out/]
  python -m core.pipeline qa   --chunk ... --shots out/<chunk_id>/shots [--frames out/<chunk_id>/frames --video ...]
Mã thoát ≠ 0 khi có cổng trượt: không giao video lỗi cho nhạc trưởng.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import config
from .captions import build_caption_plan, composite_captions
from .captions.compositor import write_plan
from .qa_gates import GateContext, make_contact_sheet, run_post_render_gates, run_pre_render_gates
from .qa_gates.gates import report as gate_report
from .qa_gates.gates import validate
from .registry import Registry
from .scene_bundle import build_bundle, write_bundle
from .shot_planner import plan_chunk
from .timing import allocate_frames


class GateFailure(RuntimeError):
    def __init__(self, stage: str, results):
        self.stage = stage
        self.results = results
        failed = [r for r in results if not r.passed]
        super().__init__(f"{stage}: trượt {len(failed)} cổng: " + "; ".join(f"{r.id} {r.details}" for r in failed))


def _log(msg: str) -> None:
    print(f"[cartoon3d] {msg}", file=sys.stderr, flush=True)


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(data: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def get_backend(name: str):
    if name == "threejs":
        from backends.threejs.capture import render_bundle
    elif name == "blender":
        from backends.blender.render import render_bundle
    else:
        raise ValueError(f"backend '{name}' không có; chọn threejs hoặc blender")
    return render_bundle


def plan(chunk: dict[str, Any], out_dir: Path, registry: Registry) -> list[dict[str, Any]]:
    shots = plan_chunk(chunk, registry)
    for s in shots:
        dump_json(s, out_dir / "shots" / f"{s['shot_id']}.json")
    return shots


def load_shots(shots_dir: Path) -> list[dict[str, Any]]:
    shots = [load_json(p) for p in sorted(shots_dir.glob("*.json"))]
    return sorted(shots, key=lambda s: int(s["shot_id"].rsplit("_s", 1)[1]))


def assemble_frames(shot_frame_dirs: list[tuple[Path, int]], chunk_frames: Path) -> int:
    """Nối khung của từng shot thành một dãy liên tục cho cả chunk. Dùng hard link, không được thì copy."""
    if chunk_frames.exists():
        shutil.rmtree(chunk_frames)
    chunk_frames.mkdir(parents=True)
    k = 0
    for d, n in shot_frame_dirs:
        for i in range(n):
            src = d / (config.FRAME_PATTERN % i)
            if not src.exists():
                raise FileNotFoundError(f"backend không sinh khung {src}")
            dst = chunk_frames / (config.FRAME_PATTERN % k)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copyfile(src, dst)
            k += 1
    return k


def package_mp4(frames_dir: Path, fps: int, out_path: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
           "-i", str(frames_dir / config.FRAME_PATTERN),
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-r", str(fps), "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)
    return out_path


def run_chunk(chunk_path: Path, *, out_root: Path = config.OUT_DIR, backend: str = config.DEFAULT_BACKEND,
              width: int = config.DEFAULT_WIDTH, height: int = config.DEFAULT_HEIGHT,
              shots_dir: Path | None = None, skip_render: bool = False) -> dict[str, Any]:
    t0 = time.time()
    registry = Registry()
    chunk = load_json(chunk_path)
    fps = int(chunk.get("fps", config.DEFAULT_FPS))
    out_dir = out_root / chunk["chunk_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chunk_path, out_dir / "chunk_input.json")

    # 1. Lập shot (hoặc dùng shot đã sửa tay)
    shots = load_shots(shots_dir) if shots_dir else plan(chunk, out_dir, registry)
    _log(f"{chunk['chunk_id']}: {len(shots)} shot, {fps} fps, {width}x{height}, backend {backend}")

    # 2. Bundle từng shot với số khung đã chia khớp G3
    frames_per_shot = allocate_frames([s["duration_ms"] for s in shots], fps)
    bundles, bundle_paths = [], []
    for s, n in zip(shots, frames_per_shot):
        b = build_bundle(s, chunk, n, registry=registry, width=width, height=height, fps=fps)
        bundles.append(b)
        bundle_paths.append(write_bundle(b, out_dir / s["shot_id"] / "scene_bundle.json"))

    # 3. Cổng trước render: trượt thì dừng, không tốn thời gian render
    ctx = GateContext(chunk, shots, bundles, fps, registry=registry)
    pre = run_pre_render_gates(ctx)
    dump_json(gate_report(pre), out_dir / "qa_pre_render.json")
    if not all(r.passed for r in pre):
        raise GateFailure("trước render", pre)
    _log("qua 5 cổng trước render")

    if skip_render:
        return {"chunk_id": chunk["chunk_id"], "shots": [s["shot_id"] for s in shots], "pre_render": gate_report(pre)}

    # 4. Render từng shot
    render = get_backend(backend)
    shot_dirs = []
    for s, bp, n in zip(shots, bundle_paths, frames_per_shot):
        fd = out_dir / s["shot_id"] / "frames"
        if fd.exists():
            shutil.rmtree(fd)
        fd.mkdir(parents=True)
        t1 = time.time()
        render(bp, fd)
        _log(f"render {s['shot_id']}: {n} khung trong {time.time() - t1:.1f}s")
        shot_dirs.append((fd, n))

    # 5. Ghép khung + 6. phụ đề
    chunk_frames = out_dir / "frames"
    total = assemble_frames(shot_dirs, chunk_frames)
    modes = {s["captions"]["mode"] for s in shots}
    mode = "none" if modes == {"none"} else ("line" if modes == {"line"} else "word_pop")
    position = next((s["captions"].get("position") for s in shots if s["captions"].get("position")), "bottom")
    plan_ = build_caption_plan(chunk, fps, width, height, total, mode=mode, position=position)
    composite_captions(chunk_frames, plan_, total)
    write_plan(plan_, out_dir / "captions_plan.json")

    # 7. Đóng gói
    video = package_mp4(chunk_frames, fps, out_dir / f"{chunk['chunk_id']}.mp4")
    sheet = make_contact_sheet(chunk_frames, total, out_dir / "contact_sheet.png")

    # 8. Cổng sau render + render_output
    ctx.frames_dir, ctx.video_path, ctx.caption_plan = chunk_frames, video, plan_
    post = run_post_render_gates(ctx)
    qa = gate_report(pre + post, sheet)
    render_output = {
        "chunk_id": chunk["chunk_id"],
        "video_path": str(video),
        "frames": total,
        "duration_ms": chunk["end_ms"] - chunk["start_ms"],
        "fps": fps, "width": width, "height": height,
        "backend": backend,
        "shots": [s["shot_id"] for s in shots],
        "qa_report": qa,
    }
    schema_errs = validate("render_output", render_output)
    if schema_errs:
        for g in qa["gates"]:
            if g["id"] == "G1":
                g["passed"] = False
                g["details"] = [f"render_output {e}" for e in schema_errs]
        qa["passed"] = False
    dump_json(qa, out_dir / "qa_report.json")
    dump_json(render_output, out_dir / "render_output.json")
    _log(f"xong trong {time.time() - t0:.1f}s · qa passed = {qa['passed']} · {video}")
    if not qa["passed"]:
        raise GateFailure("sau render", post)
    return render_output


def qa_only(chunk_path: Path, shots_dir: Path, *, frames: Path | None, video: Path | None,
            captions_plan: Path | None, width: int, height: int) -> dict[str, Any]:
    registry = Registry()
    chunk = load_json(chunk_path)
    fps = int(chunk.get("fps", config.DEFAULT_FPS))
    shots = load_shots(shots_dir)
    frames_per_shot = allocate_frames([s["duration_ms"] for s in shots], fps)
    bundles = [build_bundle(s, chunk, n, registry=registry, width=width, height=height, fps=fps)
               for s, n in zip(shots, frames_per_shot)]
    ctx = GateContext(chunk, shots, bundles, fps, registry=registry, frames_dir=frames, video_path=video,
                      caption_plan=load_json(captions_plan) if captions_plan else None)
    results = run_pre_render_gates(ctx) + (run_post_render_gates(ctx) if frames else [])
    return gate_report(results)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cartoon3d", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--chunk", required=True, type=Path, help="chunk_input.json từ nhạc trưởng")
        p.add_argument("--out", type=Path, default=config.OUT_DIR)
        p.add_argument("--width", type=int, default=config.DEFAULT_WIDTH)
        p.add_argument("--height", type=int, default=config.DEFAULT_HEIGHT)

    p_run = sub.add_parser("run", help="chạy trọn luồng, trả render_output.json")
    common(p_run)
    p_run.add_argument("--backend", default=config.DEFAULT_BACKEND, choices=["threejs", "blender"])
    p_run.add_argument("--shots", type=Path, help="thư mục shot.json đã sửa tay (bỏ qua shot_planner)")
    p_run.add_argument("--skip-render", action="store_true", help="chỉ lập shot, bundle và kiểm 5 cổng trước render")

    p_plan = sub.add_parser("plan", help="chỉ lập shot.json")
    common(p_plan)

    p_qa = sub.add_parser("qa", help="chạy lại các cổng trên kết quả đã có")
    common(p_qa)
    p_qa.add_argument("--shots", type=Path, required=True)
    p_qa.add_argument("--frames", type=Path)
    p_qa.add_argument("--video", type=Path)
    p_qa.add_argument("--captions-plan", type=Path)

    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            chunk = load_json(a.chunk)
            shots = plan(chunk, a.out / chunk["chunk_id"], Registry())
            print(json.dumps(shots, ensure_ascii=False, indent=2))
            return 0
        if a.cmd == "qa":
            rep = qa_only(a.chunk, a.shots, frames=a.frames, video=a.video, captions_plan=a.captions_plan,
                          width=a.width, height=a.height)
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0 if rep["passed"] else 2
        result = run_chunk(a.chunk, out_root=a.out, backend=a.backend, width=a.width, height=a.height,
                           shots_dir=a.shots, skip_render=a.skip_render)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GateFailure as e:
        _log(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
