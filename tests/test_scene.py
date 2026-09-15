"""Phase 3 acceptance: every placed object's bounding box in the exported glTF matches
its catalog dimensions within 1 mm, and regenerating is deterministic."""

import json

import pytest

from mmk.cli import main
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.scene import FRONT_THICKNESS, build_scene
from tests.conftest import BAD, EXAMPLES


@pytest.fixture(scope="module")
def kitchen():
    return load_kitchen(EXAMPLES / "kitchen.fits.json")


@pytest.fixture(scope="module")
def scene(kitchen):
    return build_scene(kitchen)


@pytest.fixture(scope="module")
def glb_boxes(scene, tmp_path_factory):
    path = write_glb(scene, tmp_path_factory.mktemp("glb") / "scene.glb")
    return read_glb_boxes(path)


def _placed(kitchen):
    for run in kitchen.runs:
        for p in run.items:
            if p.kind != "gap":
                yield run, p


def test_every_cabinet_box_matches_catalog_within_1mm(kitchen, glb_boxes):
    for run, p in _placed(kitchen):
        if p.kind != "cabinet" or not p.catalog_item:
            continue
        size = glb_boxes[p.label]["size_mm"]
        want = [p.catalog_item.w, p.catalog_item.h, p.catalog_item.d]  # X, Y(up), Z for a wall along X
        sx, sy, sz = size
        # width lies along the wall, depth into the room; which world axis depends on the wall
        assert abs(sy - want[1]) <= 1, (p.label, size)
        assert sorted([round(sx), round(sz)]) == sorted([want[0], want[2]]), (p.label, size)


def test_appliances_and_fillers_match(kitchen, glb_boxes):
    for run, p in _placed(kitchen):
        size = glb_boxes[p.label]["size_mm"]
        if p.appliance:
            assert abs(size[1] - p.appliance.height) <= 1
            assert min(abs(size[0] - p.appliance.width), abs(size[2] - p.appliance.width)) <= 1
        if p.kind == "filler":
            assert min(abs(size[0] - p.width), abs(size[2] - p.width)) <= 1


def test_north_wall_cabinets_lie_along_x_from_wall_start(kitchen, glb_boxes):
    n_base = next(r for r in kitchen.runs if r.wall == "N" and r.level == "base")
    for p in n_base.items:
        if p.kind == "gap":
            continue   # nothing stands in a gap
        b = glb_boxes[p.label]
        assert abs(b["min_mm"][0] - p.start) <= 1 and abs(b["max_mm"][0] - p.end) <= 1
        if p.kind != "filler":  # fillers are set back like the toe kick
            assert abs(b["min_mm"][2] - 0) <= 1  # back against the wall line (Z = 0)
    first = glb_boxes["N-base-15-drawers"]
    assert abs(first["min_mm"][1] - kitchen.legs) <= 1  # sits on legs


def test_east_wall_cabinets_lie_along_z(kitchen, glb_boxes):
    e_base = next(r for r in kitchen.runs if r.wall == "E" and r.level == "base")
    L_n = kitchen.room.walls["N"].planning_length
    for p in e_base.items:
        b = glb_boxes[p.label]
        if p.kind != "filler":
            assert abs(b["max_mm"][0] - L_n) <= 1  # back against the east wall at X = length of N
        assert abs(b["min_mm"][2] - p.start) <= 1 and abs(b["max_mm"][2] - p.end) <= 1


def test_fronts_sit_on_the_frame_face(kitchen, glb_boxes):
    frame = glb_boxes["N-base-30"]
    doors = [v for k, v in glb_boxes.items() if k.startswith("N-base-30/door")]
    assert len(doors) == 2
    for d in doors:
        assert abs(d["min_mm"][2] - frame["max_mm"][2]) <= 1
        assert abs(d["size_mm"][2] - FRONT_THICKNESS) <= 1
    drawers = [k for k in glb_boxes if k.startswith("N-base-15-drawers/drawer")]
    assert len(drawers) == 3


def test_counter_spans_run_at_counter_height(kitchen, glb_boxes):
    c = glb_boxes["counter N 0-3655"]
    assert abs(c["min_mm"][0] - 0) <= 1 and abs(c["max_mm"][0] - 3655) <= 1
    assert abs(c["min_mm"][1] - (kitchen.legs + 762)) <= 1
    assert abs(c["size_mm"][1] - kitchen.counter_thickness) <= 1


def test_counter_is_cut_around_the_range(kitchen, glb_boxes):
    counters = sorted(n for n in glb_boxes if n.startswith("counter E"))
    assert counters == ["counter E 2229-2741", "counter E 648-1467"]  # starts where the north slab's overhang ends, across the dead corner
    rng = glb_boxes["E-range"]
    for n in counters:
        c = glb_boxes[n]
        assert c["max_mm"][2] <= rng["min_mm"][2] + 1 or c["min_mm"][2] >= rng["max_mm"][2] - 1  # no overlap along the wall
    assert "counter N 0-3655" in glb_boxes  # the dishwasher stays under the counter


def test_window_cuts_the_wall(glb_boxes):
    assert "wall N under sink window" in glb_boxes and "wall N over sink window" in glb_boxes
    assert glb_boxes["wall N under sink window"]["max_mm"][1] == pytest.approx(1067, abs=1)
    assert glb_boxes["wall N over sink window"]["min_mm"][1] == pytest.approx(2032, abs=1)
    assert "window N sink window" in glb_boxes


def test_cameras_one_per_wall_plus_overview(scene):
    assert [c.name for c in scene.cameras] == ["wall-N", "wall-E", "overview"]
    n = next(c for c in scene.cameras if c.name == "wall-N")
    assert n.target[0] == pytest.approx(3655 / 2) and n.target[2] == pytest.approx(0)
    assert n.position[2] > 1500  # in front of the wall, inside the room
    # the frustum at the wall covers the floor and the top of the wall cabinets
    import math
    dist = n.position[2]
    half_v = dist * math.tan(math.radians(n.vfov_deg / 2))
    top = 1372 + 762
    assert n.target[1] - half_v <= 0 and n.target[1] + half_v >= top
    half_h = half_v * n.aspect
    assert half_h >= 3655 / 2


def test_regeneration_is_deterministic(scene, tmp_path):
    a = write_glb(scene, tmp_path / "a.glb").read_bytes()
    b = write_glb(scene, tmp_path / "b.glb").read_bytes()
    assert a == b


def test_node_extras_carry_catalog_ids(glb_boxes):
    assert glb_boxes["N-sink-36"]["extras"]["id"] == "frame:sink_base:36x24x30"
    assert glb_boxes["N-base-30/door1"]["extras"]["front"] == "front:enkoping-walnut:door:15x30"


def test_cli_render_no_render_writes_scene_and_cameras(tmp_path):
    assert main(["render", str(EXAMPLES / "kitchen.fits.json"), "--out", str(tmp_path), "--no-render"]) == 0
    assert (tmp_path / "scene.glb").exists()
    cams = json.loads((tmp_path / "cameras.json").read_text())
    assert {c["name"] for c in cams} == {"wall-N", "wall-E", "overview"}


def test_cli_render_refuses_invalid_and_reports_missing_blender(tmp_path):
    assert main(["render", str(BAD / "run_too_long.json"), "--out", str(tmp_path)]) == 1
    rc = main(["render", str(EXAMPLES / "kitchen.fits.json"), "--out", str(tmp_path), "--blender", str(tmp_path / "nope")])
    assert rc == 2
    assert (tmp_path / "scene.glb").exists()  # the export still happened


def _corner_room(tmp_path, theta):
    from tests.test_square import DIAG
    room = json.loads((EXAMPLES / "room.example.json").read_text())
    room["corners"][0]["diagonal"] = DIAG[theta]
    (tmp_path / "room.example.json").write_text(json.dumps(room))


@pytest.mark.parametrize("name,theta", [("kitchen.fits.json", 90), ("kitchen.corner.json", 90), ("kitchen.fits.json", 85), ("kitchen.fits.json", 92)])
def test_backsplash_is_continuous_through_the_inside_corner(tmp_path, name, theta):
    """The north tile reaches the corner; the east tile starts where its face meets the north tile's face; neither box
    intrudes into the other beyond the tile's own thickness, at square and surveyed off-square corners alike."""
    import math

    from mmk.draw import BACKSPLASH_THICKNESS, backsplash_corner_start

    _corner_room(tmp_path, theta)
    import shutil
    shutil.copy(EXAMPLES / name, tmp_path / "k.json")
    k = load_kitchen(tmp_path / "k.json")
    La = k.room.wall("N").planning_length
    scene = build_scene(k)
    north = [b for b in scene.boxes if b.name.startswith("backsplash N ")]
    east = [b for b in scene.boxes if b.name.startswith("backsplash E ")]
    assert north and east
    assert abs(max(b.max[0] for b in north) - La) <= 1                                   # the north tile reaches the corner
    east_run = next(r for r in k.runs if r.wall == "E" and r.level == "base")
    start = backsplash_corner_start(k, east_run)
    assert start == math.ceil(BACKSPLASH_THICKNESS / math.tan(math.radians(k.room.corner_angle("N", "E")) / 2))
    assert min(int(b.name.split()[2].split("-")[0]) for b in east) == start
    first = min(east, key=lambda b: int(b.name.split()[2].split("-")[0]))
    corners = first.world_corners()
    # world: north tile occupies x <= La, 0 <= z <= t. No east-tile corner may lie inside it by more than a millimetre;
    # its nearest corner meets the north tile's face (z = t) within the tile thickness
    t = BACKSPLASH_THICKNESS
    assert all(not (c[0] < La - 1 and 1 < c[2] < t - 1) for c in corners), corners
    nearest = min(corners, key=lambda c: (c[0] - La) ** 2 + (c[2] - t) ** 2)
    assert abs(nearest[2] - t) <= t and abs(nearest[0] - La) <= t + 1
