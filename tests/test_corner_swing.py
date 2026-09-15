"""corner_swing: fronts at an inside corner without a corner cabinet must clear the other run (issue #6)."""

import json
import math
import shutil

from mmk.model import load_kitchen
from mmk.purchase import countertop_slabs
from mmk.rules import FRONT_THICKNESS, MIN_CLEARANCE_DOOR_MM, _front_clearance, _opening_reach, validate
from tests.conftest import BAD, EXAMPLES

DIAG_85 = 4379   # the example room's diagonal at an 85 degree corner (see test_square)


def _kitchen(tmp_path, name="kitchen.fits.json", mutate=None, theta=None):
    room = json.loads((EXAMPLES / "room.example.json").read_text())
    if theta == 85:
        room["corners"][0]["diagonal"] = DIAG_85
    (tmp_path / "room.example.json").write_text(json.dumps(room))
    src = json.loads((EXAMPLES / name).read_text() if name != "corner_swing.json" else (BAD / name).read_text())
    src["room"] = "room.example.json"
    if mutate:
        mutate(src)
    (tmp_path / "k.json").write_text(json.dumps(src))
    return load_kitchen(tmp_path / "k.json")


def _item(k, label):
    return next(p for r in k.runs for p in r.items if p.label == label)


def _swing(k):
    return [f for f in validate(k) if f.rule == "corner_swing"]


def test_fixed_appliances_need_no_clearance_and_openers_do(tmp_path):
    def mutate(src):
        src["appliances"]["dishwasher"]["kind"] = "cooktop"
        src["appliances"]["fridge"] = {"name": "fridge", "kind": "fridge", "width": 762, "depth": 700, "height": 1800}
        src["runs"][0]["items"][2] = {"kind": "appliance", "label": "N-fridge", "ref": "fridge"}   # in place of the 30 base, same width
    k = _kitchen(tmp_path, mutate=mutate)
    assert _front_clearance(_item(k, "N-dishwasher")) == 0            # a cooktop has nothing that swings
    assert _front_clearance(_item(k, "E-range")) == MIN_CLEARANCE_DOOR_MM
    assert _front_clearance(_item(k, "N-fridge")) == 102               # IKEA: 4 in beside a fridge door
    assert _front_clearance(_item(k, "N-filler-corner")) == 0


def test_appliance_reach_is_its_declared_front_clearance_when_larger(tmp_path):
    k = _kitchen(tmp_path)
    dw = _item(k, "N-dishwasher")
    assert dw.appliance.depth == 622 and dw.appliance.clearance_front == 686 and _opening_reach(dw, "base") == 686
    k2 = _kitchen(tmp_path, mutate=lambda s: s["appliances"]["dishwasher"].update(clearance_front=400))
    assert _opening_reach(_item(k2, "N-dishwasher"), "base") == 622
    assert _opening_reach(_item(k, "N-base-15-drawers"), "base") == 610       # a drawer pulls out by the frame depth
    assert _opening_reach(_item(k, "N-base-30"), "base") == 381               # two doors on a 30: each swings its own width


def test_open_notch_is_measured_to_the_first_obstruction(tmp_path):
    # the bad fixture: door cabinets in the dead corner behind the east filler leg
    k = _kitchen(tmp_path, "corner_swing.json")
    assert {f.item for f in _swing(k)} == {"N-base-15", "N-base-12"}
    # the same layout with the leg replaced by a gap is an open notch: the first thing on the east wall stands beyond both doors' swing
    def open_notch(src):
        src["runs"][3]["items"][0]["kind"] = "gap"
    k = _kitchen(tmp_path, "corner_swing.json", mutate=open_notch)
    assert _swing(k) == []


def test_next_front_starts_past_the_projected_front_plane(tmp_path):
    def too_close(src):
        run = src["runs"][3]
        run["items"][0]["width"] = 25                      # a 25 mm leg: the first east front stands 654 mm along the wall
        run["items"][-1]["width"] += 457 - 25
    k = _kitchen(tmp_path, mutate=too_close)
    f = _swing(k)
    assert [x.item for x in f] == ["E-base-15"] and f[0].extra["need_start_mm"] == 610 + FRONT_THICKNESS + MIN_CLEARANCE_DOOR_MM   # 680 at a square corner
    k85 = _kitchen(tmp_path, mutate=too_close, theta=85)
    f85 = _swing(k85)
    t = math.radians(85)
    plane = math.ceil((610 + FRONT_THICKNESS + 610 * math.cos(t)) / math.sin(t))   # projected as corner_clearances projects the frames
    assert [x.item for x in f85] == ["E-base-15"] and f85[0].extra["need_start_mm"] == plane + MIN_CLEARANCE_DOOR_MM > 680
    assert "85.0°" in f85[0].message


def test_countertop_runs_over_a_dead_corner_only_behind_a_filler_leg(tmp_path):
    k = _kitchen(tmp_path)
    assert [s["start"] for s in countertop_slabs(k) if s["wall"] == "E"][0] == 648        # the leg: the slab continues from the north slab
    def cabinet_first(src):
        run = src["runs"][3]
        run["from"] = 1086
        run["items"].pop(0)
    k2 = _kitchen(tmp_path, mutate=cabinet_first)
    assert [s["start"] for s in countertop_slabs(k2) if s["wall"] == "E"][0] == 1086      # no leg: the run is its own, the slab starts with it
    def gap_first(src):   # an open span past the corner slack is not a leg either
        run = src["runs"][3]
        run["from"] = 900
        run["items"][0].update(kind="gap", width=1086 - 900)
    k3 = _kitchen(tmp_path, mutate=gap_first)
    assert [s["start"] for s in countertop_slabs(k3) if s["wall"] == "E"][0] == 900
