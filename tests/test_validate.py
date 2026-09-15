import pytest

from mmk.model import load_kitchen
from mmk.rules import validate
from tests.conftest import BAD, EXAMPLES

EXPECTED_RULE = {
    "run_too_long": "run_closure",
    "dishwasher_against_wall": "appliance_side_clearance",
    "wall_cabinet_over_window": "opening_conflict",
    "wrong_size_front": "front_fit",
    "missing_filler": "wall_filler_min",
    "zero_width_filler": "cut_width_min",
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
    allowed_extra = {"dishwasher_against_wall": {"wall_filler_min", "corner_overlap"}}  # a dishwasher in the corner also collides with the east run
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
