"""Cổng kiểm. Một chunk chỉ được trả về khâu ghép khi qua hết:

- 6 cổng chung của engine-contracts (chạy trước): C-schema, C-duration, C-format, C-visual, C-no-captions, C-license;
- 8 cổng riêng của cartoon3d: G1 schema · G2 giấy phép · G3 thời lượng · G4 hình khối · G5 máy quay ·
  G6 hình ảnh · G7 nhạy cảm · G8 không phụ đề.

Trước render (đọc spec và bundle): C-license G1 G2 G4 G5 G7. Sau render (đọc khung, video, render_output): phần còn lại.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from PIL import Image

from .. import config, contracts
from ..registry import Registry, RegistryError
from ..sensitivity import allowed_devices
from ..timing import frames_for

contracts.ensure_import_path()
from common.helpers import (  # noqa: E402  — công cụ đo dùng chung của engine-contracts
    burned_caption_words,
    ffprobe_stream,
    is_blank,
    ocr_available,
)


def validate(name: str, data: Any) -> list[str]:
    v = jsonschema.Draft202012Validator(contracts.load_schema(name))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in v.iter_errors(data)]


@dataclass
class GateResult:
    id: str
    name: str
    passed: bool
    details: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "passed": self.passed, "details": self.details}


@dataclass
class GateContext:
    chunk: dict[str, Any]
    shots: list[dict[str, Any]]
    bundles: list[dict[str, Any]]
    fps: int
    registry: Registry = field(default_factory=Registry)
    frames_dir: Path | None = None
    video_path: Path | None = None
    render_output: dict[str, Any] | None = None
    size: tuple[int, int] | None = None   # (width, height) phải ra
    preview: bool = False                 # bản xem trước: không so định dạng chuẩn

    @property
    def expected_frames(self) -> int:
        return frames_for(self.chunk["end_ms"] - self.chunk["start_ms"], self.fps)


def _sample_indices(n: int, k: int) -> list[int]:
    if n <= k:
        return list(range(n))
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


# ================================================================ cổng chung (engine-contracts)
def c_schema(ctx: GateContext) -> GateResult:
    errs = [f"chunk_input {e}" for e in validate("chunk_input", ctx.chunk)]
    if ctx.render_output is not None:
        errs += [f"render_output {e}" for e in validate("render_output", ctx.render_output)]
    return GateResult("C-schema", "Schema chung", not errs, errs or "chunk_input và render_output đúng schema engine-contracts")


def c_duration(ctx: GateContext) -> GateResult:
    exp = ctx.expected_frames
    if ctx.video_path is None or not ctx.video_path.exists():
        return GateResult("C-duration", "Thời lượng", False, ["chưa có video"])
    n = ffprobe_stream(ctx.video_path)["frames"]
    ok = n == exp
    return GateResult("C-duration", "Thời lượng", ok, {"expected_frames": exp, "video_frames": n} if ok
                      else [f"ffprobe đếm {n} khung ≠ {exp} (sai lệch cho phép: 0 khung)"])


def c_format(ctx: GateContext) -> GateResult:
    if ctx.video_path is None or not ctx.video_path.exists():
        return GateResult("C-format", "Định dạng", False, ["chưa có video"])
    fmt = contracts.load_format()
    info = ffprobe_stream(ctx.video_path)
    w, h = contracts.frame_size(ctx.chunk["aspect"])
    errs = []
    if ctx.preview:
        errs.append("bản xem trước (--preview): không đạt định dạng chuẩn, không được giao")
    if info["fps"] != fmt["fps"]:
        errs.append(f"fps {info['fps']} ≠ {fmt['fps']}")
    if (info["width"], info["height"]) != (w, h):
        errs.append(f"độ phân giải {info['width']}x{info['height']} ≠ {w}x{h} ({ctx.chunk['aspect']})")
    if info["codec"] != fmt["codec"] or info["pix_fmt"] != fmt["pix_fmt"]:
        errs.append(f"codec {info['codec']}/{info['pix_fmt']} ≠ {fmt['codec']}/{fmt['pix_fmt']}")
    return GateResult("C-format", "Định dạng", not errs, errs or info)


def _blank_frames(frames_dir: Path, n: int, step_target: int = 48) -> tuple[list[int], list[str]]:
    step = max(1, n // step_target)
    idxs = sorted(set(list(range(0, n, step)) + [n - 1]))
    errs = []
    for i in idxs:
        p = frames_dir / (config.FRAME_PATTERN % i)
        if not p.exists():
            errs.append(f"thiếu khung {i}")
        elif is_blank(Image.open(p), config.BLANK_FRAME_MEAN_LOW, config.BLANK_FRAME_MEAN_HIGH, config.BLANK_FRAME_STD_MAX):
            errs.append(f"khung {i} đen/trắng trơn")
    return idxs, errs


def c_visual(ctx: GateContext) -> GateResult:
    if ctx.frames_dir is None:
        return GateResult("C-visual", "Hình ảnh chung", False, ["chưa có khung hình"])
    idxs, errs = _blank_frames(ctx.frames_dir, ctx.expected_frames)
    return GateResult("C-visual", "Hình ảnh chung", not errs,
                      errs or f"{len(idxs)} khung mẫu không đen/trắng; engine không vẽ chữ nên không có chữ bị cắt")


def no_captions_in_frames(frames_dir: Path, indices: list[int], text: str) -> list[tuple[int, list[str]]]:
    """[(khung, các từ lời thoại OCR đọc được)] — rỗng = không có phụ đề in cứng."""
    found = []
    for i in indices:
        words = burned_caption_words(frames_dir / (config.FRAME_PATTERN % i), text)
        if words:
            found.append((i, words))
    return found


def c_no_captions(ctx: GateContext) -> GateResult:
    if ctx.frames_dir is None:
        return GateResult("C-no-captions", "Không phụ đề", False, ["chưa có khung hình"])
    if not ocr_available():
        return GateResult("C-no-captions", "Không phụ đề", False, ["thiếu tesseract: không kiểm được thì không giao"])
    mid = ctx.expected_frames // 2
    found = no_captions_in_frames(ctx.frames_dir, [mid], ctx.chunk["text"])
    return GateResult("C-no-captions", "Không phụ đề", not found,
                      [f"khung {i}: OCR đọc ra {w}" for i, w in found] or f"OCR khung giữa ({mid}) không ra chữ của lời thoại")


def _used_assets(shots: list[dict[str, Any]]) -> set[tuple[str, str]]:
    used: set[tuple[str, str]] = set()
    for s in shots:
        used.add((s["set"], "set"))
        for m in s["cast"]:
            used.add((m["id"], "character"))
            for p in m.get("props", []):
                used.add((p, "prop"))
    return used


def c_license(ctx: GateContext) -> GateResult:
    errs = []
    for aid, kind in sorted(_used_assets(ctx.shots)):
        try:
            ctx.registry.require(aid, kind)
        except RegistryError as e:
            errs.append(str(e))
    return GateResult("C-license", "Giấy phép chung", not errs,
                      errs or "mọi tài sản dùng thương mại được; engine không gọi provider trả phí")


# ================================================================ cổng riêng cartoon3d
def g1_schema(ctx: GateContext) -> GateResult:
    errs = []
    for s in ctx.shots:
        errs += [f"{s.get('shot_id', '?')} {e}" for e in validate("shot", s)]
        if not str(s.get("shot_id", "")).startswith(ctx.chunk["chunk_id"] + "_s"):
            errs.append(f"shot_id {s.get('shot_id')} không mang chunk_id {ctx.chunk['chunk_id']}")
        if s.get("look_id") != ctx.chunk["look_id"]:
            errs.append(f"{s.get('shot_id')}: look_id {s.get('look_id')} ≠ chunk {ctx.chunk['look_id']}")
    total = sum(s["duration_ms"] for s in ctx.shots)
    if total != ctx.chunk["end_ms"] - ctx.chunk["start_ms"]:
        errs.append(f"tổng duration_ms của shot = {total} ≠ thời lượng chunk")
    return GateResult("G1", "Schema", not errs, errs or f"{len(ctx.shots)} shot đúng shot.schema.json")


def g2_license(ctx: GateContext) -> GateResult:
    errs = []
    for row in ctx.registry.all_rows():
        errs += [f"registry[{row.get('asset_id')}] {e}" for e in validate("asset", row)]
    used = _used_assets(ctx.shots)
    for aid, kind in sorted(used):
        try:
            ctx.registry.require(aid, kind)
        except RegistryError as e:
            errs.append(str(e))
    return GateResult("G2", "Giấy phép", not errs, errs or f"{len(used)} tài sản có trong registry, commercial_ok = true")


def g3_duration(ctx: GateContext) -> GateResult:
    exp = ctx.expected_frames
    details: dict[str, Any] = {"expected_frames": exp, "fps": ctx.fps,
                               "shot_frames": [b["render"]["n_frames"] for b in ctx.bundles]}
    errs = []
    if sum(details["shot_frames"]) != exp:
        errs.append(f"tổng khung các shot {sum(details['shot_frames'])} ≠ {exp}")
    if ctx.frames_dir is not None:
        n = len(list(ctx.frames_dir.glob("frame_*.png")))
        details["frames_on_disk"] = n
        if n != exp:
            errs.append(f"số file khung {n} ≠ {exp}")
    if ctx.video_path is not None and ctx.video_path.exists():
        details["video_frames"] = ffprobe_stream(ctx.video_path)["frames"]
        if details["video_frames"] != exp:
            errs.append(f"ffprobe đếm {details['video_frames']} khung ≠ {exp}")
    return GateResult("G3", "Thời lượng", not errs, errs or details)


ROUND_SHAPES = {"cylinder", "sphere"}


def g4_geometry(ctx: GateContext) -> GateResult:
    errs = []
    for b in ctx.bundles:
        geo = b["style"].get("geometry", {})
        min_seg = int(geo.get("min_segments", 32))
        if min_seg < 32:
            errs.append(f"style {b['style']['style_id']} min_segments = {min_seg} < 32")
        if geo.get("crease_angle_deg") != 140:
            errs.append(f"style {b['style']['style_id']} crease_angle_deg = {geo.get('crease_angle_deg')}, phải cố định 140")
        sources = [(f"set {b['set']['asset_id']}", b["set"].get("objects", []))]
        sources += [(f"prop {pid}", p.get("objects", [])) for pid, p in b["props"].items()]
        sources += [(f"character {cid}", [dict(v, name=k) for k, v in ch.get("parts", {}).items()])
                    for cid, ch in b["characters"].items()]
        for label, objs in sources:
            for o in objs:
                if o.get("shape") in ROUND_SHAPES and int(o.get("segments", 0)) < 32:
                    errs.append(f"{b['shot']['shot_id']}: {label}/{o.get('name')} {o['shape']} có {o.get('segments', 0)} mặt < 32")
    return GateResult("G4", "Hình khối", not errs, errs or f"vật tròn ≥ 32 mặt, crease 140° ở {len(ctx.bundles)} shot")


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / n, v[1] / n, v[2] / n) if n else (0.0, 0.0, 1.0)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def in_frame(cam_pos, look_at, fov_deg: float, aspect: float, point, tol: float = config.FRAMING_TOLERANCE) -> bool:
    fwd = _norm(_sub(look_at, cam_pos))
    up0 = (0.0, 1.0, 0.0) if abs(fwd[1]) < 0.999 else (0.0, 0.0, -1.0)
    right = _norm(_cross(fwd, up0))
    up = _cross(right, fwd)
    d = _sub(point, cam_pos)
    z = _dot(d, fwd)
    if z <= 0.05:
        return False
    tan_v = math.tan(math.radians(fov_deg) / 2)
    return abs(_dot(d, up) / z) <= tan_v * tol and abs(_dot(d, right) / z) <= tan_v * aspect * tol


def g5_camera(ctx: GateContext) -> GateResult:
    errs: list[str] = []
    checked = 0
    for b in ctx.bundles:
        shot, cams, aspect = b["shot"], b["tracks"]["camera"], b["render"]["aspect"]
        visible = b["tracks"]["visible_cast"]
        heights = {cid: float(ch.get("height_m", 1.7)) for cid, ch in b["characters"].items()}
        need_subject = b["sensitivity"]["device"] not in ("cut_away", "offscreen_sound", "symbol_object") and bool(visible)
        subject = None
        if need_subject:
            la = shot["camera"].get("look_at")
            subject = la if isinstance(la, str) and la in visible else visible[0]
        out_of_frame = 0
        for i, cam in enumerate(cams):
            checked += 1
            for cid in visible:
                p = b["tracks"]["cast"][cid][i]["position"]
                dist = math.dist(cam["position"], (p[0], p[1] + heights[cid] / 2, p[2]))
                if dist < config.CAMERA_MIN_DISTANCE_M:
                    errs.append(f"{shot['shot_id']} khung {i}: máy quay cách {cid} {dist:.2f} m < {config.CAMERA_MIN_DISTANCE_M}")
                    break
            if subject:
                p = b["tracks"]["cast"][subject][i]["position"]
                if not in_frame(cam["position"], cam["look_at"], cam["fov_deg"], aspect,
                                (p[0], p[1] + heights[subject] / 2, p[2])):
                    out_of_frame += 1
        if subject and out_of_frame:
            errs.append(f"{shot['shot_id']}: chủ thể {subject} nằm ngoài khung ở {out_of_frame}/{len(cams)} khung")
        if len(errs) > 20:
            errs = errs[:20] + ["…"]
            break
    return GateResult("G5", "Máy quay", not errs, errs or f"đo {checked} khung: không xuyên nhân vật, chủ thể trong khung")


def g6_image(ctx: GateContext) -> GateResult:
    if ctx.frames_dir is None:
        return GateResult("G6", "Hình ảnh", False, ["chưa có khung hình"])
    idxs, errs = _blank_frames(ctx.frames_dir, ctx.expected_frames, step_target=ctx.expected_frames)
    return GateResult("G6", "Hình ảnh", not errs,
                      errs or f"soát cả {len(idxs)} khung: không đen/trắng; contact sheet chờ agent tự xem")


def g7_sensitivity(ctx: GateContext) -> GateResult:
    level = ctx.chunk["sensitivity"]
    allowed = allowed_devices(level)
    errs = [f"{s['shot_id']}: thủ pháp '{s['sensitivity_device']}' không được phép ở mức {level} (được: {allowed})"
            for s in ctx.shots if s["sensitivity_device"] not in allowed]
    return GateResult("G7", "Nhạy cảm", not errs, errs or f"mức {level} → {[s['sensitivity_device'] for s in ctx.shots]}")


def g8_no_captions(ctx: GateContext) -> GateResult:
    if ctx.frames_dir is None:
        return GateResult("G8", "Không phụ đề", False, ["chưa có khung hình"])
    if not ocr_available():
        return GateResult("G8", "Không phụ đề", False, ["thiếu tesseract: không kiểm được thì không giao"])
    idxs = _sample_indices(ctx.expected_frames, config.OCR_SAMPLE_FRAMES)
    found = no_captions_in_frames(ctx.frames_dir, idxs, ctx.chunk["text"])
    return GateResult("G8", "Không phụ đề", not found,
                      [f"khung {i}: OCR đọc ra {w}" for i, w in found] or f"OCR {len(idxs)} khung mẫu {idxs}: không ra chữ")


COMMON_PRE = [c_license]
COMMON_POST = [c_duration, c_format, c_visual, c_no_captions]  # c_schema chạy cuối, khi đã có render_output
PRE_RENDER = [g1_schema, g2_license, g4_geometry, g5_camera, g7_sensitivity]
POST_RENDER = [g3_duration, g6_image, g8_no_captions]
ORDER = ["C-schema", "C-duration", "C-format", "C-visual", "C-no-captions", "C-license",
         "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]


def _gate_id(fn) -> str:
    name = fn.__name__
    if name.startswith("c_"):
        return {"c_schema": "C-schema", "c_duration": "C-duration", "c_format": "C-format", "c_visual": "C-visual",
                "c_no_captions": "C-no-captions", "c_license": "C-license"}[name]
    return name.split("_")[0].upper()


def _run(gates, ctx: GateContext) -> list[GateResult]:
    results = []
    for g in gates:
        try:
            results.append(g(ctx))
        except Exception as e:  # cổng lỗi kỹ thuật cũng là trượt, không được âm thầm qua
            results.append(GateResult(_gate_id(g), g.__name__, False, [f"lỗi khi kiểm: {type(e).__name__}: {e}"]))
    return results


def run_pre_render_gates(ctx: GateContext) -> list[GateResult]:
    return _run(COMMON_PRE + PRE_RENDER, ctx)


def run_post_render_gates(ctx: GateContext) -> list[GateResult]:
    return _run(COMMON_POST + POST_RENDER, ctx)


def report(results: list[GateResult], contact_sheet: Path | None = None) -> dict[str, Any]:
    by_id = {r.id: r for r in results}
    ordered = [by_id[i] for i in ORDER if i in by_id] + [r for r in results if r.id not in ORDER]
    rep: dict[str, Any] = {"passed": all(r.passed for r in ordered), "gates": [r.as_dict() for r in ordered]}
    if contact_sheet is not None:
        rep["contact_sheet"] = str(contact_sheet)
    return rep
