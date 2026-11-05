"""8 cổng kiểm. Một chunk chỉ được trả về nhạc trưởng khi qua đủ 8 cổng.

Cổng trước render (đọc spec và bundle): G1 G2 G4 G5 G7.
Cổng sau render (đọc khung hình, video, kế hoạch phụ đề): G3 G6 G8.
"""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from PIL import Image, ImageStat

from .. import config
from ..registry import Registry, RegistryError
from ..sensitivity import allowed_devices
from ..timing import frames_for, ms_to_frame

_SCHEMAS: dict[str, Any] = {}


def schema(name: str) -> dict[str, Any]:
    if name not in _SCHEMAS:
        _SCHEMAS[name] = json.loads((config.SPECS_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return _SCHEMAS[name]


def validate(name: str, data: Any) -> list[str]:
    v = jsonschema.Draft202012Validator(schema(name))
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
    frames_dir: Path | None = None          # khung của cả chunk, sau khi ghép shot
    video_path: Path | None = None
    caption_plan: dict[str, Any] | None = None
    render_output: dict[str, Any] | None = None

    @property
    def expected_frames(self) -> int:
        return frames_for(self.chunk["end_ms"] - self.chunk["start_ms"], self.fps)


# ---------------------------------------------------------------- G1
def g1_schema(ctx: GateContext) -> GateResult:
    errs = [f"chunk {e}" for e in validate("chunk_input", ctx.chunk)]
    if ctx.chunk["end_ms"] <= ctx.chunk["start_ms"]:
        errs.append("chunk end_ms phải lớn hơn start_ms")
    for s in ctx.shots:
        errs += [f"{s.get('shot_id', '?')} {e}" for e in validate("shot", s)]
        if not str(s.get("shot_id", "")).startswith(ctx.chunk["chunk_id"] + "_s"):
            errs.append(f"shot_id {s.get('shot_id')} không mang chunk_id {ctx.chunk['chunk_id']}")
    total = sum(s["duration_ms"] for s in ctx.shots)
    if total != ctx.chunk["end_ms"] - ctx.chunk["start_ms"]:
        errs.append(f"tổng duration_ms của shot = {total} ≠ thời lượng chunk {ctx.chunk['end_ms'] - ctx.chunk['start_ms']}")
    if ctx.render_output is not None:
        errs += [f"render_output {e}" for e in validate("render_output", ctx.render_output)]
    return GateResult("G1", "Schema", not errs, errs or "chunk, shot (và render_output) đúng schema")


# ---------------------------------------------------------------- G2
def g2_license(ctx: GateContext) -> GateResult:
    errs = []
    for row in ctx.registry.all_rows():
        errs += [f"registry[{row.get('asset_id')}] {e}" for e in validate("asset", row)]
    used: set[tuple[str, str]] = set()
    for s in ctx.shots:
        used.add((s["set"], "set"))
        for m in s["cast"]:
            used.add((m["id"], "character"))
            for p in m.get("props", []):
                used.add((p, "prop"))
    for aid, kind in sorted(used):
        try:
            ctx.registry.require(aid, kind)
        except RegistryError as e:
            errs.append(str(e))
    return GateResult("G2", "Giấy phép", not errs, errs or f"{len(used)} tài sản có trong registry, commercial_ok = true")


# ---------------------------------------------------------------- G3
def ffprobe_frames(video: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.strip()
    return int(out.splitlines()[0])


def g3_duration(ctx: GateContext) -> GateResult:
    expected = ctx.expected_frames
    details: dict[str, Any] = {"expected_frames": expected, "fps": ctx.fps,
                               "duration_ms": ctx.chunk["end_ms"] - ctx.chunk["start_ms"]}
    errs = []
    per_shot = [b["render"]["n_frames"] for b in ctx.bundles]
    details["shot_frames"] = per_shot
    if sum(per_shot) != expected:
        errs.append(f"tổng khung các shot {sum(per_shot)} ≠ {expected}")
    if ctx.frames_dir is not None:
        n = len(list(ctx.frames_dir.glob("frame_*.png")))
        details["frames_on_disk"] = n
        if n != expected:
            errs.append(f"số file khung {n} ≠ {expected}")
    if ctx.video_path is not None:
        if not ctx.video_path.exists():
            errs.append(f"không thấy video {ctx.video_path}")
        else:
            n = ffprobe_frames(ctx.video_path)
            details["video_frames"] = n
            if n != expected:
                errs.append(f"ffprobe đếm {n} khung ≠ {expected}")
    return GateResult("G3", "Thời lượng", not errs, errs or details)


# ---------------------------------------------------------------- G4
ROUND_SHAPES = {"cylinder", "sphere"}


def g4_geometry(ctx: GateContext) -> GateResult:
    errs = []
    for b in ctx.bundles:
        geo = b["style"].get("geometry", {})
        min_seg = int(geo.get("min_segments", 32))
        crease = geo.get("crease_angle_deg")
        if crease != 140:
            errs.append(f"{b['shot']['shot_id']}: style {b['style']['style_id']} crease_angle_deg = {crease}, phải cố định 140")
        sources: list[tuple[str, list[dict[str, Any]]]] = [(f"set {b['set']['asset_id']}", b["set"].get("objects", []))]
        for pid, prop in b["props"].items():
            sources.append((f"prop {pid}", prop.get("objects", [])))
        for cid, ch in b["characters"].items():
            parts = ch.get("parts", {})
            sources.append((f"character {cid}", [dict(v, name=k) for k, v in parts.items()]))
        for label, objs in sources:
            for o in objs:
                if o.get("shape") in ROUND_SHAPES and int(o.get("segments", 0)) < min_seg:
                    errs.append(f"{b['shot']['shot_id']}: {label}/{o.get('name')} {o['shape']} có {o.get('segments', 0)} mặt < {min_seg}")
    return GateResult("G4", "Hình khối", not errs, errs or f"vật tròn ≥ 32 mặt, crease 140° ở {len(ctx.bundles)} shot")


# ---------------------------------------------------------------- G5
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
    x, y = _dot(d, right), _dot(d, up)
    tan_v = math.tan(math.radians(fov_deg) / 2)
    return abs(y / z) <= tan_v * tol and abs(x / z) <= tan_v * aspect * tol


def g5_camera(ctx: GateContext) -> GateResult:
    errs = []
    checked = 0
    for b in ctx.bundles:
        shot = b["shot"]
        cams = b["tracks"]["camera"]
        aspect = b["render"]["aspect"]
        visible = b["tracks"]["visible_cast"]
        heights = {cid: float(ch.get("height_m", 1.7)) for cid, ch in b["characters"].items()}
        device = b["sensitivity"]["device"]
        need_subject = device not in ("cut_away", "offscreen_sound", "symbol_object") and bool(visible)
        subject = None
        if need_subject:
            la = shot["camera"].get("look_at")
            subject = la if isinstance(la, str) and la in visible else visible[0]
        out_of_frame = 0
        for i, cam in enumerate(cams):
            checked += 1
            for cid in visible:
                p = b["tracks"]["cast"][cid][i]["position"]
                center = (p[0], p[1] + heights[cid] / 2, p[2])
                dist = math.dist(cam["position"], center)
                if dist < config.CAMERA_MIN_DISTANCE_M:
                    errs.append(f"{shot['shot_id']} khung {i}: máy quay cách {cid} {dist:.2f} m < {config.CAMERA_MIN_DISTANCE_M}")
                    break
            if subject:
                p = b["tracks"]["cast"][subject][i]["position"]
                center = (p[0], p[1] + heights[subject] / 2, p[2])
                if not in_frame(cam["position"], cam["look_at"], cam["fov_deg"], aspect, center):
                    out_of_frame += 1
        if subject and out_of_frame:
            errs.append(f"{shot['shot_id']}: chủ thể {subject} nằm ngoài khung ở {out_of_frame}/{len(cams)} khung")
        if len(errs) > 20:
            errs = errs[:20] + ["…"]
            break
    return GateResult("G5", "Máy quay", not errs, errs or f"đo {checked} khung: không xuyên nhân vật, chủ thể trong khung")


# ---------------------------------------------------------------- G6
def frame_stats(path: Path) -> tuple[float, float]:
    img = Image.open(path).convert("L")
    st = ImageStat.Stat(img)
    return st.mean[0], st.stddev[0]


def g6_image(ctx: GateContext) -> GateResult:
    if ctx.frames_dir is None:
        return GateResult("G6", "Hình ảnh", False, ["chưa có khung hình để kiểm"])
    n = ctx.expected_frames
    step = max(1, n // 48)
    idxs = sorted(set(list(range(0, n, step)) + [n - 1]))
    errs = []
    for i in idxs:
        p = ctx.frames_dir / (config.FRAME_PATTERN % i)
        if not p.exists():
            errs.append(f"thiếu khung {i}")
            continue
        mean, std = frame_stats(p)
        if std < config.BLANK_FRAME_STD_MAX and (mean < config.BLANK_FRAME_MEAN_LOW or mean > config.BLANK_FRAME_MEAN_HIGH):
            errs.append(f"khung {i} gần như {'đen' if mean < 128 else 'trắng'} (mean {mean:.1f}, std {std:.1f})")
    if ctx.caption_plan and ctx.caption_plan.get("mode") != "none":
        w, h = ctx.caption_plan["width"], ctx.caption_plan["height"]
        for it in ctx.caption_plan["items"]:
            x0, y0, x1, y1 = it["box"]
            if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
                errs.append(f"chữ '{it['word']}' bị cắt khỏi khung {it['box']}")
    return GateResult("G6", "Hình ảnh", not errs, errs or f"xem {len(idxs)} khung mẫu: không đen/trắng, chữ không bị cắt")


# ---------------------------------------------------------------- G7
def g7_sensitivity(ctx: GateContext) -> GateResult:
    level = int(ctx.chunk["sensitivity"])
    allowed = allowed_devices(level)
    errs = [f"{s['shot_id']}: thủ pháp '{s['sensitivity_device']}' không được phép ở mức {level} (được: {allowed})"
            for s in ctx.shots if s["sensitivity_device"] not in allowed]
    return GateResult("G7", "Nhạy cảm", not errs, errs or f"mức {level} → {[s['sensitivity_device'] for s in ctx.shots]}")


# ---------------------------------------------------------------- G8
def g8_captions(ctx: GateContext) -> GateResult:
    modes = {s["captions"]["mode"] for s in ctx.shots}
    plan = ctx.caption_plan
    if modes == {"none"}:
        return GateResult("G8", "Phụ đề", True, "shot không có phụ đề")
    if plan is None:
        return GateResult("G8", "Phụ đề", False, ["shot yêu cầu phụ đề nhưng chưa có captions_plan"])
    if plan.get("mode") == "none":
        words = ctx.chunk.get("words") or []
        return GateResult("G8", "Phụ đề", not words, "chunk không có timeline từ" if not words else ["có words nhưng kế hoạch phụ đề rỗng"])
    errs = []
    w, h = plan["width"], plan["height"]
    mx, my = w * plan["safe_area_pct"] / 100, h * plan["safe_area_pct"] / 100
    words = ctx.chunk["words"]
    n = ctx.expected_frames
    for it in plan["items"]:
        x0, y0, x1, y1 = it["box"]
        # chữ "pop" to hơn 15% được nhô lên trên hộp một chút, vẫn phải trong vùng an toàn
        pop_rise = it["font_size"] * 0.15
        if x0 < mx - 1 or x1 > w - mx + 1 or y0 - pop_rise < my - 1 or y1 > h - my + 1:
            errs.append(f"'{it['word']}' hộp {it['box']} ra ngoài vùng an toàn {plan['safe_area_pct']}%")
        src = words[it["index"]]
        exp_start = max(0, ms_to_frame(src["start_ms"] - ctx.chunk["start_ms"], ctx.fps))
        if it["start_frame"] != exp_start:
            errs.append(f"'{it['word']}' bắt đầu khung {it['start_frame']} ≠ SRT {exp_start}")
        if it["end_frame"] > n:
            errs.append(f"'{it['word']}' kết thúc {it['end_frame']} vượt {n} khung")
    if len(plan["items"]) != len(words):
        errs.append(f"kế hoạch có {len(plan['items'])} từ, SRT có {len(words)}")
    return GateResult("G8", "Phụ đề", not errs, errs or f"{len(words)} từ khớp mốc, nằm trong vùng an toàn")


PRE_RENDER = [g1_schema, g2_license, g4_geometry, g5_camera, g7_sensitivity]
POST_RENDER = [g3_duration, g6_image, g8_captions]
ALL = [g1_schema, g2_license, g3_duration, g4_geometry, g5_camera, g6_image, g7_sensitivity, g8_captions]


def _run(gates, ctx: GateContext) -> list[GateResult]:
    results = []
    for g in gates:
        try:
            results.append(g(ctx))
        except Exception as e:  # cổng lỗi kỹ thuật cũng là trượt, không được âm thầm qua
            gid = g.__name__.split("_")[0].upper()
            results.append(GateResult(gid, g.__name__, False, [f"lỗi khi kiểm: {type(e).__name__}: {e}"]))
    return results


def run_pre_render_gates(ctx: GateContext) -> list[GateResult]:
    return _run(PRE_RENDER, ctx)


def run_post_render_gates(ctx: GateContext) -> list[GateResult]:
    return _run(POST_RENDER, ctx)


def run_gates(ctx: GateContext) -> list[GateResult]:
    return _run(ALL, ctx)


def report(results: list[GateResult], contact_sheet: Path | None = None) -> dict[str, Any]:
    results = sorted(results, key=lambda r: r.id)
    rep: dict[str, Any] = {"passed": all(r.passed for r in results), "gates": [r.as_dict() for r in results]}
    if contact_sheet is not None:
        rep["contact_sheet"] = str(contact_sheet)
    return rep
