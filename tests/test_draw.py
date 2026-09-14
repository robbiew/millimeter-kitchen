"""Phase 2 acceptance: the SVG geometry is the file's millimeters, labels carry nominal + id,
and the title block lists totals and fillers."""

import re
import xml.etree.ElementTree as ET

import pytest

from mmk.cli import main
from mmk.draw import elevation_svg, plan_svg, write_drawings
from mmk.model import load_kitchen
from tests.conftest import BAD, EXAMPLES

NS = {"s": "http://www.w3.org/2000/svg"}


@pytest.fixture(scope="module")
def kitchen():
    return load_kitchen(EXAMPLES / "kitchen.fits.json")


@pytest.fixture(scope="module")
def elevation_n(kitchen):
    return ET.fromstring(elevation_svg(kitchen, "N", scale=20))


def test_page_size_is_viewbox_over_scale(elevation_n):
    vb = [float(x) for x in elevation_n.get("viewBox").split()]
    w_mm = float(elevation_n.get("width").rstrip("m"))
    h_mm = float(elevation_n.get("height").rstrip("m"))
    assert elevation_n.get("width").endswith("mm") and elevation_n.get("data-scale") == "1:20"
    assert abs(w_mm - vb[2] / 20) < 0.01 and abs(h_mm - vb[3] / 20) < 0.01


def test_every_cabinet_rect_is_its_catalog_width(kitchen, elevation_n):
    n_base = next(r for r in kitchen.runs if r.wall == "N" and r.level == "base")
    rects = {r.get("data-label"): r for r in elevation_n.iterfind(".//s:rect[@data-label]", NS)}
    assert len(rects) == sum(len(r.items) for r in kitchen.runs if r.wall == "N")
    for p in n_base.items:
        r = rects[p.label]
        assert float(r.get("width")) == p.width
        if p.catalog_item:
            assert float(r.get("width")) == p.catalog_item.w
            assert float(r.get("height")) == p.catalog_item.h
        if p.appliance:
            assert float(r.get("height")) == p.appliance.height
    # items are contiguous along x, in file order
    xs = [float(rects[p.label].get("x")) for p in n_base.items]
    ws = [float(rects[p.label].get("width")) for p in n_base.items]
    for x0, w0, x1 in zip(xs, ws, xs[1:]):
        assert x0 + w0 == x1


def test_base_cabinets_sit_on_legs_and_wall_cabinets_at_bottom_height(kitchen, elevation_n):
    rects = {r.get("data-label"): r for r in elevation_n.iterfind(".//s:rect[@data-label]", NS)}
    floor_y = None
    for ln in elevation_n.iterfind(".//s:line[@class='floor']", NS):
        floor_y = float(ln.get("y1"))
        break
    base = rects["N-base-15"]
    assert floor_y - (float(base.get("y")) + float(base.get("height"))) == kitchen.legs
    wall = rects["N-wall-15"]
    assert floor_y - (float(wall.get("y")) + float(wall.get("height"))) == kitchen.wall_cabinet_bottom


def test_labels_carry_nominal_and_catalog_id(elevation_n):
    texts = [t.text for t in elevation_n.iterfind(".//s:text", NS) if t.text]
    assert "36x24x30" in texts and "sink_base:36x24x30" in texts
    assert "18x24x30" in texts and "base:18x24x30" in texts


def test_title_block_lists_totals_and_fillers(elevation_n):
    texts = " | ".join(t.text for t in elevation_n.iterfind(".//s:text", NS) if t.text)
    assert "planning length 3655 mm" in texts
    assert "base run 0–3655: 3655 mm used of 3655 · fillers 76 mm, 74 mm" in texts
    assert "3655 mm overall" in texts


def test_running_dimensions_match_item_widths(kitchen, elevation_n):
    n_base = next(r for r in kitchen.runs if r.wall == "N" and r.level == "base")
    labels = {t.text for t in elevation_n.iterfind(".//s:text[@class='s']", NS) if t.text}
    for p in n_base.items:
        assert str(p.width) in labels
    for p in n_base.items:
        assert str(p.start) in labels and str(p.end) in labels


def test_doors_and_drawers_are_split(elevation_n):
    fronts = list(elevation_n.iterfind(".//s:rect[@class='front']", NS))
    # N-base-30 has two doors, N-base-15-drawers has three drawer fronts; at least those
    assert len(fronts) >= 5


def test_plan_depths_match_catalog(kitchen):
    root = ET.fromstring(plan_svg(kitchen))
    polys = {p.get("data-label"): p for p in root.iterfind(".//s:polygon[@data-label]", NS)}
    for run in kitchen.runs:
        for p in run.items:
            if p.catalog_item and p.catalog_item.d:
                assert int(polys[p.label].get("data-depth")) == p.catalog_item.d
            if p.appliance:
                assert int(polys[p.label].get("data-depth")) == p.appliance.depth
    # a polygon's long edge equals the item width
    pts = [tuple(map(float, xy.split(","))) for xy in polys["N-sink-36"].get("points").split()]
    assert abs(pts[1][0] - pts[0][0]) == 914


def test_write_drawings_one_per_wall_plus_plan(kitchen, tmp_path):
    files = write_drawings(kitchen, tmp_path)
    assert sorted(f.name for f in files) == ["elevation-E.svg", "elevation-N.svg", "plan.svg"]
    for f in files:
        ET.parse(f)  # well-formed


def test_cli_refuses_to_draw_invalid_kitchen(tmp_path, capsys):
    assert main(["draw", str(BAD / "run_too_long.json"), "--out", str(tmp_path)]) == 1
    assert not list(tmp_path.glob("*.svg"))
    assert main(["draw", str(BAD / "run_too_long.json"), "--out", str(tmp_path), "--force"]) == 0
    assert len(list(tmp_path.glob("*.svg"))) == 3


def test_cli_draw_fits(tmp_path):
    assert main(["draw", str(EXAMPLES / "kitchen.fits.json"), "--out", str(tmp_path), "--scale", "50"]) == 0
    root = ET.parse(tmp_path / "elevation-N.svg").getroot()
    assert root.get("data-scale") == "1:50"
    assert re.match(r"^[\d.]+mm$", root.get("width"))
