"""Corner cabinets: placement and overlap rules, L-shaped geometry, counter through the corner, purchase pack."""

import json
import shutil

import pytest

from mmk.edit import apply
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.purchase import derive, exposed_sides
from mmk.draw import elevation_svg, plan_svg
from mmk.rules import validate
from mmk.scene import build_scene
from tests.conftest import BAD, EXAMPLES

V = "front:enkoping-walnut"


@pytest.fixture(scope="module")
def kitchen():
    return load_kitchen(EXAMPLES / "kitchen.corner.json")


@pytest.fixture(scope="module")
def boxes(kitchen, tmp_path_factory):
    return read_glb_boxes(write_glb(build_scene(kitchen), tmp_path_factory.mktemp("c") / "scene.glb"))


def errors(findings):
    return {f.rule for f in findings if f.is_error}


def test_corner_example_fits(kitchen):
    f = validate(kitchen)
    assert errors(f) == set(), [x.render() for x in f if x.is_error]
    assert "corner_gap" not in {x.rule for x in f}


def test_overlap_fixture_is_refused():
    f = validate(load_kitchen(BAD / "corner_overlap.json"))
    assert errors(f) == {"corner_overlap"}
    e = next(x for x in f if x.rule == "corner_overlap")
    assert e.wall == "E" and e.item == "E-filler-corner" and "965 mm" in e.message


def test_dead_corner_warns_on_the_plain_example():
    f = validate(load_kitchen(EXAMPLES / "kitchen.fits.json"))
    gaps = [x for x in f if x.rule == "corner_gap"]
    assert gaps and all(not x.is_error for x in gaps)
    assert any(x.wall == "E" and "wall:" in x.message for x in gaps)


def test_carousel_is_two_legs_with_doors_on_the_notch(kitchen, boxes):
    main, leg = boxes["N-corner"], boxes["N-corner/leg"]
    L = kitchen.room.walls["N"].planning_length
    assert [round(v) for v in main["size_mm"]] == [965, 762, 610]
    assert abs(main["max_mm"][0] - L) <= 1                      # against the east wall
    assert [round(v) for v in leg["size_mm"]] == [610, 762, 355]
    assert abs(leg["min_mm"][2] - 610) <= 1 and abs(leg["max_mm"][2] - 965) <= 1
    assert abs(leg["max_mm"][0] - L) <= 1
    d1, d2 = boxes["N-corner/door1"], boxes["N-corner/door2"]
    assert abs(d1["size_mm"][0] - (355 - 6)) <= 1 and abs(d1["min_mm"][2] - 610) <= 1   # on the notch face parallel to N
    assert abs(d2["size_mm"][2] - (355 - 6)) <= 1 and abs(d2["size_mm"][0] - 19) <= 1    # on the notch face parallel to E
    assert d1["material"] == "enkoping-walnut" and "N-corner/toe_kick" in boxes and "N-corner/leg/toe_kick" in boxes


def test_wall_corner_cabinet_geometry(kitchen, boxes):
    main, leg = boxes["N-wall-corner"], boxes["N-wall-corner/leg"]
    assert [round(v) for v in main["size_mm"]] == [660, 762, 375]   # wall frames are 14 3/4" deep
    assert [round(v) for v in leg["size_mm"]] == [375, 762, 285]   # 14 3/4" leg, 660 - 375 long
    assert abs(main["min_mm"][1] - kitchen.wall_cabinet_bottom) <= 1


def test_counter_runs_through_the_corner(kitchen, boxes):
    assert "counter N 0-3655" in boxes
    east = sorted(n for n in boxes if n.startswith("counter E"))
    assert east == ["counter E 2184-2741", "counter E 648-1422"]   # starts where the north slab ends, cut by the range


def test_east_runs_are_not_exposed_and_pack_derives(kitchen):
    sides = {(r.wall, side, item.label) for r, side, item in exposed_sides(kitchen)}
    assert not any(w == "E" and side == "start" for w, side, _ in sides)
    pack = {l.id: l for l in derive(kitchen).lines}
    assert pack["frame:base_corner:38x38x30"].qty == 1 and pack[f"{V}:corner-door:13x30"].qty == 2   # one set for the base corner, one for the wall corner
    assert pack["frame:wall_corner:26x26x30"].qty == 1
    slabs = [(s["wall"], s["start"], s["end"]) for s in derive(kitchen).countertop]
    assert slabs == [("N", 0, 3655), ("E", 648, 1422), ("E", 2184, 2741)]


def test_drawings_show_the_corner(kitchen):
    plan = plan_svg(kitchen)
    assert 'data-label="N-corner/leg"' in plan and 'data-label="N-wall-corner/leg"' in plan
    elev = elevation_svg(kitchen, "N")
    assert ">corner<" in elev and "base_corner:38x38x30" in elev


def _ws(tmp_path):
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    shutil.copy(EXAMPLES / "kitchen.corner.json", tmp_path / "kitchen.json")
    return tmp_path / "kitchen.json"


def test_corner_cabinet_must_touch_the_corner(tmp_path):
    k = _ws(tmp_path)
    res = apply(k, [{"op": "swap", "label": "N-corner", "with": "N-base-12"}])
    assert not res.ok and "corner_placement" in {f.rule for f in res.errors}


def test_corner_takes_a_corner_door_of_the_right_width(tmp_path):
    k = _ws(tmp_path)
    res = apply(k, [{"op": "set_fronts", "label": "N-corner", "fronts": [{"id": f"{V}:door:24x30", "count": 1}]}])
    assert not res.ok and {f.rule for f in res.errors} == {"front_fit"}
    res = apply(k, [{"op": "set_fronts", "label": "N-corner", "fronts": [{"id": f"{V}:drawer:15x5", "count": 1}]}])
    assert not res.ok and "front_fit" in {f.rule for f in res.errors}


def test_blind_corner_variant(tmp_path):
    """Swap the carousel for a blind corner: 50 wide (it takes the 12" cabinet's place too), 24 door on the outer end, east run starts at the cabinet depth."""
    k = _ws(tmp_path)
    src = json.loads(k.read_text())
    del src["runs"][0]["items"][-2]          # N-base-12: 305 + 965 mm = the 1270 mm blind frame
    src["runs"][0]["items"][-1] = {"kind": "cabinet", "label": "N-blind", "id": "frame:base_corner_blind:50x24x30", "fronts": [{"id": f"{V}:door:24x30", "count": 1}]}
    src["runs"][2]["from"] = 610
    src["runs"][2]["items"].insert(0, {"kind": "filler", "label": "E-filler-corner", "width": 355})
    k.write_text(json.dumps(src))
    kk = load_kitchen(k)
    f = validate(kk)
    assert errors(f) == set(), [x.render() for x in f if x.is_error]
    b = read_glb_boxes(write_glb(build_scene(kk), tmp_path / "b.glb"))
    assert [round(v) for v in b["N-blind"]["size_mm"]] == [1270, 762, 610]
    assert "N-blind/leg" not in b and abs(b["N-blind/door1"]["size_mm"][0] - (610 - 6)) <= 1
    assert abs(b["N-blind/door1"]["min_mm"][0] - (3655 - 1270 + 3)) <= 1   # door on the outer end, away from the corner
