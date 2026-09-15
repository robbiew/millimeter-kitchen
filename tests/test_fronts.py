"""Door and drawer combinations: rows top to bottom, checked and drawn the same way."""

import json
import shutil

import pytest

from mmk.draw import front_panels, front_rows
from mmk.edit import apply
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.purchase import derive
from mmk.rules import validate
from mmk.scene import build_scene
from tests.conftest import BAD, EXAMPLES

V = "front:enkoping-walnut"


def _ws(tmp_path, name="kitchen.fits.json"):
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    shutil.copy(EXAMPLES / name, tmp_path / "k.json")
    return tmp_path / "k.json"


def _set(k, label, fronts):
    return apply(k, [{"op": "set_fronts", "label": label, "fronts": [{"id": f"{V}:{f}", "count": c} for f, c in fronts]}])


def test_rows_are_built_top_to_bottom():
    k = load_kitchen(EXAMPLES / "kitchen.corner.json")
    p = next(p for r in k.runs for p in r.items if p.label == "N-base-30")
    rows = front_rows(p)
    assert [(r["kind"], r["height_in"], len(r["panels"])) for r in rows] == [("drawer", 10, 1), ("doors", 20, 2)]


def test_drawer_over_two_doors_fits(tmp_path):
    k = _ws(tmp_path)
    res = _set(k, "N-base-30", [("drawer:30x10", 1), ("door:15x20", 2)])
    assert res.ok, res.message
    assert not [f for f in res.findings if f.rule == "front_fit"]


def test_drawer_over_one_door_and_two_drawer_rows_over_doors(tmp_path):
    k = _ws(tmp_path)
    assert _set(k, "E-base-18", [("drawer:18x10", 1), ("door:18x20", 1)]).ok
    # 5 + 5 drawers over a 20 door
    assert _set(k, "E-base-18", [("drawer:18x5", 2), ("door:18x20", 1)]).ok


@pytest.mark.parametrize("fronts,fragment", [
    ([("drawer:30x10", 1), ("door:15x15", 2)], "stack to 25"),          # rows too short
    ([("drawer:30x10", 1), ("door:15x20", 1)], "doors total 15"),        # door row too narrow
    ([("drawer:30x10", 1), ("door:15x20", 2), ("door:15x15", 1)], "doors total 15"),  # a lone 15 door row
    ([("drawer:18x10", 1), ("door:15x20", 2)], "drawer front"),          # drawer narrower than the frame
    ([("door:15x20", 1), ("door:15x15", 1), ("door:15x30", 1)], "doors total 15"),  # different heights cannot share a row
])
def test_bad_combinations_are_refused(tmp_path, fronts, fragment):
    k = _ws(tmp_path)
    res = _set(k, "N-base-30", fronts)
    assert not res.ok and {f.rule for f in res.errors} == {"front_fit"}
    assert any(fragment in f.message for f in res.errors), [f.message for f in res.errors]


def test_bad_fixture_names_the_stack():
    f = validate(load_kitchen(BAD / "front_rows_mismatch.json"))
    e = [x for x in f if x.rule == "front_fit"]
    assert e and e[0].item == "N-base-30" and "10 + 15" in e[0].message


def test_panels_tile_the_face_and_scene_matches(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.corner.json")
    run = next(r for r in k.runs if r.wall == "N" and r.level == "base")
    from mmk.draw import elevation_boxes
    b = next(b for b in elevation_boxes(k, run) if b.p.label == "N-base-30")
    panels = front_panels(b)
    assert [p["name"] for p in panels] == ["drawer1", "door1", "door2"]
    r = 3
    assert panels[0]["w"] == pytest.approx(b.w - 2 * r) and panels[0]["y0"] + panels[0]["h"] == pytest.approx(b.y0 + b.h - r)
    assert panels[1]["w"] == pytest.approx((b.w - 3 * r) / 2) and panels[2]["x"] > panels[1]["x"]
    assert panels[1]["y0"] == pytest.approx(b.y0 + r) and panels[1]["y0"] + panels[1]["h"] < panels[0]["y0"]
    assert panels[0]["h"] / panels[1]["h"] == pytest.approx(10 / 20, rel=0.02)
    boxes = read_glb_boxes(write_glb(build_scene(k), tmp_path / "s.glb"))
    d = boxes["N-base-30/drawer1"]
    assert abs(d["size_mm"][0] - panels[0]["w"]) <= 1 and abs(d["size_mm"][1] - panels[0]["h"]) <= 1
    assert boxes["N-base-30/door2"]["min_mm"][0] > boxes["N-base-30/door1"]["max_mm"][0]


def test_purchase_counts_doors_and_drawers_in_a_combo():
    k = load_kitchen(EXAMPLES / "kitchen.corner.json")
    lines = {l.id: l for l in derive(k).lines}
    assert lines["drawer:maximera:30x24:medium"].qty == 1 and lines["drawer:maximera:18x24:medium"].qty == 2
    assert lines[f"{V}:door:15x20"].qty == 2 and lines[f"{V}:door:18x20"].qty == 1
