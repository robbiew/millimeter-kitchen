"""Out-of-square corners: the surveyed angle drives the plan, the scene, where the next run may start,
and the filler the first wall needs at the corner."""

import json
import math
import shutil

import pytest

from mmk.draw import corner_clearances
from mmk.edit import apply
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen, wall_frames
from mmk.room import room_from_dict
from mmk.rules import validate
from mmk.scene import build_scene
from tests.conftest import EXAMPLES

# diagonals for the example room (3660 x 2745 at counter height) at chosen corner angles
DIAG = {85: 4379, 88: 4498, 90: 4575, 92: 4651}


E_CABINETS_FROM = 1086   # where the fitting kitchen's east cabinets start (its dead corner)


def _ws(tmp_path, theta, kitchen="kitchen.fits.json", e_from=610):
    """The example at a surveyed corner angle, with the east runs pulled back to e_from behind a longer corner filler
    leg, so the cabinets stay where they are (the range over its gas stub) and the corner rules have something to say."""
    room = json.loads((EXAMPLES / "room.example.json").read_text())
    room["corners"][0]["diagonal"] = DIAG[theta]
    (tmp_path / "room.example.json").write_text(json.dumps(room))
    src = json.loads((EXAMPLES / kitchen).read_text())
    if kitchen == "kitchen.fits.json":
        for run in src["runs"]:
            if run["wall"] == "E" and run["level"] == "base":   # the wall run keeps its open notch; a leg there would hide the north wall door
                run["from"] = e_from
                run["items"][0]["width"] = E_CABINETS_FROM - e_from
    (tmp_path / "k.json").write_text(json.dumps(src))
    return tmp_path / "k.json"


def errors(f):
    return {x.rule for x in f if x.is_error}


def test_corner_angle_from_the_diagonal(room_data):
    assert room_from_dict(room_data).corner_angle("N", "E") == pytest.approx(90.0, abs=0.1)
    for theta, d in DIAG.items():
        r = dict(room_data)
        r["corners"] = [{"walls": ["N", "E"], "diagonal": d}]
        assert room_from_dict(r).corner_angle("N", "E") == pytest.approx(theta, abs=0.1)
    r["corners"] = []
    assert room_from_dict(r).corner_angle("N", "E") == 90.0


def test_clearances_at_88_and_92(tmp_path):
    k = load_kitchen(_ws(tmp_path, 88))
    g = corner_clearances(k, "N", "E", "base")
    assert g["theta"] == pytest.approx(88, abs=0.1) and g["depth_a"] == 610
    assert g["min_start_b"] == math.ceil((610 + 610 * math.cos(math.radians(88))) / math.sin(math.radians(88)))  # 632
    assert g["min_end_filler_a"] == math.ceil(610 / math.tan(math.radians(88)))                             # 22
    (tmp_path / "b").mkdir()
    k = load_kitchen(_ws(tmp_path / "b", 92))
    g = corner_clearances(k, "N", "E", "base")
    assert g["min_start_b"] == 611 and g["min_end_filler_a"] == 0


def test_acute_corner_pushes_the_next_run_out(tmp_path):
    k = _ws(tmp_path, 88)
    f = validate(load_kitchen(k))
    assert errors(f) == {"corner_overlap"}
    e = next(x for x in f if x.rule == "corner_overlap")
    assert "632 mm" in e.message and "88.0°" in e.message and e.wall == "E"
    # start the east runs where the geometry says (base and wall together, so the hood stays over the range) and it fits again
    src = json.loads(k.read_text())
    run = src["runs"][3]                # the base run; the wall run keeps its open notch at 1010
    run["from"] = 632
    run["items"][0]["width"] = E_CABINETS_FROM - 632
    k.write_text(json.dumps(src))
    assert errors(validate(load_kitchen(k))) == set()


def test_obtuse_corner_needs_no_change(tmp_path):
    assert errors(validate(load_kitchen(_ws(tmp_path, 92)))) == set()


def test_acute_corner_needs_a_wider_filler_on_the_first_wall(tmp_path):
    k = _ws(tmp_path, 85, e_from=666)   # at 85 degrees the east runs must start at 666
    assert errors(validate(load_kitchen(k))) == set()
    # the dead gap at the corner keeps the last cabinet's front corner clear of the wall; shrink it below the 54 mm the angle asks and the rule speaks
    res = apply(k, [{"op": "set_width", "label": "N-corner-dead", "width": 51}, {"op": "set_width", "label": "N-filler-corner", "width": 283 + 629 - 51}])
    assert not res.ok and {f.rule for f in res.errors} == {"corner_filler"}
    assert "85.0°" in res.errors[0].message and "at least 54 mm" in res.errors[0].message


def test_plan_and_scene_follow_the_angle(tmp_path):
    k = load_kitchen(_ws(tmp_path, 85, "kitchen.fits.json"))
    fr = wall_frames(k.room)
    hx, hy = fr["E"][2], fr["E"][3]
    assert math.degrees(math.atan2(hy, hx)) == pytest.approx(95.0, abs=0.2)   # turned 95°, not 90°
    boxes = read_glb_boxes(write_glb(build_scene(k), tmp_path / "s.glb"))
    e = boxes["E-base-15"]
    assert [round(v) for v in e["size_mm"]] == [381, 762, 610]              # the box itself is unchanged
    assert abs(abs(e["yaw_deg"]) - 95.0) < 0.2                              # only its orientation differs
    assert boxes["N-base-30"]["yaw_deg"] == pytest.approx(0.0, abs=1e-6)
    # a square room still reads exactly as before through the node transforms
    k0 = load_kitchen(EXAMPLES / "kitchen.fits.json")
    b0 = read_glb_boxes(write_glb(build_scene(k0), tmp_path / "s0.glb"))
    assert abs(b0["E-base-15"]["max_mm"][0] - 3655) <= 1 and abs(b0["E-base-15"]["yaw_deg"]) == pytest.approx(90.0, abs=1e-6)


def test_corner_cabinet_at_an_out_of_square_corner_warns(tmp_path):
    k = _ws(tmp_path, 88, "kitchen.corner.json")
    f = validate(load_kitchen(k))
    assert errors(f) == set()
    assert any(x.rule == "corner_out_of_square" and "scribe" in x.message for x in f)
