"""Write examples/room.example.json, examples/kitchen.fits.json and examples/bad/*.json.

The fixtures are generated so that each bad kitchen is the fitting kitchen
with exactly one deliberate change. Re-run after changing the fitting layout.

Run:  python tools/make_fixtures.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
BAD = EX / "bad"

# ---- room: an L of two walls, illustrative, not a real survey -----------------
ROOM = {
    "units": "mm",
    "name": "Example L kitchen (illustrative, not surveyed)",
    "surveyed": "2026-09-14",
    "notes": "Numbers chosen to exercise the validator. Replace with a real survey per docs/SURVEY_PROTOCOL.md.",
    "walls": [
        {
            "id": "N",
            "length": {"floor": 3658, "counter": 3660, "high": 3655},
            "plumb_dev": 2,
            "openings": [{"kind": "window", "label": "sink window", "from": 1219, "width": 914, "sill": 1067, "head": 2032}],
            "services": [
                {"kind": "sink_drain", "at": 1676},
                {"kind": "water_supply", "at": 1600, "height": 500},
                {"kind": "outlet", "at": 610, "height": 1118},
                {"kind": "outlet", "at": 2900, "height": 1118},
            ],
        },
        {
            "id": "E",
            "length": {"floor": 2743, "counter": 2745, "high": 2741},
            "plumb_dev": 0,
            "services": [
                {"kind": "gas", "at": 1500, "height": 300},
                {"kind": "electrical_240v", "at": 1500, "height": 300},
                {"kind": "outlet", "at": 2300, "height": 1118},
            ],
        },
    ],
    "corners": [{"walls": ["N", "E"], "diagonal": 4575}],
    "ceiling": {"NE": 2438, "NW": 2440, "SE": 2436, "SW": 2441, "center": 2439},
    "floor_high_point": {"N": 1800, "E": 700},
}

# ---- kitchen that fits --------------------------------------------------------
V = "front:voxtorp-walnut"


def cab(id_: str, label: str, *fronts: tuple[str, int], interior: list[str] | None = None) -> dict:
    d = {"kind": "cabinet", "label": label, "id": id_, "fronts": [{"id": f, "count": n} for f, n in fronts]}
    if interior:
        d["interior"] = interior
    return d


def filler(width: int, label: str) -> dict:
    return {"kind": "filler", "label": label, "width": width}


FITS = {
    "units": "mm",
    "name": "Example L kitchen, variation A (fits)",
    "room": "room.example.json",
    "catalog": "sektion-us-2026-09",
    "notes": "Sink centered on the window; dishwasher right of sink; range on the east wall over the gas stub.",
    "counter": {"thickness": 38, "overhang_front": 38, "legs": 114, "material": "quartz"},
    "wall_cabinet_bottom": 1372,
    "backsplash_height": 457,
    "materials": {
        "frame": "sektion-white",
        "counter": "quartz-white",
        "backsplash": "tile-white-subway",
        "floor": "oak-natural",
        "wall": "paint-warm-white",
        "appliance": "stainless",
        "toe_kick": "toe-kick-white",
    },
    "appliances": {
        "dishwasher": {"name": "24in dishwasher (example)", "kind": "dishwasher", "width": 610, "depth": 622, "height": 864,
                        "clearance_front": 686, "clearance_to_wall": 51, "needs_water": True},
        "range": {"name": "30in gas range (example)", "kind": "range", "width": 762, "depth": 690, "height": 914, "uses_gas": True},
    },
    "runs": [
        {"wall": "N", "level": "base", "items": [
            filler(76, "N-filler-left"),
            cab("frame:base:15x24x30", "N-base-15", (f"{V}:door:15x30", 1)),
            cab("frame:base:30x24x30", "N-base-30", (f"{V}:door:15x30", 2)),
            cab("frame:sink_base:36x24x30", "N-sink-36", (f"{V}:door:18x30", 2)),
            {"kind": "appliance", "label": "N-dishwasher", "ref": "dishwasher"},
            cab("frame:base:18x24x30", "N-base-18-drawers", (f"{V}:drawer:18x10", 1), (f"{V}:drawer:18x20", 1), interior=["MAXIMERA 18x24 medium", "MAXIMERA 18x24 high"]),
            cab("frame:base:15x24x30", "N-base-15-drawers", (f"{V}:drawer:15x5", 1), (f"{V}:drawer:15x10", 1), (f"{V}:drawer:15x15", 1)),
            filler(74, "N-filler-right"),
        ]},
        {"wall": "N", "level": "wall", "to": 1219, "items": [
            filler(76, "N-wall-filler-left"),
            cab("frame:wall:15x12x30", "N-wall-15", (f"{V}:door:15x30", 1)),
            cab("frame:wall:30x12x30", "N-wall-30", (f"{V}:door:15x30", 2)),
        ]},
        {"wall": "N", "level": "wall", "from": 2133, "items": [
            cab("frame:wall:36x12x30", "N-wall-36", (f"{V}:door:18x30", 2)),
            cab("frame:wall:21x12x30", "N-wall-21", (f"{V}:door:21x30", 1)),
            filler(75, "N-wall-filler-right"),
        ]},
        {"wall": "E", "level": "base", "from": 610, "items": [
            cab("frame:base:21x24x30", "E-base-21-drawers", (f"{V}:drawer:21x10", 1), (f"{V}:drawer:21x20", 1)),
            {"kind": "appliance", "label": "E-range", "ref": "range"},
            cab("frame:base:30x24x30", "E-base-30", (f"{V}:door:15x30", 2)),
            filler(74, "E-filler-right"),
        ]},
        {"wall": "E", "level": "wall", "from": 610, "items": [
            cab("frame:wall:21x12x30", "E-wall-21", (f"{V}:door:21x30", 1)),
            cab("frame:wall:30x12x20", "E-wall-30-hood", (f"{V}:door:30x20", 1), interior=["hood below"]),
            cab("frame:wall:30x12x30", "E-wall-30", (f"{V}:door:15x30", 2)),
            filler(74, "E-wall-filler-right"),
        ]},
    ],
}


def variant(name: str, note: str, mutate) -> dict:
    k = copy.deepcopy(FITS)
    k["name"] = f"Example L kitchen — BAD: {name}"
    k["notes"] = note
    k["room"] = "../room.example.json"
    mutate(k)
    return k


def n_base(k: dict) -> list[dict]:
    return k["runs"][0]["items"]


def run_too_long(k: dict) -> None:
    n_base(k)[1] = cab("frame:base:18x24x30", "N-base-18", (f"{V}:door:18x30", 1))  # 457 in place of 381


def dishwasher_against_wall(k: dict) -> None:
    items = n_base(k)
    dw = items.pop(4)
    items.pop()             # drop right filler
    items[0]["width"] = 150  # keep closure: 76 + 74 -> 150 on the left
    items.append(dw)         # dishwasher now touches the east wall end


def wall_cabinet_over_window(k: dict) -> None:
    run = k["runs"][1]
    run["to"] = 2133
    run["items"].append(cab("frame:wall:36x12x30", "N-wall-36-over-window", (f"{V}:door:18x30", 2)))


def wrong_size_front(k: dict) -> None:
    n_base(k)[5] = cab("frame:base:18x24x30", "N-base-18-drawers", (f"{V}:door:15x30", 1))


def missing_filler(k: dict) -> None:
    items = n_base(k)
    items.pop(0)  # drop the 76 mm left filler…
    items[0] = cab("frame:base:18x24x30", "N-base-18-at-wall", (f"{V}:door:18x30", 1))  # …and widen 15 -> 18 so the run still closes


def blocked_drain(k: dict) -> None:
    n_base(k)[3] = cab("frame:base:36x24x30", "N-base-36-not-a-sink", (f"{V}:door:18x30", 2))


BAD_CASES = {
    "run_too_long": ("the first base cabinet is 18 wide instead of 15; the run overshoots the wall by 76 mm", run_too_long),
    "dishwasher_against_wall": ("the dishwasher is the last item on the north wall with no filler; its door cannot clear the wall", dishwasher_against_wall),
    "wall_cabinet_over_window": ("a 36 wall cabinet hangs at 1372 mm across the window whose head is at 2032 mm", wall_cabinet_over_window),
    "wrong_size_front": ("a 15x30 door on an 18-wide frame", wrong_size_front),
    "missing_filler": ("the base run closes exactly but starts with a cabinet hard against the wall; IKEA wants 2 in of filler", missing_filler),
    "blocked_drain": ("the sink drain at 1676 mm falls inside a regular base cabinet, not a sink base", blocked_drain),
}


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    write(EX / "room.example.json", ROOM)
    write(EX / "kitchen.fits.json", FITS)
    for name, (note, fn) in BAD_CASES.items():
        write(BAD / f"{name}.json", variant(name, note, fn))
    print(f"wrote {EX / 'room.example.json'}, {EX / 'kitchen.fits.json'} and {len(BAD_CASES)} bad fixtures")
