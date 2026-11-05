import math

import pytest

from core.camera_library import camera_track, fill_from_preset, interp
from core.motion import cast_track, point_on_path
from core.registry import Registry


@pytest.mark.parametrize("name", ["linear", "ease_in", "ease_out", "ease_in_out", "constant", "bounce"])
def test_interp_endpoints(name):
    assert interp(name, 0.0) == pytest.approx(0.0, abs=1e-9) or name == "constant"
    assert interp(name, 1.0) == pytest.approx(1.0, abs=1e-9)


def test_interp_rejects_after_effects_names():
    with pytest.raises(ValueError):
        interp("easeInOut", 0.5)


def test_ease_in_out_is_symmetric():
    assert interp("ease_in_out", 0.25) == pytest.approx(1 - interp("ease_in_out", 0.75))


def test_fill_from_preset_completes_dolly():
    reg = Registry()
    vault = reg.load("cheese_vault", "set")
    cam = fill_from_preset({"move": "dolly"}, vault)
    assert cam["from"] and cam["to"] and cam["look_at"] == "target_empty"
    assert cam["interp"] == "ease_in_out"


def test_fill_from_preset_missing_param_raises():
    with pytest.raises(ValueError):
        fill_from_preset({"move": "orbit"}, {"asset_id": "x", "points": {}})


def test_point_on_path_walks_full_length():
    pts = [[0, 0, 0], [0, 0, -4], [3, 0, -4]]
    p, yaw = point_on_path(pts, 0)
    assert p == [0, 0, 0] and yaw == pytest.approx(180.0)
    p, yaw = point_on_path(pts, 7)
    assert p == pytest.approx([3, 0, -4]) and yaw == pytest.approx(90.0)


def test_dolly_track_hits_endpoints(shot_example):
    reg = Registry()
    vault = reg.load("cheese_vault", "set")
    n = 25
    tracks = {"cheesemaker": cast_track(shot_example["cast"][0], vault, n)}
    poses = camera_track(shot_example["camera"], vault, tracks, {"cheesemaker": 1.75}, n, shot_example["duration_ms"])
    assert len(poses) == n
    assert list(poses[0].position) == pytest.approx(shot_example["camera"]["from"])
    assert list(poses[-1].position) == pytest.approx(shot_example["camera"]["to"])
    assert list(poses[0].look_at) == pytest.approx(vault["points"]["target_empty"])


def test_orbit_keeps_radius():
    reg = Registry()
    hall = reg.load("bank_hall", "set")
    cam = fill_from_preset({"move": "orbit"}, hall)
    poses = camera_track(cam, hall, {}, {}, 10, 2000)
    c = cam["center"]
    for p in poses:
        assert math.hypot(p.position[0] - c[0], p.position[2] - c[2]) == pytest.approx(cam["radius"])


def test_track_to_follows_cast():
    reg = Registry()
    hall = reg.load("bank_hall", "set")
    member = {"id": "banker", "action": "walk", "path": "to_counter"}
    tracks = {"banker": cast_track(member, hall, 12)}
    cam = {"move": "track_to", "target": "banker", "look_at": "banker", "interp": "linear"}
    poses = camera_track(cam, hall, tracks, {"banker": 1.8}, 12, 3000)
    off = hall["camera_presets"]["track_to"]["offset"]
    for pose, tr in zip(poses, tracks["banker"]):
        assert list(pose.position) == pytest.approx([tr["position"][k] + off[k] for k in range(3)])


def test_cut_switches_positions():
    reg = Registry()
    hall = reg.load("bank_hall", "set")
    cam = fill_from_preset({"move": "cut", "look_at": "counter_mark"}, hall)
    poses = camera_track(cam, hall, {}, {}, 9, 3000)
    seen = {tuple(p.position) for p in poses}
    assert len(seen) == len(cam["positions"])
