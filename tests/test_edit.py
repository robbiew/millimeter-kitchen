"""Phase 5 acceptance: an edit that fits is applied with a BOM diff and fresh drawings;
an edit that does not fit is refused and the file is untouched."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mmk import tools
from mmk.cli import main
from mmk.edit import EditError, apply, branch
from tests.conftest import EXAMPLES

V = "front:enkoping-walnut"


@pytest.fixture
def ws(tmp_path):
    """A working copy of the example kitchen and room."""
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    shutil.copy(EXAMPLES / "kitchen.fits.json", tmp_path / "kitchen.json")
    return tmp_path


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def drawers(w: int, heights: list[int]) -> list[dict]:
    return [{"id": f"{V}:drawer:{w}x{h}", "count": 1} for h in heights]


def test_replace_30_with_two_15s_with_drawers(ws):
    """The acceptance example: a 30 base becomes two 15s with three drawers each."""
    k = ws / "kitchen.json"
    res = apply(k, [{"op": "replace", "label": "N-base-30", "items": [
        {"kind": "cabinet", "id": "frame:base:15x24x30", "label": "N-base-15-a", "fronts": drawers(15, [5, 10, 15])},
        {"kind": "cabinet", "id": "frame:base:15x24x30", "label": "N-base-15-b", "fronts": drawers(15, [5, 10, 15])},
    ]}])
    assert res.ok and res.written, res.message
    assert res.errors == []
    diff = {d["id"]: d["delta"] for d in res.bom_diff}
    assert diff["frame:base:30x24x30"] == -1 and diff["frame:base:15x24x30"] == 2
    assert diff[f"{V}:door:15x30"] == -2 and diff[f"{V}:drawer:15x5"] == 2
    n_base = next(r for r in res.runs if r["wall"] == "N" and r["level"] == "base")
    assert n_base["used_mm"] == n_base["length_mm"] == 3655
    labels = [i["label"] for i in n_base["items"]]
    assert labels[2:4] == ["N-base-15-a", "N-base-15-b"]  # filler, 15, then the two new 15s where the 30 was
    # the file on disk now has the new items and still validates on reload
    doc = json.loads(k.read_text())
    assert [i["label"] for i in doc["runs"][0]["items"]][2:4] == ["N-base-15-a", "N-base-15-b"]


def test_impossible_edit_is_refused_and_file_untouched(ws):
    k = ws / "kitchen.json"
    before = _sha(k)
    res = apply(k, [{"op": "replace", "label": "N-base-30", "items": [{"kind": "cabinet", "id": "frame:base:36x24x30", "fronts": [{"id": f"{V}:door:18x30", "count": 2}]}]}])
    assert not res.ok and not res.written
    assert {f.rule for f in res.errors} == {"run_closure"}
    assert "152 mm too long" in res.errors[0].message
    assert _sha(k) == before


def test_batch_of_ops_is_validated_as_a_whole(ws):
    """Shrinking one cabinet and widening a filler in one call; either alone would not close."""
    k = ws / "kitchen.json"
    single = apply(k, [{"op": "replace", "label": "N-base-15-drawers", "items": [{"kind": "cabinet", "id": "frame:base:12x24x30", "fronts": [{"id": f"{V}:door:12x30", "count": 1}]}]}])
    assert not single.ok and "76 mm gap" in single.errors[0].message
    both = apply(k, [
        {"op": "replace", "label": "N-base-15-drawers", "items": [{"kind": "cabinet", "id": "frame:base:12x24x30", "fronts": [{"id": f"{V}:door:12x30", "count": 1}]}]},
        {"op": "set_width", "label": "N-filler-right", "width": 150},
    ])
    assert both.ok, both.message
    assert any(d["id"] == "frame:base:12x24x30" and d["delta"] == 1 for d in both.bom_diff)


def test_dry_run_reports_but_does_not_write(ws):
    k = ws / "kitchen.json"
    before = _sha(k)
    res = apply(k, [{"op": "set_material", "role": "counter", "key": "butcher-block-oak"}], dry_run=True)
    assert res.ok and not res.written
    assert any(d["id"] == "finish:counter" for d in res.bom_diff)
    assert _sha(k) == before


def test_unknown_finish_is_refused(ws):
    res = apply(ws / "kitchen.json", [{"op": "set_material", "role": "counter", "key": "marble-imaginary"}])
    assert not res.ok and {f.rule for f in res.errors} == {"finish_unknown"}


def test_remove_leaves_a_gap_and_is_refused(ws):
    res = apply(ws / "kitchen.json", [{"op": "remove", "label": "N-base-18-drawers"}])
    assert not res.ok and res.errors[0].rule == "run_closure"


def test_move_dishwasher_next_to_the_wall_is_refused(ws):
    ok = apply(ws / "kitchen.json", [{"op": "move", "label": "N-dishwasher", "after": "N-base-15-drawers"}], dry_run=True)
    assert ok.ok  # 74 mm filler still separates it from the wall
    res = apply(ws / "kitchen.json", [{"op": "move", "label": "N-dishwasher", "after": "N-filler-right"}])
    assert not res.ok
    assert {"appliance_side_clearance", "wall_filler_min"} <= {f.rule for f in res.errors}


def test_swap_two_cabinets(ws):
    res = apply(ws / "kitchen.json", [{"op": "swap", "label": "N-base-18-drawers", "with": "N-base-15-drawers"}])
    assert res.ok
    n_base = next(r for r in res.runs if r["wall"] == "N" and r["level"] == "base")
    labels = [i["label"] for i in n_base["items"]]
    assert labels.index("N-base-15-drawers") < labels.index("N-base-18-drawers")
    assert res.bom_diff == []  # same things, different order


def test_insert_auto_labels_and_requires_closure(ws):
    k = ws / "kitchen.json"
    res = apply(k, [
        {"op": "set_width", "label": "E-filler-right", "width": 74 + 610 - 533},
        {"op": "replace", "label": "E-base-21", "items": [{"kind": "cabinet", "id": "frame:base:24x24x30", "fronts": [{"id": f"{V}:door:12x30", "count": 2}]}]},
    ])
    assert not res.ok  # 610 replaces 533 (+77) and the filler grew by 77 too: run is 77 mm too long
    res = apply(k, [{"op": "replace", "label": "E-base-21", "items": [
        {"kind": "cabinet", "id": "frame:base:18x24x30", "fronts": [{"id": f"{V}:door:18x30", "count": 1}]},
        {"kind": "filler", "width": 76},
    ]}])
    assert res.ok, res.message
    e_base = next(r for r in res.runs if r["wall"] == "E" and r["level"] == "base")
    assert e_base["items"][0]["label"] == "E-base:18x24x30" or e_base["items"][0]["label"].startswith("E-")
    assert e_base["items"][1]["kind"] == "filler" and e_base["items"][1]["label"].startswith("E-filler")


def test_set_fronts_wrong_size_is_refused(ws):
    res = apply(ws / "kitchen.json", [{"op": "set_fronts", "label": "N-base-18-drawers", "fronts": [{"id": f"{V}:door:15x30", "count": 1}]}])
    assert not res.ok and res.errors[0].rule == "front_fit"


def test_bad_label_and_bad_op_raise(ws):
    with pytest.raises(EditError):
        apply(ws / "kitchen.json", [{"op": "remove", "label": "nope"}])
    with pytest.raises(EditError):
        apply(ws / "kitchen.json", [{"op": "teleport", "label": "N-base-30"}])


def test_duplicate_labels_are_an_error(ws):
    res = apply(ws / "kitchen.json", [{"op": "replace", "label": "N-base-15", "items": [{"kind": "cabinet", "id": "frame:base:15x24x30", "label": "N-base-15", "fronts": [{"id": f"{V}:door:15x30", "count": 1}]}]}])
    assert res.ok  # same label reused after removal is fine
    with pytest.raises(EditError):
        apply(ws / "kitchen.json", [{"op": "insert", "wall": "N", "level": "base", "index": 0, "item": {"kind": "filler", "width": 10, "label": "N-base-15"}}])


def test_branch_copies_and_names(ws):
    dst = branch(ws / "kitchen.json", "Island instead of peninsula")
    assert dst.name == "island-instead-of-peninsula.json"
    assert json.loads(dst.read_text())["name"].endswith("Island instead of peninsula")
    with pytest.raises(EditError):
        branch(ws / "kitchen.json", "Island instead of peninsula")


# ---- the tool surface the MCP server exposes

def test_tools_describe_and_search(ws):
    d = tools.describe(ws, "kitchen.json")
    assert d["ok"] and d["errors"] == []
    assert [w["id"] for w in d["walls"]] == ["N", "E"]
    assert any(i["label"] == "N-sink-36" for r in d["runs"] for i in r["items"])
    s = tools.search_catalog(ws, "kitchen.json", kind="frame", type="base", width_in=18)
    assert [i["id"] for i in s["items"]] == ["frame:base:18x24x30"]
    f = tools.list_finishes("counter")
    assert any(x["key"] == "quartz-white" and x["default"] for x in f["finishes"])


def test_tools_apply_reexports_everything(ws):
    from mmk.export import file_sha
    from mmk.gltf import read_glb_boxes
    out = tools.apply_ops(ws, "kitchen.json", [{"op": "set_material", "role": "counter", "key": "quartz-grey"}])
    assert out["ok"] and out["written"]
    ex = out["export"]
    assert len(ex["drawings"]) == 3 and ex["renders"] == []
    d = ws / "out" / "kitchen"
    for name in ("elevation-N.svg", "plan.svg", "scene.glb", "cameras.json", "manifest.json"):
        assert (d / name).exists(), name
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["source_sha256"] == file_sha(ws / "kitchen.json") and manifest["renders_current"] is False
    assert tools.describe(ws, "kitchen.json")["export_stale"] is False
    assert read_glb_boxes(d / "scene.glb")["counter N 0-3655"]["material"] == "quartz-grey"
    refused = tools.apply_ops(ws, "kitchen.json", [{"op": "remove", "label": "N-filler-left"}])
    assert not refused["ok"] and not refused["written"] and refused["errors"] and "export" not in refused
    (ws / "kitchen.json").write_text((ws / "kitchen.json").read_text() + "\n")  # a hand edit
    assert tools.describe(ws, "kitchen.json")["export_stale"] is True
    assert tools.export(ws, "kitchen.json")["ok"]
    assert tools.describe(ws, "kitchen.json")["export_stale"] is False
    assert tools.validate_kitchen(ws, "kitchen.json")["ok"]
    assert any(l["id"] == "finish:counter" and "grey" in l["name"].lower() for l in tools.bom(ws, "kitchen.json")["lines"])


def test_tools_refuse_paths_outside_root(ws):
    out = tools.describe(ws, "../../etc/passwd")
    assert not out["ok"] and "outside" in out["error"]


def test_tools_variation_and_render_export(ws):
    v = tools.start_variation(ws, "kitchen.json", "drawers everywhere")
    assert v["ok"] and v["path"] == "drawers-everywhere.json"
    r = tools.export(ws, "drawers-everywhere.json")
    assert r["ok"] and (ws / "out" / "drawers-everywhere" / "scene.glb").exists()
    assert tools.describe(ws, "drawers-everywhere.json")["export_stale"] is False
    assert tools.describe(ws, "kitchen.json")["export_stale"] is None  # never exported


def test_cli_edit(ws, capsys):
    op = json.dumps({"op": "set_material", "role": "floor", "key": "tile-slate"})
    assert main(["edit", str(ws / "kitchen.json"), op, "--out", str(ws / "out")]) == 0
    out = capsys.readouterr().out
    assert "written" in out and "finish:floor" in out and "exported to" in out
    assert (ws / "out" / "kitchen" / "scene.glb").exists()
    bad = json.dumps({"op": "remove", "label": "N-sink-36"})
    assert main(["edit", str(ws / "kitchen.json"), bad]) == 1
    assert "refused" in capsys.readouterr().out


def test_fixture_guard_and_variations_dir(tmp_path):
    """A repo-shaped tree: editing examples/ is refused; a variation of a fixture goes to variations/."""
    root = tmp_path
    ex = root / "examples"
    ex.mkdir()
    shutil.copy(EXAMPLES / "room.example.json", ex / "room.example.json")
    shutil.copy(EXAMPLES / "kitchen.fits.json", ex / "kitchen.fits.json")
    op = [{"op": "set_material", "role": "floor", "key": "tile-slate"}]
    refused = tools.apply_ops(root, "examples/kitchen.fits.json", op)
    assert not refused["ok"] and "start_variation" in refused["error"]
    assert tools.apply_ops(root, "examples/kitchen.fits.json", op, dry_run=True)["ok"]  # dry runs are fine
    v = tools.start_variation(root, "examples/kitchen.fits.json", "slate floor")
    assert v["ok"] and v["path"] == "variations/slate-floor.json"
    doc = json.loads((root / "variations" / "slate-floor.json").read_text())
    assert doc["room"] == "../examples/room.example.json"
    applied = tools.apply_ops(root, "variations/slate-floor.json", op)
    assert applied["ok"] and applied["written"]
    assert tools.apply_ops(root, "examples/kitchen.fits.json", op, allow_fixture_edit=True)["ok"]
