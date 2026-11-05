"""Luồng xử lý một chunk theo hợp đồng engine-contracts:

  chunk_input → kiểm thẻ năng lực (rejected?) → shot_planner (qua port llm_provider) → scene_bundle (dịch look)
  → cổng trước render → backend render → ghép khung → ffmpeg .mp4 → cổng sau render → render_output.json

Engine KHÔNG in phụ đề: phụ đề in một lần ở khâu ghép. fps, độ phân giải, codec lấy từ format.json.

Dùng:
  python -m core.pipeline run --chunk <chunk_input.json> [--backend threejs|blender] [--shots DIR] [--preview]
  python -m core.pipeline plan --chunk <chunk_input.json>
Mã thoát: 0 = done · 2 = failed (trượt cổng) · 3 = rejected · 4 = preview (không giao).
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

from . import config, contracts
from .capability import check_capability, load_capability_card
from .qa_gates import GateContext, make_contact_sheet, run_post_render_gates, run_pre_render_gates
from .qa_gates.gates import c_schema
from .qa_gates.gates import report as gate_report
from .registry import Registry
from .scene_bundle import build_bundle, write_bundle
from .shot_planner import plan_chunk
from .timing import allocate_frames

EXIT_CODES = {"done": 0, "failed": 2, "rejected": 3, "preview": 4}


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


def load_shots(shots_dir: Path) -> list[dict[str, Any]]:
    shots = [load_json(p) for p in sorted(shots_dir.glob("*.json"))]
    return sorted(shots, key=lambda s: int(s["shot_id"].rsplit("_s", 1)[1]))


def assemble_frames(shot_frame_dirs: list[tuple[Path, int]], chunk_frames: Path) -> int:
    """Nối khung của từng shot thành một dãy liên tục cho cả chunk (hard link, không được thì copy)."""
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
    fmt = contracts.load_format()
    codec = {"h264": "libx264", "hevc": "libx265"}.get(fmt["codec"], fmt["codec"])
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                    "-i", str(frames_dir / config.FRAME_PATTERN),
                    "-c:v", codec, "-preset", "medium", "-crf", "18", "-pix_fmt", fmt["pix_fmt"],
                    "-r", str(fps), "-movflags", "+faststart", str(out_path)], check=True)
    return out_path


def _render_output(chunk: dict[str, Any], status: str, *, fps: int, video: Path | None = None, frames: int = 0,
                   qa: dict[str, Any] | None = None, render_s: float = 0.0, reason: str | None = None,
                   extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ro: dict[str, Any] = {
        "chunk_id": chunk["chunk_id"],
        "engine_id": config.ENGINE_ID,
        "status": status,
        "video_path": str(video) if video else None,
        "frames": frames,
        "fps": fps,
        "duration_ms": chunk["end_ms"] - chunk["start_ms"],
        "qa_report": qa or {"passed": False, "gates": []},
        "cost": {"usd": 0.0, "render_s": round(render_s, 2)},
    }
    if reason:
        ro["reason"] = reason
    ro.update(extra or {})
    return ro


def run_chunk(chunk_path: Path, *, out_root: Path = config.OUT_DIR, backend: str = config.DEFAULT_BACKEND,
              shots_dir: Path | None = None, preview: bool = False, llm=None) -> dict[str, Any]:
    """Chạy trọn luồng một chunk, luôn trả về render_output (done | rejected | failed).

    preview=True: render 1/3 độ phân giải để xem nhanh; ghi preview_report.json, không ghi render_output.json.
    """
    t0 = time.time()
    registry = Registry()
    chunk = load_json(chunk_path)
    fmt = contracts.load_format()
    fps = int(fmt["fps"])
    out_dir = Path(out_root) / chunk["chunk_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chunk_path, out_dir / "chunk_input.json")
    if contracts.is_vendored():
        _log("dùng vendor/engine-contracts (bản chép tạm từ brief)")

    def finish(ro: dict[str, Any]) -> dict[str, Any]:
        dump_json(ro, out_dir / ("preview_report.json" if preview else "render_output.json"))
        _log(f"{chunk['chunk_id']}: {ro['status']} trong {time.time() - t0:.1f}s"
             + (f" · {ro.get('reason')}" if ro.get("reason") else ""))
        return ro

    # 0. Hợp đồng vào + thẻ năng lực
    pre_schema = c_schema(GateContext(chunk, [], [], fps))
    if not pre_schema.passed:
        return finish(_render_output(chunk, "rejected", fps=fps, reason="chunk_input sai schema",
                                     qa=gate_report([pre_schema])))
    reason = check_capability(load_capability_card(), chunk)
    if reason:
        return finish(_render_output(chunk, "rejected", fps=fps, reason=reason, qa=gate_report([pre_schema])))

    width, height = contracts.frame_size(chunk["aspect"])
    if preview:
        width, height = (round(width * config.PREVIEW_SCALE / 2) * 2, round(height * config.PREVIEW_SCALE / 2) * 2)
    look = contracts.load_look(chunk["look_id"])

    # 1. Lập shot (hoặc dùng shot đã sửa tay)
    shots = load_shots(shots_dir) if shots_dir else plan_chunk(chunk, registry, llm=llm)
    for s in shots:
        dump_json(s, out_dir / "shots" / f"{s['shot_id']}.json")
    _log(f"{chunk['chunk_id']}: {len(shots)} shot, {fps} fps, {width}x{height}, look {chunk['look_id']}, backend {backend}")

    # 2. Bundle từng shot với số khung đã chia khớp C-duration/G3
    frames_per_shot = allocate_frames([s["duration_ms"] for s in shots], fps)
    bundles, bundle_paths = [], []
    for s, n in zip(shots, frames_per_shot):
        b = build_bundle(s, chunk, n, look=look, width=width, height=height, fps=fps, registry=registry)
        bundles.append(b)
        bundle_paths.append(write_bundle(b, out_dir / s["shot_id"] / "scene_bundle.json"))

    # 3. Cổng trước render: trượt thì dừng, không tốn thời gian render
    ctx = GateContext(chunk, shots, bundles, fps, registry=registry, size=(width, height), preview=preview)
    pre = run_pre_render_gates(ctx)
    if not all(r.passed for r in pre):
        failed = "; ".join(f"{r.id}" for r in pre if not r.passed)
        return finish(_render_output(chunk, "failed", fps=fps, reason=f"trượt cổng trước render: {failed}",
                                     qa=gate_report(pre), render_s=time.time() - t0))

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

    # 5. Ghép khung, đóng gói (không phụ đề)
    chunk_frames = out_dir / "frames"
    total = assemble_frames(shot_dirs, chunk_frames)
    video = package_mp4(chunk_frames, fps, out_dir / f"{chunk['chunk_id']}.mp4")
    sheet = make_contact_sheet(chunk_frames, total, out_dir / "contact_sheet.png")

    # 6. Cổng sau render, rồi C-schema trên chính render_output
    ctx.frames_dir, ctx.video_path = chunk_frames, video
    results = pre + run_post_render_gates(ctx)
    render_s = time.time() - t0
    passed = all(r.passed for r in results)
    extra = {"width": width, "height": height, "backend": backend, "look_id": chunk["look_id"],
             "shots": [s["shot_id"] for s in shots]}
    status = "done" if passed else "failed"
    ro = _render_output(chunk, status, fps=fps, video=video if passed else None, frames=total,
                        qa=gate_report(results, sheet), render_s=render_s, extra=extra)
    ctx.render_output = ro
    results.append(c_schema(ctx))
    if not all(r.passed for r in results):
        failed = ", ".join(r.id for r in results if not r.passed)
        ro = _render_output(chunk, "failed", fps=fps, frames=total, qa=gate_report(results, sheet),
                            render_s=render_s, reason=f"trượt cổng: {failed}", extra=dict(extra, video_file=str(video)))
    else:
        ro["qa_report"] = gate_report(results, sheet)
    if preview:
        ro["status"] = "preview"
    return finish(ro)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cartoon3d", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="chạy trọn luồng, ghi render_output.json")
    p_run.add_argument("--chunk", required=True, type=Path, help="chunk_input.json từ nhạc trưởng")
    p_run.add_argument("--out", type=Path, default=config.OUT_DIR)
    p_run.add_argument("--backend", default=config.DEFAULT_BACKEND, choices=["threejs", "blender"])
    p_run.add_argument("--shots", type=Path, help="thư mục shot.json đã sửa tay (bỏ qua shot_planner)")
    p_run.add_argument("--preview", action="store_true", help="render 1/3 độ phân giải để xem nhanh; không giao")

    p_plan = sub.add_parser("plan", help="chỉ lập shot.json")
    p_plan.add_argument("--chunk", required=True, type=Path)

    a = ap.parse_args(argv)
    if a.cmd == "plan":
        shots = plan_chunk(load_json(a.chunk))
        print(json.dumps(shots, ensure_ascii=False, indent=2))
        return 0
    ro = run_chunk(a.chunk, out_root=a.out, backend=a.backend, shots_dir=a.shots, preview=a.preview)
    print(json.dumps(ro, ensure_ascii=False, indent=2))
    return EXIT_CODES.get(ro["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
