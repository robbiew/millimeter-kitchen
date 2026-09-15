import json
import shutil

import pytest

from mmk.model import load_kitchen
from mmk.rules import validate
from tests.conftest import BAD, EXAMPLES, WARN

EXPECTED_RULE = {
    "run_too_long": "run_closure",
    "dishwasher_against_wall": "appliance_side_clearance",
    "wall_cabinet_over_window": "opening_conflict",
    "wrong_size_front": "front_fit",
    "missing_filler": "wall_filler_min",
    "zero_width_filler": "cut_width_min",
    "run_overlap": "run_overlap",
    "corner_swing": "corner_swing",
    "blocked_drain": "service_conflict",
    "front_rows_mismatch": "front_fit",
}


def errors(findings):
    return [f for f in findings if f.is_error]


def test_fitting_kitchen_has_no_errors():
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    findings = validate(k)
    assert errors(findings) == [], [f.render() for f in errors(findings)]
    # every run closes on its span
    for run in k.runs:
        assert abs(run.used - run.length) <= 3, (run.wall, run.level, run.used, run.length)


def test_fitting_kitchen_warns_until_catalog_is_verified(tmp_path):
    import json
    import shutil
    from tests.conftest import CATALOG

    findings = validate(load_kitchen(EXAMPLES / "kitchen.fits.json"))
    assert not any(f.rule == "unverified_dimensions" for f in findings)   # every item it uses was checked on ikea.com
    # the same kitchen against a catalog where one of its frames is not verified
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    data = json.loads(CATALOG.read_text())
    next(i for i in data["items"] if i["id"] == "frame:base:30x24x30")["verified"] = False
    (tmp_path / "cat.json").write_text(json.dumps(data))
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    kit["catalog"] = "cat.json"
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    findings = validate(load_kitchen(tmp_path / "kitchen.json"))
    assert any(f.rule == "unverified_dimensions" and "frame:base:30x24x30" in f.message for f in findings)


@pytest.mark.parametrize("name,rule", EXPECTED_RULE.items(), ids=list(EXPECTED_RULE))
def test_each_bad_fixture_fails_with_its_rule(name, rule):
    findings = validate(load_kitchen(BAD / f"{name}.json"))
    errs = errors(findings)
    assert errs, f"{name} produced no errors"
    hit = [f for f in errs if f.rule == rule]
    assert hit, f"{name}: expected rule {rule}, got {[f.rule for f in errs]}"
    assert hit[0].wall == "N"
    assert hit[0].item or hit[0].extra, hit[0].render()


def test_bad_fixtures_differ_from_fits_by_one_thing():
    # each bad case must not trip unrelated rules (other than the one under test and rules it drags along)
    allowed_extra = {"dishwasher_against_wall": {"wall_filler_min", "corner_overlap", "corner_swing"}}  # a dishwasher in the corner also collides with the east run and cannot open into it
    for name, rule in EXPECTED_RULE.items():
        rules = {f.rule for f in errors(validate(load_kitchen(BAD / f"{name}.json")))}
        assert rules <= {rule} | allowed_extra.get(name, set()), (name, rules)


def test_placed_intervals_are_contiguous():
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    for run in k.runs:
        cursor = run.start
        for p in run.items:
            assert p.start == cursor
            cursor = p.end


def test_sink_base_covers_drain():
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    n_base = next(r for r in k.runs if r.wall == "N" and r.level == "base")
    sink = next(p for p in n_base.items if p.label == "N-sink-36")
    assert sink.start <= 1676 < sink.end


def test_unknown_catalog_id_is_reported(tmp_path):
    import json
    src = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    src["runs"][0]["items"][1]["id"] = "frame:base:99x24x30"
    (tmp_path / "room.example.json").write_text((EXAMPLES / "room.example.json").read_text())
    p = tmp_path / "k.json"
    p.write_text(json.dumps(src))
    rules = {f.rule for f in errors(validate(load_kitchen(p)))}
    assert "unknown_item" in rules


def test_non_ikea_front_is_rejected(tmp_path):
    import json
    from tests.conftest import CATALOG
    cat = json.loads(CATALOG.read_text())
    cat["items"].append({
        "id": "front:other:door:15x30", "kind": "front", "type": "door", "brand": "Semihandmade", "name": "x",
        "nominal": "15x30", "nominal_in": {"w": 15, "h": 30}, "actual": {"w": 378, "h": 759}, "verified": False,
    })
    (tmp_path / "cat.json").write_text(json.dumps(cat))
    src = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    src["catalog"] = "cat.json"
    src["runs"][0]["items"][1]["fronts"] = [{"id": "front:other:door:15x30", "count": 1}]
    (tmp_path / "room.example.json").write_text((EXAMPLES / "room.example.json").read_text())
    p = tmp_path / "k.json"
    p.write_text(json.dumps(src))
    rules = {f.rule for f in errors(validate(load_kitchen(p)))}
    assert "ikea_fronts_only" in rules


def _fits_with(mutate, tmp_path):
    """The fitting kitchen after one change to its north base run, as a Kitchen."""
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    mutate(kit["runs"][0]["items"])
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    return load_kitchen(tmp_path / "kitchen.json")


@pytest.mark.parametrize("kind,width,expect", [
    ("filler", 25, False), ("filler", 24, True), ("filler", 0, True),    # the 25 mm boundary
    ("panel", 25, False), ("panel", 24, True),                           # panels are cut strips too
    ("gap", 1, False), ("gap", 0, True),                                 # a gap is an open span: any width, but a width
])
def test_cut_width_min_boundaries(tmp_path, kind, width, expect):
    def mutate(items):
        items.insert(2, {"kind": kind, "label": "N-cut", "width": width})
        items[0]["width"] -= width   # keep the run closed: take it from the 76 mm left filler
    hits = [f for f in errors(validate(_fits_with(mutate, tmp_path))) if f.rule == "cut_width_min"]
    assert bool(hits) is expect, [f.render() for f in hits]
    if expect:
        assert hits[0].item == "N-cut" and hits[0].wall == "N" and hits[0].extra["width_mm"] == width


def _warnings(k, rule):
    return [f for f in validate(k) if not f.is_error and f.rule == rule]


def test_exposed_side_warns_with_the_pack(tmp_path):
    """Warning-only rules have no bad fixture: they run on copies of the fitting kitchen (docs/BUILD_ORDER.md)."""
    from mmk.purchase import derive

    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    n_wall2 = kit["runs"][2]
    n_wall2["items"][-1] = {"kind": "gap", "label": "N-wall-gap", "width": n_wall2["items"][-1]["width"]}   # a gap in place of the filler
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    k = load_kitchen(tmp_path / "kitchen.json")
    w = [x for x in _warnings(k, "exposed_side") if x.item == "N-wall-21"]   # besides the two sides at the window
    assert [(x.wall, x.item, x.extra["side"]) for x in w] == [("N", "N-wall-21", "end")] and "N-wall-gap" in w[0].message and "cover panel" in w[0].message
    assert not errors(validate(k))                                    # it still fits; buying is where it matters
    pack = derive(k)
    assert any(l.rule == "cover panel" and "N-wall-21 end side is exposed to the gap 'N-wall-gap'" in l.detail for l in pack.lines)
    fits = load_kitchen(EXAMPLES / "kitchen.fits.json")
    assert {x.item for x in _warnings(fits, "exposed_side")} == {"N-wall-30", "N-wall-36"}   # the two sides at the window, as the pack has always said


def test_filler_stock_warns_for_a_filler_wider_than_its_panel(tmp_path):
    from mmk.purchase import filler_stock_width

    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    stock = filler_stock_width(load_kitchen(EXAMPLES / "kitchen.fits.json"), "base")
    items = kit["runs"][0]["items"]
    leg, gap = items[-2], items[-1]
    leg["width"], gap["width"] = stock + 40, gap["width"] - 40 - (stock - leg["width"])   # the north leg grows past one panel; the gap gives it up
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    k = load_kitchen(tmp_path / "kitchen.json")
    w = _warnings(k, "filler_stock")
    assert [(x.item, x.extra["stock_mm"]) for x in w] == [("N-filler-corner", stock)] and f"{stock + 40} mm" in w[0].message
    assert not errors(validate(k))
    assert _warnings(load_kitchen(EXAMPLES / "kitchen.fits.json"), "filler_stock") == []


def test_backsplash_window_warns_and_a_lower_band_clears_it(tmp_path):
    fits = load_kitchen(EXAMPLES / "kitchen.fits.json")
    w = _warnings(fits, "backsplash_window")
    band_top = fits.legs + 762 + fits.counter_thickness + fits.backsplash_height    # 1409 in the example
    assert [(x.wall, x.item, x.extra) for x in w] == [("N", "sink window", {"overlap_mm": band_top - 1067, "from": 1219, "to": 2133})]
    assert "sill 1067 mm" in w[0].message
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    kit["backsplash_height"] = 1067 - (fits.legs + 762 + fits.counter_thickness)   # the band stops at the sill
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    assert _warnings(load_kitchen(tmp_path / "kitchen.json"), "backsplash_window") == []


EXPECTED_WARNING = {"exposed_side": "exposed_side", "filler_stock": "filler_stock", "backsplash_window": "backsplash_window"}


@pytest.mark.parametrize("name,rule", EXPECTED_WARNING.items(), ids=list(EXPECTED_WARNING))
def test_each_warn_fixture_fits_with_its_warning(name, rule):
    """examples/warn/: the fitting kitchen with one change that still fits but draws the rule's warning."""
    findings = validate(load_kitchen(WARN / f"{name}.json"))
    assert not errors(findings), name
    hit = [f for f in findings if not f.is_error and f.rule == rule]
    assert hit, f"{name}: expected warning {rule}, got {[f.rule for f in findings]}"
    assert hit[0].wall == "N" and (hit[0].item or hit[0].extra)


def test_warn_fixtures_add_one_warning_to_the_fitting_kitchen():
    base = {f.rule for f in validate(load_kitchen(EXAMPLES / "kitchen.fits.json")) if not f.is_error}
    for name, rule in EXPECTED_WARNING.items():
        got = {f.rule for f in validate(load_kitchen(WARN / f"{name}.json")) if not f.is_error}
        assert got <= base | {rule}, (name, got - base)


def test_exposed_side_ignores_panels_and_touching_runs(tmp_path):
    """A cover panel at an open end is not a cabinet side, and two runs that meet on one wall hide each other's ends."""
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    n_wall2 = kit["runs"][2]
    n_wall2["items"][-1] = {"kind": "panel", "label": "N-wall-end-panel", "width": n_wall2["items"][-1]["width"]}
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    assert {x.item for x in _warnings(load_kitchen(tmp_path / "kitchen.json"), "exposed_side")} == {"N-wall-30", "N-wall-36"}
    # split the north base run in two at the sink: the halves touch, so neither end shows
    kit = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    n_base = kit["runs"][0]
    left, right = n_base["items"][:3], n_base["items"][3:]
    kit["runs"][0] = {"wall": "N", "level": "base", "to": 1219, "items": left}
    kit["runs"].append({"wall": "N", "level": "base", "from": 1219, "items": right})
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    k = load_kitchen(tmp_path / "kitchen.json")
    assert not errors(validate(k)) and not any(x.wall == "N" and k.runs[0].level == "base" and x.item in ("N-base-30", "N-sink-36") for x in _warnings(k, "exposed_side"))


def test_filler_stock_counts_panels_in_the_pack(tmp_path):
    from mmk.purchase import derive, filler_stock_width

    k = load_kitchen(WARN / "filler_stock.json")
    stock = filler_stock_width(k, "base")
    line = next(l for l in derive(k).lines if l.rule == "filler stock" and "base" in l.detail)
    assert line.qty >= 2 and "700" in line.detail                     # a 700 mm strip alone needs a second panel
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    kit = json.loads((WARN / "filler_stock.json").read_text())
    kit["room"] = "room.example.json"
    kit["runs"][0]["items"][-2]["kind"] = "panel"                       # the same strip as a panel counts the same way
    (tmp_path / "kitchen.json").write_text(json.dumps(kit))
    k2 = load_kitchen(tmp_path / "kitchen.json")
    line2 = next(l for l in derive(k2).lines if l.rule == "filler stock" and "base" in l.detail)
    assert line2.qty == line.qty and [x.item for x in _warnings(k2, "filler_stock")] == ["N-filler-corner"] and stock < 700


def test_backsplash_window_overlap_is_clamped_to_the_window(tmp_path):
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    room = json.loads((EXAMPLES / "room.example.json").read_text())
    win = next(o for o in room["walls"][0]["openings"] if o["kind"] == "window")
    win["sill"], win["head"] = 1000, 1100                               # a short window entirely inside the band
    (tmp_path / "room.example.json").write_text(json.dumps(room))
    shutil.copy(EXAMPLES / "kitchen.fits.json", tmp_path / "kitchen.json")
    w = _warnings(load_kitchen(tmp_path / "kitchen.json"), "backsplash_window")
    assert [x.extra["overlap_mm"] for x in w] == [100]
