"""Generate the SEKTION seed catalog from published size tables.

Every entry it writes is `verified: false`: the dimensions are exact inch
conversions of the nominal sizes IKEA publishes for the US SEKTION system,
not values read from product pages. `tools/scrape_sektion.py` upgrades
entries to verified once the product page has been fetched.

Only two article numbers were known at seed time; the rest are null.

Run:  python tools/build_catalog_seed.py > catalog/sektion-us-2026-09.json
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mmk.units import inch_to_mm  # noqa: E402

CATALOG_ID = "sektion-us-2026-09"
SOURCE = "Published SEKTION size guides (IKEA US category pages, dimensions.com, kitchen-installers.com), Sept 2026. Not product pages."
FRONT_REVEAL_IN = 0.125  # IKEA fronts measure 1/8" under nominal in each direction

KNOWN_ARTICLES = {
    "frame:base:36x24x30": "802.653.98",
    "frame:base:15x15x30": "302.653.91",
}

FRONT_SERIES = [
    # id slug, series, finish
    ("voxtorp-walnut", "VOXTORP", "walnut effect"),
    ("bodbyn-off-white", "BODBYN", "off-white"),
    ("axstad-matt-white", "AXSTAD", "matt white"),
]

BASE_WIDTHS = [12, 15, 18, 21, 24, 30, 36]
WALL_WIDTHS = [12, 15, 18, 21, 24, 30, 36]
WALL_HEIGHTS = [15, 20, 30, 40]
DOOR_WIDTHS = [12, 15, 18, 21, 24]
DOOR_HEIGHTS = [15, 20, 30, 40, 80]
WIDE_DOOR_WIDTHS = [30, 36]          # horizontal doors for short wall cabinets
WIDE_DOOR_HEIGHTS = [15, 20]
DRAWER_FRONT_WIDTHS = [15, 18, 21, 24, 30, 36]
DRAWER_FRONT_HEIGHTS = [5, 10, 15, 20]


def frame(kind_type: str, w: float, d: float, h: float, nominal: str | None = None, notes: str | None = None) -> dict:
    nominal = nominal or f"{w:g}x{d:g}x{h:g}"
    id_ = f"frame:{kind_type}:{w:g}x{round(d):g}x{h:g}"
    return {
        "id": id_,
        "kind": "frame",
        "type": kind_type,
        "brand": "IKEA",
        "series": "SEKTION",
        "name": f"SEKTION {kind_type.replace('_', ' ')} cabinet frame {nominal}",
        "article": KNOWN_ARTICLES.get(id_),
        "nominal": nominal,
        "nominal_in": {"w": w, "d": d, "h": h},
        "actual": {"w": inch_to_mm(w), "d": inch_to_mm(d), "h": inch_to_mm(h)},
        "verified": False,
        "source": SOURCE,
        **({"notes": notes} if notes else {}),
    }


def front(kind: str, slug: str, series: str, finish: str, w: float, h: float) -> dict:
    what = "door" if kind == "front" else "drawer front"
    return {
        "id": f"front:{slug}:{'door' if kind == 'front' else 'drawer'}:{w:g}x{h:g}",
        "kind": kind,
        "type": "door" if kind == "front" else "drawer",
        "brand": "IKEA",
        "series": series,
        "finish": finish,
        "name": f"{series} {what} {w:g}x{h:g} {finish}",
        "article": None,
        "nominal": f"{w:g}x{h:g}",
        "nominal_in": {"w": w, "h": h},
        "actual": {"w": inch_to_mm(w - FRONT_REVEAL_IN), "h": inch_to_mm(h - FRONT_REVEAL_IN)},
        "verified": False,
        "source": SOURCE,
        "notes": "Actual = nominal minus 1/8\" each way (reveal).",
    }


def build() -> dict:
    items: list[dict] = []
    for w in BASE_WIDTHS:
        items.append(frame("base", w, 24, 30))
    items.append(frame("base", 15, 14.75, 30, nominal="15x14 3/4x30", notes="Shallow base; depth is 14 3/4\" nominal."))
    for w in (30, 36):
        items.append(frame("sink_base", w, 24, 30))
    for w in WALL_WIDTHS:
        for h in WALL_HEIGHTS:
            items.append(frame("wall", w, 12, h))
    for w in (24, 30, 36):
        for h in (15, 20):
            items.append(frame("wall_fridge", w, 24, h, notes="Deep wall cabinet for over a refrigerator."))
    for w in (24, 30):
        for h in (80, 90):
            items.append(frame("high", w, 24, h))

    for slug, series, finish in FRONT_SERIES:
        for w in DOOR_WIDTHS:
            for h in DOOR_HEIGHTS:
                items.append(front("front", slug, series, finish, w, h))
        for w in WIDE_DOOR_WIDTHS:
            for h in WIDE_DOOR_HEIGHTS:
                items.append(front("front", slug, series, finish, w, h))
        for w in DRAWER_FRONT_WIDTHS:
            for h in DRAWER_FRONT_HEIGHTS:
                items.append(front("drawer_front", slug, series, finish, w, h))

    for h, level in ((30, "base"), (40, "wall"), (90, "high")):
        items.append({
            "id": f"filler:strip:10x{h}",
            "kind": "filler",
            "brand": "IKEA",
            "series": "SEKTION",
            "name": f"Filler strip stock 10x{h} ({level})",
            "article": None,
            "nominal": f"10x{h}",
            "nominal_in": {"w": 10, "h": h},
            "actual": {"w": inch_to_mm(10), "h": inch_to_mm(h)},
            "verified": False,
            "source": SOURCE,
            "notes": "Cut to width on site. In kitchen.json a filler item gives its cut width directly.",
        })
    items.append({
        "id": "legs:sektion:4pack",
        "kind": "legs",
        "brand": "IKEA",
        "series": "SEKTION",
        "name": "SEKTION legs, adjustable, 4 pack",
        "article": None,
        "actual": {"w": 0, "h": inch_to_mm(4.5)},
        "verified": False,
        "source": SOURCE,
        "notes": "Nominal 4 1/2\" with a few cm of adjustment. Counter height 36\" = 30\" frame + legs + 1 1/2\" top.",
    })
    return {
        "id": CATALOG_ID,
        "market": "us",
        "units": "mm",
        "generated": date(2026, 9, 14).isoformat(),
        "source": SOURCE,
        "items": items,
    }


if __name__ == "__main__":
    json.dump(build(), sys.stdout, indent=2)
    sys.stdout.write("\n")
