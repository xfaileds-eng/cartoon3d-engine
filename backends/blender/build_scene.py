"""build_scene.py — dựng cảnh Blender (bpy) từ cùng scene_bundle.json mà backend Three.js dùng.

Chạy bên trong Blender:  blender --background --python backends/blender/render.py -- --bundle ... --out ...
Module này chỉ dựng; render.py đặt keyframe máy quay theo track và xuất khung.
Giai đoạn P3 của lộ trình: chưa chạy trong CI, giữ cùng hợp đồng để thay backend không đụng spec.
"""
from __future__ import annotations

import math
from typing import Any

try:
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore
except ImportError:  # pragma: no cover - ngoài Blender
    bpy = None
    Vector = None

CREASE_ANGLE_DEG = 140


def _hex(c: str) -> tuple[float, float, float, float]:
    c = c.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    # sRGB → linear cho Blender
    lin = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return (lin(r), lin(g), lin(b), 1.0)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_material(name: str, color: str, style: dict[str, Any], emissive: str | None = None,
                  override: str | None = None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    if override == "silhouette":
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value = _hex(style.get("sensitivity", {}).get("silhouette_color", "#000000"))
        links.new(emit.outputs[0], out.inputs[0])
        return mat
    if style.get("material", {}).get("type") == "toon":
        # Toon: Diffuse → Shader to RGB → Color Ramp bậc thang (gradient_steps)
        diff = nodes.new("ShaderNodeBsdfDiffuse")
        diff.inputs["Color"].default_value = _hex(color)
        to_rgb = nodes.new("ShaderNodeShaderToRGB")
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.interpolation = "CONSTANT"
        steps = int(style["material"].get("gradient_steps", 4))
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0.25, 0.25, 0.25, 1)
        ramp.color_ramp.elements[1].position = 1.0 - 1.0 / steps
        ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
        for k in range(1, steps - 1):
            e = ramp.color_ramp.elements.new(k / steps)
            v = 0.25 + 0.75 * k / (steps - 1)
            e.color = (v, v, v, 1)
        mix = nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        mix.inputs["Color1"].default_value = _hex(color)
        emit = nodes.new("ShaderNodeEmission")
        links.new(diff.outputs[0], to_rgb.inputs[0])
        links.new(to_rgb.outputs["Color"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], mix.inputs["Color2"])
        links.new(mix.outputs[0], emit.inputs["Color"])
        links.new(emit.outputs[0], out.inputs[0])
    else:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = _hex(color)
        bsdf.inputs["Roughness"].default_value = 0.9
        if emissive:
            bsdf.inputs["Emission Color"].default_value = _hex(emissive)
            bsdf.inputs["Emission Strength"].default_value = 2.0
        links.new(bsdf.outputs[0], out.inputs[0])
    return mat


def add_primitive(o: dict[str, Any], style: dict[str, Any], parent=None, override: str | None = None):
    seg = max(int(style.get("geometry", {}).get("min_segments", 32)), int(o.get("segments", 0)))
    shape = o["shape"]
    if shape == "box":
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.active_object
        obj.scale = tuple(o["size"])
    elif shape == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=seg, radius=o["radius"], depth=o["height"])
        obj = bpy.context.active_object
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=max(16, seg // 2), radius=o["radius"])
        obj = bpy.context.active_object
    elif shape == "plane":
        bpy.ops.mesh.primitive_plane_add(size=1)
        obj = bpy.context.active_object
        obj.scale = (o["size"][0], o["size"][1], 1)
    else:
        raise ValueError(f"shape '{shape}' chưa hỗ trợ")
    obj.name = o.get("name", shape)
    # Three.js dùng Y lên; Blender dùng Z lên: (x, y, z) → (x, -z, y)
    p = o.get("position", [0, 0, 0])
    obj.location = (p[0], -p[2], p[1])
    rx, ry, rz = (math.radians(v) for v in o.get("rotation", [0, 0, 0]))
    obj.rotation_euler = (rx + math.radians(90) if shape == "cylinder" and False else rx, -rz, ry)
    if shape == "cylinder":
        # trục cylinder Three.js là Y (lên) → Blender là Z: không cần xoay thêm sau phép đổi trục
        pass
    mat = make_material(f"{obj.name}_mat", o["color"], style, o.get("emissive"), override)
    obj.data.materials.append(mat)
    obj.data.use_auto_smooth = True if hasattr(obj.data, "use_auto_smooth") else None
    if hasattr(obj.data, "auto_smooth_angle"):
        obj.data.auto_smooth_angle = math.radians(CREASE_ANGLE_DEG)
    if parent is not None:
        obj.parent = parent
    return obj


def add_lights(style: dict[str, Any], dim: float = 1.0) -> None:
    for l in style.get("lights", []):
        if l["type"] == "directional":
            data = bpy.data.lights.new("sun", "SUN")
            data.energy = 3.0 * l["intensity"] * dim
            data.color = _hex(l["color"])[:3]
            data.use_shadow = bool(l.get("shadow"))
            obj = bpy.data.objects.new("sun", data)
            p = l["position"]
            obj.location = (p[0], -p[2], p[1])
            obj.rotation_euler = Vector((p[0], -p[2], p[1])).to_track_quat("Z", "Y").to_euler()
            bpy.context.collection.objects.link(obj)
        elif l["type"] == "hemisphere":
            world = bpy.context.scene.world or bpy.data.worlds.new("world")
            bpy.context.scene.world = world
            world.use_nodes = True
            bg = world.node_tree.nodes.get("Background")
            if bg:
                bg.inputs["Color"].default_value = _hex(l["sky"])
                bg.inputs["Strength"].default_value = 0.6 * l["intensity"] * dim


def build_biped(cid: str, ch: dict[str, Any], style: dict[str, Any], override: str | None):
    """Người khối: gốc ở chân, mặt hướng -Y của Blender (= +Z của Three.js)."""
    P = ch["parts"]
    root = bpy.data.objects.new(f"cast:{cid}", None)
    bpy.context.collection.objects.link(root)
    leg_h, torso_h, head_r = P["leg_l"]["size"][1], P["torso"]["size"][1], P["head"]["radius"]
    parts = {
        "torso": dict(P["torso"], position=[0, leg_h + torso_h / 2, 0]),
        "head": dict(P["head"], position=[0, leg_h + torso_h + head_r * 1.05, 0]),
        "arm_l": dict(P["arm_l"], position=[-(P["torso"]["size"][0] / 2 + P["arm_l"]["size"][0] / 2), leg_h + torso_h - 0.04 - P["arm_l"]["size"][1] / 2, 0]),
        "arm_r": dict(P["arm_r"], position=[(P["torso"]["size"][0] / 2 + P["arm_r"]["size"][0] / 2), leg_h + torso_h - 0.04 - P["arm_r"]["size"][1] / 2, 0]),
        "leg_l": dict(P["leg_l"], position=[-P["torso"]["size"][0] / 4, leg_h / 2, 0]),
        "leg_r": dict(P["leg_r"], position=[P["torso"]["size"][0] / 4, leg_h / 2, 0]),
    }
    if "hat" in P:
        parts["hat"] = dict(P["hat"], position=[0, leg_h + torso_h + head_r * 1.8 + P["hat"].get("height", 0.1) / 2, 0])
    if "apron" in P:
        parts["apron"] = dict(P["apron"], position=[0, leg_h + torso_h / 2 - 0.05, P["torso"]["size"][2] / 2 + P["apron"]["size"][2] / 2])
    for name, spec in parts.items():
        add_primitive(dict(spec, name=f"{cid}.{name}"), style, parent=root, override=override)
    natural = leg_h + torso_h + head_r * 2.1 + (P.get("hat", {}).get("height", 0))
    s = ch.get("height_m", natural) / natural
    root.scale = (s, s, s)
    return root


def build_voxel(cid: str, ch: dict[str, Any], style: dict[str, Any], override: str | None):
    root = bpy.data.objects.new(f"cast:{cid}", None)
    bpy.context.collection.objects.link(root)
    vs = ch.get("voxel_size", 0.1)
    mats: dict[str, Any] = {}
    for i, (x, y, z, color) in enumerate(ch["voxels"]):
        bpy.ops.mesh.primitive_cube_add(size=vs)
        obj = bpy.context.active_object
        obj.name = f"{cid}.v{i}"
        obj.location = (x * vs, -z * vs, y * vs + vs / 2)
        key = "sil" if override == "silhouette" else color
        if key not in mats:
            mats[key] = make_material(f"{cid}_{key}", color, style, override=override)
        obj.data.materials.append(mats[key])
        obj.parent = root
    return root


def build_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Dựng toàn bộ cảnh; trả về {cast_id: object gốc} để render.py đặt keyframe."""
    style, set_data, spec = bundle["style"], bundle["set"], bundle["sensitivity"]["spec"]
    clear_scene()
    scene = bpy.context.scene
    bg = style["sensitivity"].get("diagram_background") if spec.get("background_override") == "diagram" else style["renderer"]["background"]
    world = bpy.data.worlds.new("world")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = _hex(bg)
    add_lights(style, float(spec.get("dim", 1.0)))
    for o in set_data.get("objects", []):
        add_primitive(o, style)
    roots: dict[str, Any] = {}
    override = "silhouette" if spec.get("cast_material") == "silhouette" else None
    for member in bundle["shot"]["cast"]:
        ch = bundle["characters"][member["id"]]
        if member["action"] == "hidden" or spec.get("hide_cast"):
            continue
        if spec.get("cast_material") == "marker":
            root = add_primitive({"name": f"cast:{member['id']}", "shape": "cylinder", "radius": 0.35, "height": 0.08,
                                  "segments": 32, "color": "#ff5a5f", "position": [0, 0.04, 0]}, style)
        elif ch.get("rig") == "voxel_static" or ch.get("style") == "voxel":
            root = build_voxel(member["id"], ch, style, override)
        else:
            root = build_biped(member["id"], ch, style, override)
        roots[member["id"]] = root
    if spec.get("symbol"):
        for pid, prop in bundle["props"].items():
            sym = bpy.data.objects.new("symbol", None)
            bpy.context.collection.objects.link(sym)
            for o in prop["objects"]:
                add_primitive(o, style, parent=sym)
            k = style["sensitivity"].get("symbol_scale", 1.6)
            sym.scale = (k, k, k)
            roots["__symbol__"] = sym
            break
    return roots
