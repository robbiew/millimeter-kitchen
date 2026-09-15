"""Generate the SEKTION seed catalog from published size tables.

Every entry it writes is `verified: false`: the dimensions are exact inch
conversions of the nominal sizes IKEA publishes for the US SEKTION system,
not values read from product pages. `tools/scrape_sektion.py` upgrades
entries to verified once the product page has been fetched.

Only two article numbers were known at seed time; the rest are null.

Run:  python tools/build_catalog_seed.py catalog/sektion-us-2026-09.json   (keeps verified entries)
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
    "frame:base:30x24x30": "302.653.86",   # from ikea.com's search API, 2026-09-14; verify with tools/scrape_sektion.py
    "frame:base:24x24x30": "902.653.88",
    "frame:base:18x24x30": "202.653.96",
}

FRONT_SERIES = [
    # id slug, series, finish
    ("enkoping-walnut", "ENKÖPING", "brown walnut effect"),   # VOXTORP walnut effect left the US range; ENKÖPING is the walnut front now
    ("bodbyn-off-white", "BODBYN", "off-white"),
    ("axstad-matt-white", "AXSTAD", "matt white"),
]

BASE_WIDTHS = [12, 15, 18, 21, 24, 30, 36]
WALL_WIDTHS = [12, 15, 18, 21, 24, 30, 36]
WALL_HEIGHTS = [15, 20, 30, 40]
# Door sizes per width, from the 2026-09 sweep of ikea.com (ENKÖPING; BODBYN and AXSTAD offer the same).
# No 80" doors exist: high cabinets take 30+50, 20+60 or 40+50.
DOOR_SIZES = {12: [30, 40], 15: [15, 20, 30, 40, 50, 60], 18: [15, 20, 30, 40, 50, 60], 21: [30, 40], 24: [20, 30, 40, 50, 60]}
# No 30" or 36" wide door exists (families 05166-05169 swept 2026-09): a 30x15 wall cabinet takes two 15x15 doors.
DRAWER_FRONT_WIDTHS = [15, 18, 24, 30, 36]   # no 21" drawer front or MAXIMERA drawer is made
DRAWER_FRONT_HEIGHTS = [5, 10, 15, 20]      # no 20" drawer front is made: that entry is the 20" door article, hung on a high drawer


def frame(kind_type: str, w: float, d: float, h: float, nominal: str | None = None, notes: str | None = None) -> dict:
    nominal = nominal or f"{w:g}x{d:g}x{h:g}"
    id_ = f"frame:{kind_type}:{w:g}x{round(d):g}x{h:g}"
    return {
        "id": id_,
        "kind": "frame",
        "type": kind_type,
        "brand": "IKEA",
        "series": "SEKTION",
        "name": f"SEKTION {'top' if kind_type == 'wall_fridge' else kind_type.replace('_', ' ')} cabinet frame {nominal}",
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
        "actual": {"w": inch_to_mm(w - FRONT_REVEAL_IN), "h": inch_to_mm(h)},   # ikea.com: 14 7/8" x 30" for a 15x30 door
        **({"notes": "IKEA sells no 20\" drawer front; this is the 20\" door article hung on a high drawer."} if kind == "drawer_front" and h == 20 else {}),
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
            if w in (12, 21) and h in (15, 20):
                continue   # not made: the 2026-09 sweep of ikea.com found no 12" or 21" frame at 15" or 20" high
            items.append(frame("wall", w, 14.75, h, nominal=f"{w:g}x14 3/4x{h:g}"))   # SEKTION wall frames are 15" nominal, 14 3/4" measured
    for w in (30, 36):   # ikea.com sells the 24"-deep "top cabinet with ventilation" only 30 and 36 wide
        for h in (15, 20):
            items.append(frame("wall_fridge", w, 24, h, notes="Deep top cabinet for over a refrigerator; IKEA calls it 'top cabinet with ventilation'."))
    for w in (24, 30):
        for h in (80, 90):
            items.append(frame("high", w, 24, h))

    # corner cabinets. Sizes from published guides; verify per article before buying.
    def corner(kind_type: str, id_: str, nominal: str, w_in: float, d_in: float, h_in: float, reach_in: float, side_in: float, notch_in: float, blind: bool, front_w: float, name: str, notes: str) -> dict:
        # actual.w is the width along the cabinet's own wall; corner.reach_mm is what it occupies on the adjacent wall
        return {
            "id": id_, "kind": "frame", "type": kind_type, "brand": "IKEA", "series": "SEKTION", "name": name, "article": None,
            "nominal": nominal, "nominal_in": {"w": w_in, "d": d_in, "h": h_in},
            "actual": {"w": inch_to_mm(w_in), "d": inch_to_mm(side_in), "h": inch_to_mm(h_in)},
            "corner": {"reach_mm": inch_to_mm(reach_in), "side_depth_mm": inch_to_mm(side_in), "notch_mm": inch_to_mm(notch_in), "blind": blind, "front_width_in": front_w},
            "verified": False, "source": SOURCE, "notes": notes,
        }
    items.append(corner("base_corner", "frame:base_corner:38x38x30", "38x24x30", 38, 24, 30, 38, 24, 14, False, 13,
                        "SEKTION corner base cabinet frame 38x38x30 (carousel)",
                        "L-shaped: 38\" along each wall, 24\" deep legs, 14\" notch at the outer corner for the 2-piece bi-fold door set (13x30). Occupies 38\" of the adjacent wall too."))
    items.append(corner("base_corner", "frame:base_corner_blind:50x24x30", "50x24x30", 50, 24, 30, 24, 24, 0, True, 24,
                        "SEKTION corner base cabinet 50x24x30",
                        "Straight 50\" blind frame (ikea.com 2026-09: 'Corner base cabinet 50x24x30', 505.967.57; the old 47\" is gone); the part nearest the corner has no door and is covered by the adjacent wall's first cabinet. Takes a 24\" door on the outer end."))
    for h in (30, 40):
        items.append(corner("wall_corner", f"frame:wall_corner:26x26x{h}", f"26x14 3/4x{h}", 26, 14.75, h, 26, 14.75, 11, False, 13,
                            f"SEKTION corner wall cabinet frame 26x26x{h}",
                            "L-shaped: 26\" along each wall, 15\" deep legs, 11\" notch for a 2-piece door (13\" set)."))

    for slug, series, finish in FRONT_SERIES:
        for w, heights in DOOR_SIZES.items():
            for h in heights:
                items.append(front("front", slug, series, finish, w, h))
        w, h = 13, 30   # ikea.com sells one corner set per series: "2-p door/corner base cabinet set 13x30", two 13" leaves
        items.append({
            "id": f"front:{slug}:corner-door:{w}x{h}", "kind": "front", "type": "corner_door", "brand": "IKEA", "series": series, "finish": finish,
            "name": f"{series} 2-piece door for corner base cabinet {w}x{h} {finish}", "article": None,
            "nominal": f"{w}x{h}", "nominal_in": {"w": w, "h": h},
            "actual": {"w": inch_to_mm(w - FRONT_REVEAL_IN), "h": inch_to_mm(h)},
            "verified": False, "source": SOURCE, "notes": "Two-piece bi-fold set for the 38\" corner base cabinet; also the only set for the 30\" corner wall cabinet. Each leaf is 13\" wide.",
        })
        for w in DRAWER_FRONT_WIDTHS:
            for h in DRAWER_FRONT_HEIGHTS:
                if h == 20 and 20 not in DOOR_SIZES.get(w, []):
                    continue   # the 20" "drawer front" is the 20" door, which comes 15, 18 and 24 wide
                items.append(front("drawer_front", slug, series, finish, w, h))

    # ---- hardware and accessories the purchase pack derives from the layout
    def hw(id_: str, kind: str, name: str, nominal: str | None, actual: dict, notes: str, **extra) -> dict:
        return {"id": id_, "kind": kind, "brand": "IKEA", "series": id_.split(":")[1].upper(), "name": name, "article": None,
                **({"nominal": nominal} if nominal else {}), "actual": actual, "verified": False, "source": SOURCE, "notes": notes, **extra}

    for w in DRAWER_FRONT_WIDTHS:
        for d in (24, 15):
            for h_name, front_h in (("low", 5), ("medium", 10), ("high", 15)):
                if d == 15 and h_name == "high":
                    continue   # not made at 14 3/4" depth
                items.append(hw(f"drawer:maximera:{w}x{d}:{h_name}", "drawer", f"MAXIMERA drawer, {h_name}, {w}x{d}", f"{w}x{d}",
                                {"w": inch_to_mm(w), "d": inch_to_mm(d), "h": inch_to_mm(front_h)},
                                f"One per drawer front: {front_h}\" fronts take a {h_name} drawer. Runners included.",
                                nominal_in={"w": w, "d": d}))
    # FÖRBÄTTRA panels and toe kicks come in each front finish; sizes are ikea.com's (wall panels overhang the frame)
    for slug, series, finish in FRONT_SERIES:
        for w, h, level in ((25, 30, "base"), (25, 80, "high"), (25, 90, "high"), (15, 31.125, "wall"), (15, 41.125, "wall"), (15, 90, "high")):
            size = f"{w:g}x{int(h)}"
            nominal = f"{w:g}x{'31 1/8' if h == 31.125 else '41 1/8' if h == 41.125 else f'{h:g}'}"
            items.append({**hw(f"cover_panel:forbattra:{slug}:{size}", "cover_panel", f"FÖRBÄTTRA cover panel {nominal} {finish}", nominal,
                                {"w": inch_to_mm(w), "h": inch_to_mm(h)}, f"Exposed {level} cabinet sides, and ripped into filler strips.",
                                nominal_in={"w": w, "h": h}), "finish": finish})
        items.append({**hw(f"toe_kick:forbattra:{slug}:84", "toe_kick", f"FÖRBÄTTRA toekick 84x4 1/2 {finish}", "84x4 1/2",
                            {"w": inch_to_mm(84), "h": inch_to_mm(4.5)}, "Stock length; count = base run length / 2134 mm, rounded up.",
                            stock_mm=inch_to_mm(84), nominal_in={"w": 84, "h": 4.5}),
                      "finish": finish})
    items.append(hw("rail:sektion:84", "rail", "SEKTION suspension rail 84", "84",
                    {"w": inch_to_mm(84)}, "Every base, wall and high run hangs on rail; count = run lengths / 2134 mm, rounded up per wall.", stock_mm=inch_to_mm(84), nominal_in={"w": 84}))
    items.append(hw("legs:sektion:4pack", "legs", "SEKTION leg for cabinet 4 1/2, 4 pack", "4 1/2",
                    {"w": 0, "h": inch_to_mm(4.5)}, "One pack per base or high cabinet. Counter height 36\" = 30\" frame + legs + 1 1/2\" top.", pack=4, nominal_in={"h": 4.5}))
    items.append(hw("hinge:utrusta:2pack", "hinge", "UTRUSTA hinge, 2 pack", None,
                    {"w": 0}, "One pack per door up to 40\" tall, two packs per taller door.", pack=2))
    return {
        "id": CATALOG_ID,
        "market": "us",
        "units": "mm",
        "generated": date(2026, 9, 14).isoformat(),
        "source": SOURCE,
        "items": items,
    }


def merge_verified(new: dict, existing_path: Path) -> int:
    """Carry article numbers and verification over from the existing catalog file; the seed never owns those."""
    if not existing_path.exists():
        return 0
    prev = {i["id"]: i for i in json.loads(existing_path.read_text())["items"]}
    n = 0
    for item in new["items"]:
        old = prev.get(item["id"])
        if old and (old.get("verified") or old.get("article")):
            for key in ("article", "verified", "verified_on", "source", "actual"):
                if key in old:
                    item[key] = old[key]
            n += 1
    return n


if __name__ == "__main__":
    catalog = build()
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
        kept = merge_verified(catalog, out)
        out.write_text(json.dumps(catalog, indent=2) + "\n")
        print(f"wrote {out} with {len(catalog['items'])} items, kept {kept} verified entries", file=sys.stderr)
    else:
        json.dump(catalog, sys.stdout, indent=2)
        sys.stdout.write("\n")
