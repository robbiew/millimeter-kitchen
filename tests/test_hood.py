"""Wall cabinets align their tops; the cabinet over a cooktop must clear it."""

import json
import shutil

from mmk.draw import elevation_boxes, wall_run_top
from mmk.edit import apply
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.rules import validate
from mmk.scene import build_scene
from tests.conftest import EXAMPLES

V = "front:voxtorp-walnut"


def _e_wall(k):
    return next(r for r in k.runs if r.wall == "E" and r.level == "wall")


def test_tops_align_and_the_short_cabinet_sits_higher():
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    run = _e_wall(k)
    boxes = {b.p.label: b for b in elevation_boxes(k, run) if b.p.kind == "cabinet"}
    top = wall_run_top(run)
    assert top == k.wall_cabinet_bottom + 762
    assert all(b.y0 + b.h == top for b in boxes.values())
    assert boxes["E-wall-30"].y0 == k.wall_cabinet_bottom
    assert boxes["E-wall-30-hood"].y0 == top - 381         # 15 in cabinet hangs 381 lower than the top


def test_hood_clearance_is_met_in_the_examples():
    for name in ("kitchen.fits.json", "kitchen.corner.json"):
        f = validate(load_kitchen(EXAMPLES / name))
        assert not [x for x in f if x.rule in ("hood_clearance", "ceiling")], name


def test_20_inch_cabinet_over_a_gas_range_is_refused(tmp_path):
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    shutil.copy(EXAMPLES / "kitchen.fits.json", tmp_path / "k.json")
    res = apply(tmp_path / "k.json", [{"op": "replace", "label": "E-wall-30-hood", "items": [
        {"kind": "cabinet", "id": "frame:wall:30x15x20", "label": "E-wall-30-hood", "fronts": [{"id": f"{V}:door:30x20", "count": 1}]}]}])
    assert not res.ok and {f.rule for f in res.errors} == {"hood_clearance"}
    e = res.errors[0]
    assert "gas range" in e.message and "762 mm" in e.message and e.item == "E-wall-30-hood"
    # 712 mm gap: top 2134 - 508 = 1626 underside, range top 914
    assert "712 mm" in e.message


def test_explicit_run_top_and_item_bottom(tmp_path):
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    src = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    e_wall = next(r for r in src["runs"] if r["wall"] == "E" and r["level"] == "wall")
    e_wall["top"] = 2200
    e_wall["items"][0]["bottom"] = 1500     # E-wall-21 hung lower on purpose
    (tmp_path / "k.json").write_text(json.dumps(src))
    k = load_kitchen(tmp_path / "k.json")
    boxes = {b.p.label: b for b in elevation_boxes(k, _e_wall(k))}
    assert boxes["E-wall-30"].y0 + boxes["E-wall-30"].h == 2200
    assert boxes["E-wall-21"].y0 == 1500
    e_wall["top"] = 2500                    # above the 2436 ceiling
    (tmp_path / "k.json").write_text(json.dumps(src))
    f = validate(load_kitchen(tmp_path / "k.json"))
    assert "ceiling" in {x.rule for x in f if x.is_error}


def test_scene_and_backsplash_follow_the_alignment(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    b = read_glb_boxes(write_glb(build_scene(k), tmp_path / "s.glb"))
    top = k.wall_cabinet_bottom + 762
    assert abs(b["E-wall-30"]["max_mm"][1] - top) <= 1 and abs(b["E-wall-30-hood"]["max_mm"][1] - top) <= 1
    assert abs(b["E-wall-30-hood"]["min_mm"][1] - (top - 381)) <= 1
    hood_span = "backsplash E 1143-1905"   # exactly under the hood cabinet, which sits over the range
    assert hood_span in b and abs(b[hood_span]["max_mm"][1] - (top - 381)) <= 1
    assert "backsplash E 610-1143" in b and abs(b["backsplash E 610-1143"]["max_mm"][1] - k.wall_cabinet_bottom) <= 1
