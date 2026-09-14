"""Phase 4 acceptance: one finish string changes exactly one thing in the regenerated scene,
and the bill of materials lists the fronts actually used."""

import copy
import json

import pytest

from mmk.bom import bill_of_materials
from mmk.cli import main
from mmk.finishes import ROLES, load_finishes
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.rules import validate
from mmk.scene import build_scene
from tests.conftest import EXAMPLES


def _load_variant(tmp_path, mutate):
    src = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
    mutate(src)
    (tmp_path / "room.example.json").write_text((EXAMPLES / "room.example.json").read_text())
    p = tmp_path / "k.json"
    p.write_text(json.dumps(src))
    return load_kitchen(p)


def _boxes(k, tmp_path, name):
    return read_glb_boxes(write_glb(build_scene(k), tmp_path / f"{name}.glb"))


def test_library_is_consistent():
    lib = load_finishes()
    for role in ROLES:
        assert lib.for_role(role), role
    for f in lib.finishes.values():
        assert 0 <= f.roughness <= 1 and 0 <= f.metallic <= 1 and 0 < f.alpha <= 1
        assert all(0 <= c <= 1 for c in f.color)
    for slug in ("voxtorp-walnut", "bodbyn-off-white", "axstad-matt-white"):
        assert lib[slug].role == "front" and lib[slug].brand == "IKEA"


def test_example_uses_its_declared_finishes(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    b = _boxes(k, tmp_path, "a")
    assert b["counter N 0-3655"]["material"] == "quartz-white"
    assert b["floor"]["material"] == "oak-natural"
    assert b["N-base-30/door1"]["material"] == "voxtorp-walnut"   # from the catalog front series
    assert b["N-base-30"]["material"] == "sektion-white"
    assert b["N-dishwasher"]["material"] == "stainless"


def test_changing_the_counter_finish_changes_only_the_counters(tmp_path):
    base = _boxes(load_kitchen(EXAMPLES / "kitchen.fits.json"), tmp_path, "base")

    def mutate(src):
        src["materials"]["counter"] = "butcher-block-oak"

    changed = _boxes(_load_variant(tmp_path, mutate), tmp_path, "changed")
    assert set(base) == set(changed)
    diffs = [n for n in base if base[n] != changed[n]]
    assert diffs and all(n.startswith("counter ") for n in diffs), diffs
    for n in diffs:
        assert base[n]["min_mm"] == changed[n]["min_mm"] and base[n]["max_mm"] == changed[n]["max_mm"]
        assert changed[n]["material"] == "butcher-block-oak"


def test_changing_a_front_series_changes_only_those_panels_and_the_bom(tmp_path):
    k0 = load_kitchen(EXAMPLES / "kitchen.fits.json")
    base = _boxes(k0, tmp_path, "base")

    def mutate(src):
        for run in src["runs"]:
            for item in run["items"]:
                for f in item.get("fronts", []):
                    f["id"] = f["id"].replace("voxtorp-walnut", "bodbyn-off-white")

    k1 = _load_variant(tmp_path, mutate)
    assert not [f for f in validate(k1) if f.is_error]
    changed = _boxes(k1, tmp_path, "changed")
    diffs = [n for n in base if base[n] != changed[n]]
    assert diffs and all("/door" in n or "/drawer" in n for n in diffs), diffs
    for n in diffs:
        assert base[n]["size_mm"] == changed[n]["size_mm"]
        assert changed[n]["material"] == "bodbyn-off-white"
    ids0 = {l.id for l in bill_of_materials(k0)}
    ids1 = {l.id for l in bill_of_materials(k1)}
    assert any(i.startswith("front:voxtorp-walnut") for i in ids0) and not any(i.startswith("front:voxtorp") for i in ids1)
    assert any(i.startswith("front:bodbyn-off-white") for i in ids1)


def test_unknown_or_misrole_finish_is_an_error(tmp_path):
    k = _load_variant(tmp_path, lambda s: s["materials"].__setitem__("counter", "no-such-finish"))
    assert "finish_unknown" in {f.rule for f in validate(k) if f.is_error}
    k = _load_variant(tmp_path, lambda s: s["materials"].__setitem__("counter", "oak-natural"))
    assert "finish_role" in {f.rule for f in validate(k) if f.is_error}


def test_defaults_apply_when_materials_block_is_absent(tmp_path):
    k = _load_variant(tmp_path, lambda s: s.pop("materials"))
    b = _boxes(k, tmp_path, "d")
    lib = load_finishes()
    assert b["floor"]["material"] == lib.defaults["floor"]
    assert b["counter N 0-3655"]["material"] == lib.defaults["counter"]


def test_backsplash_fills_between_counter_and_wall_cabinets(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    b = _boxes(k, tmp_path, "bs")
    top = k.legs + 762 + k.counter_thickness
    under_cabs = b["backsplash N 0-1219"]
    assert under_cabs["min_mm"][1] == pytest.approx(top, abs=1) and under_cabs["max_mm"][1] == pytest.approx(k.wall_cabinet_bottom, abs=1)
    at_window = b["backsplash N 1219-2133"]
    assert at_window["max_mm"][1] == pytest.approx(top + k.backsplash_height, abs=1)
    assert under_cabs["material"] == "tile-white-subway"


def test_bom_lists_frames_fronts_fillers_and_finishes():
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    lines = {l.id: l for l in bill_of_materials(k)}
    assert lines["frame:base:15x24x30"].qty == 2
    assert lines["front:voxtorp-walnut:door:15x30"].qty == 10  # N-base-15, N-base-30 x2, N-wall-15, N-wall-30 x2, E-base-30 x2, E-wall-30 x2
    assert lines["frame:sink_base:36x24x30"].qty == 1 and lines["frame:sink_base:36x24x30"].article is None
    assert lines["filler:cut"].qty == 6 and "76 mm" in lines["filler:cut"].detail
    assert lines["finish:counter"].name.startswith("Quartz")
    assert lines["appliance:range"].qty == 1


def test_cli_bom_and_finishes(capsys):
    assert main(["bom", str(EXAMPLES / "kitchen.fits.json")]) == 0
    out = capsys.readouterr().out
    assert "front:voxtorp-walnut:door:15x30" in out and "(unverified)" in out
    assert main(["finishes", "list", "--role", "counter"]) == 0
    out = capsys.readouterr().out
    assert "quartz-white" in out and "(default)" in out
