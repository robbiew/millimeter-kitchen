"""Phase 2: dimensioned elevations and a plan view, generated from kitchen.json.

Every coordinate in the SVG is a real millimeter: a 36" frame is drawn as a
rect 914 wide. The page size (`width`/`height` attributes) divides the viewBox
by the print scale, so a 1:20 print measured with a caliper reads the file's
numbers times 20. Nothing here is edited by hand; change the file and redraw.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from .catalog import Item
from .model import Kitchen, Placed, Run, wall_frames

DEFAULT_SCALE = 20
BASE_DEPTH_FALLBACK = 610
WALL_DEPTH_FALLBACK = 305
FRONT_REVEAL_MM = 3
MARGIN = 300          # around the drawing, real mm
TITLE_H = 260         # title block height
DIM_ROW = 140         # height of one dimension row
FONT = 42             # ~2.1 mm on a 1:20 print
SMALL = 34

SERVICE_GLYPH = {"sink_drain": "D", "water_supply": "W", "gas": "G", "outlet": "O", "switch": "S", "vent": "V", "electrical_240v": "E"}


class Svg:
    """Tiny SVG string builder. Coordinates are real millimeters."""

    def __init__(self, width_mm: float, height_mm: float, scale: int, title: str):
        self.w, self.h, self.scale = width_mm, height_mm, scale
        self.parts: list[str] = []
        self.title = title

    def rect(self, x: float, y: float, w: float, h: float, cls: str, **attrs: str) -> None:
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" class="{cls}"{extra}/>')

    def line(self, x1: float, y1: float, x2: float, y2: float, cls: str) -> None:
        self.parts.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" class="{cls}"/>')

    def text(self, x: float, y: float, s: str, cls: str = "t", anchor: str = "middle", rotate: float | None = None, **attrs: str) -> None:
        tr = f' transform="rotate({rotate:g} {x:g} {y:g})"' if rotate else ""
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.parts.append(f'<text x="{x:g}" y="{y:g}" class="{cls}" text-anchor="{anchor}"{tr}{extra}>{escape(s)}</text>')

    def circle(self, cx: float, cy: float, r: float, cls: str) -> None:
        self.parts.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{r:g}" class="{cls}"/>')

    def group(self, cls: str, **attrs: str) -> None:
        extra = "".join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        self.parts.append(f'<g class="{cls}"{extra}>')

    def end(self) -> None:
        self.parts.append("</g>")

    def render(self) -> str:
        pw, ph = self.w / self.scale, self.h / self.scale
        style = f"""
  .wall{{fill:none;stroke:#000;stroke-width:6}}
  .floor{{stroke:#000;stroke-width:8}}
  .cab{{fill:#fff;stroke:#000;stroke-width:4}}
  .front{{fill:none;stroke:#000;stroke-width:2}}
  .counter{{fill:#ddd;stroke:#000;stroke-width:3}}
  .appl{{fill:url(#hatch);stroke:#000;stroke-width:4}}
  .filler{{fill:url(#hatchf);stroke:#000;stroke-width:3}}
  .gap{{fill:none;stroke:#000;stroke-width:2;stroke-dasharray:24 12}}
  .open{{fill:#eef;stroke:#000;stroke-width:4}}
  .wallcab{{fill:none;stroke:#000;stroke-width:3;stroke-dasharray:30 15}}
  .dim{{stroke:#000;stroke-width:2}}
  .ext{{stroke:#666;stroke-width:1.5}}
  .svc{{fill:#fff;stroke:#000;stroke-width:3}}
  .t{{font-family:Helvetica,Arial,sans-serif;font-size:{FONT}px}}
  .s{{font-family:Helvetica,Arial,sans-serif;font-size:{SMALL}px}}
  .h{{font-family:Helvetica,Arial,sans-serif;font-size:{FONT * 1.6:g}px;font-weight:bold}}
  .m{{font-family:Menlo,Consolas,monospace;font-size:{SMALL}px}}
"""
        defs = (
            '<defs>'
            '<pattern id="hatch" width="60" height="60" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<line x1="0" y1="0" x2="0" y2="60" stroke="#999" stroke-width="3"/></pattern>'
            '<pattern id="hatchf" width="24" height="24" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<line x1="0" y1="0" x2="0" y2="24" stroke="#000" stroke-width="2"/></pattern>'
            '</defs>'
        )
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw:.3f}mm" height="{ph:.3f}mm" '
            f'viewBox="0 0 {self.w:g} {self.h:g}" data-scale="1:{self.scale}" data-units="mm">\n'
            f'<title>{escape(self.title)}</title>\n<style>{style}</style>\n{defs}\n'
            f'<rect x="0" y="0" width="{self.w:g}" height="{self.h:g}" fill="#fff"/>\n{body}\n</svg>\n'
        )


# ---------------------------------------------------------------- helpers

def short_id(item: Item | None) -> str:
    if item is None:
        return ""
    return item.id.split(":", 1)[1] if ":" in item.id else item.id


def item_depth(p: Placed, level: str) -> int:
    if p.appliance:
        return p.appliance.depth
    if p.catalog_item and p.catalog_item.d:
        return p.catalog_item.d
    return WALL_DEPTH_FALLBACK if level == "wall" else BASE_DEPTH_FALLBACK


def item_height(p: Placed, level: str) -> int:
    if p.appliance:
        return p.appliance.height
    if p.catalog_item and p.catalog_item.h:
        return p.catalog_item.h
    return 762 if level == "base" else 762


def run_depth(run: Run) -> int:
    return max((item_depth(p, run.level) for p in run.items), default=BASE_DEPTH_FALLBACK)


CORNER_TOL = 3


def prev_wall(k, wid: str) -> str | None:
    o = list(k.room.order)
    i = o.index(wid)
    return o[i - 1] if i > 0 else None


def next_wall(k, wid: str) -> str | None:
    o = list(k.room.order)
    i = o.index(wid)
    return o[i + 1] if i + 1 < len(o) else None


def run_at_end(k, wid: str, level: str) -> Run | None:
    """The run on this wall and level that touches the wall's far end (the corner with the next wall)."""
    L = k.room.wall(wid).planning_length
    cands = [r for r in k.runs if r.wall == wid and r.level == level and r.items]
    return max(cands, key=lambda r: r.end, default=None) if any(r.end >= L - CORNER_TOL for r in cands) else None


def run_at_start(k, wid: str, level: str) -> Run | None:
    """The run on this wall and level that comes first (its start faces the corner with the previous wall)."""
    cands = [r for r in k.runs if r.wall == wid and r.level == level and r.items]
    return min(cands, key=lambda r: r.start, default=None)


def corner_reach(p: Placed, level: str) -> int:
    """How far an item at a corner occupies the adjacent wall, measured from the corner along that wall."""
    if p.catalog_item and p.catalog_item.corner:
        return p.catalog_item.corner["reach_mm"]
    return item_depth(p, level)


CORNER_SLACK = 51  # a run may start this much past the required corner clearance and still be "in the corner"


def corner_clearances(k, a: str, b: str, level: str) -> dict:
    """Geometry of the corner between consecutive walls a and b at one level.

    theta: interior angle from the survey. depth_a: what the wall-a cabinets
    occupy along wall b at a square corner (their depth, or a corner cabinet's
    reach). min_start_b: where wall b's first cabinet may start so that its
    near side clears the wall-a cabinet's front. min_end_filler_a: the strip
    the last wall-a cabinet needs at the corner so its front corner clears
    wall b when the corner is acute. Both collapse to depth_a and 0 at 90°.
    """
    import math

    theta = k.room.corner_angle(a, b)
    ra = run_at_end(k, a, level)
    rb = run_at_start(k, b, level)
    out = {"theta": theta, "depth_a": 0, "depth_b": 0, "min_start_b": 0, "min_end_filler_a": 0, "corner_cabinet_a": False}
    if ra is None:
        return out
    ia = ra.items[-1]
    out["corner_cabinet_a"] = bool(ia.catalog_item and ia.catalog_item.corner)
    d_a = corner_reach(ia, level)
    d_b = item_depth(rb.items[0], level) if rb is not None and rb.items else 0
    out["depth_a"], out["depth_b"] = d_a, d_b
    t = math.radians(theta)
    if out["corner_cabinet_a"]:
        out["min_start_b"] = d_a  # an L-shaped cabinet is built square; an out-of-square corner is scribed, not shifted
    else:
        out["min_start_b"] = int(math.ceil((d_a + max(0.0, d_b * math.cos(t))) / math.sin(t)))
        out["min_end_filler_a"] = int(math.ceil(max(0.0, d_a / math.tan(t)))) if theta < 90 else 0
    return out


def occupancy_from_prev(k, run: Run) -> int:
    """Where this run may start at the earliest, given what the previous wall's cabinets occupy at this level; 0 if none touch the corner."""
    pw = prev_wall(k, run.wall)
    if pw is None:
        return 0
    return corner_clearances(k, pw, run.wall, run.level)["min_start_b"]


def corner_start(k, run: Run) -> tuple[bool, int]:
    """(True, required start) when this run starts in the corner the previous wall's cabinets occupy."""
    occ = occupancy_from_prev(k, run)
    return (occ > 0 and run.start <= occ + CORNER_SLACK, occ)


def counter_segments(k, run: Run) -> list[tuple[int, int]]:
    """Intervals along a base run that carry countertop: everything except appliances
    that reach counter height (a range, a tall fridge). A dishwasher stays under it."""
    top = k.legs + max((item_height(p, "base") for p in run.items if p.kind == "cabinet"), default=762)
    out: list[tuple[int, int]] = []
    a0 = run.start
    is_corner, _ = corner_start(k, run)
    if is_corner:
        # the previous wall's slab covers the corner to its own depth; this slab starts where that one ends
        pw = prev_wall(k, run.wall)
        prev_run = run_at_end(k, pw, "base") if pw else None
        if prev_run is not None:
            a0 = counter_depth(prev_run) + 38
    for p in run.items:
        if p.kind == "appliance" and p.appliance and p.appliance.height >= top:
            if p.start > a0:
                out.append((a0, p.start))
            a0 = p.end
    if run.end > a0:
        out.append((a0, run.end))
    return out


def counter_depth(run: Run) -> int:
    """Countertops follow the cabinet frames, not an appliance that happens to be deeper."""
    cabs = [item_depth(p, run.level) for p in run.items if p.kind == "cabinet"]
    return max(cabs) if cabs else run_depth(run)


def fillers(run: Run) -> list[int]:
    return [p.width for p in run.items if p.kind == "filler"]


@dataclass(frozen=True)
class Box:
    """A placed item's rectangle in elevation: x from wall start, y from floor (up)."""

    p: Placed
    x: int
    y0: int
    w: int
    h: int


def wall_run_top(run: Run) -> int:
    """The shared top line of a wall run: explicit, or the underside plus the tallest cabinet in it.
    SEKTION wall cabinets hang from a rail at their top, so tops align and shorter cabinets sit higher."""
    if run.top is not None:
        return run.top
    tallest = max((item_height(p, "wall") for p in run.items if p.kind == "cabinet"), default=762)
    return run.bottom + tallest


def elevation_boxes(k: Kitchen, run: Run) -> list[Box]:
    out = []
    top = wall_run_top(run) if run.level == "wall" else None
    for p in run.items:
        if run.level == "base":
            y0, h = (0, p.appliance.height) if p.appliance else (k.legs, item_height(p, "base"))
        elif run.level == "high":
            y0, h = k.legs, item_height(p, "high")
        else:
            h = item_height(p, "wall")
            y0 = p.bottom if p.bottom is not None else top - h
        out.append(Box(p, p.start, y0, p.width, h))
    return out


# ---------------------------------------------------------------- elevation

def elevation_svg(k: Kitchen, wall_id: str, scale: int = DEFAULT_SCALE) -> str:
    wall = k.room.wall(wall_id)
    L = wall.planning_length
    ceiling = k.room.min_ceiling
    runs = [r for r in k.runs if r.wall == wall_id]
    base_runs = [r for r in runs if r.level == "base"]
    n_dim_rows = 2 + (1 if any(r.level == "wall" for r in runs) else 0)

    W = L + 2 * MARGIN
    H = TITLE_H + MARGIN + ceiling + MARGIN // 2 + n_dim_rows * DIM_ROW + MARGIN
    svg = Svg(W, H, scale, f"{k.name} — elevation, wall {wall_id}")
    ox, oy = MARGIN, TITLE_H + MARGIN + ceiling  # floor line origin; y grows downward in SVG

    def X(x: float) -> float:
        return ox + x

    def Y(y_up: float) -> float:
        return oy - y_up

    # title block
    svg.text(MARGIN, 90, f"Wall {wall_id} — elevation", "h", anchor="start")
    svg.text(MARGIN, 150, f"{k.name}", "t", anchor="start")
    used = {r.level: r.used for r in runs}
    lines = [f"planning length {L} mm (floor {wall.lengths['floor']}, counter {wall.lengths['counter']}, high {wall.lengths['high']})",
             f"ceiling {ceiling} mm (lowest corner) · legs {k.legs} · counter {k.counter_thickness} · wall cabinets from {k.wall_cabinet_bottom} mm"]
    for r in runs:
        f = fillers(r)
        lines.append(f"{r.level} run {r.start}–{r.end}: {r.used} mm used of {r.length} · fillers {', '.join(str(x) + ' mm' for x in f) if f else 'none'}")
    if wall.services:
        lines.append("services: " + " · ".join(f"{SERVICE_GLYPH.get(sv.kind, '?')}={sv.kind} @ {sv.at}" + (f" h{sv.height}" if sv.height is not None else "") for sv in wall.services))
    for i, s in enumerate(lines):
        svg.text(MARGIN, 195 + i * (SMALL + 6), s, "m", anchor="start")
    svg.text(W - MARGIN, 90, f"scale 1:{scale} · units mm", "t", anchor="end")
    svg.text(W - MARGIN, 150, f"catalog {k.catalog.id}", "s", anchor="end")

    # room envelope
    svg.rect(X(0), Y(ceiling), L, ceiling, "wall")
    svg.line(X(-MARGIN // 3), Y(0), X(L + MARGIN // 3), Y(0), "floor")

    # openings and obstructions
    for o in wall.openings:
        sill = o.sill if o.sill is not None else 0
        svg.rect(X(o.start), Y(o.head), o.width, o.head - sill, "open")
        if o.kind == "window":
            svg.line(X(o.start), Y(o.head), X(o.end), Y(sill), "front")
            svg.line(X(o.start), Y(sill), X(o.end), Y(o.head), "front")
        svg.text(X(o.start + o.width / 2), Y(o.head) - 12, f"{o.kind} {o.label or ''} {o.width} w · sill {sill} · head {o.head}".strip(), "s")
    for ob in wall.obstructions:
        if ob.bottom is not None:
            svg.rect(X(ob.start), Y(ceiling), ob.end - ob.start, ceiling - ob.bottom, "appl")
            svg.text(X((ob.start + ob.end) / 2), Y(ob.bottom) - 12, f"{ob.kind} to {ob.bottom} mm", "s")

    # cabinets, appliances, fillers
    for run in runs:
        for b in elevation_boxes(k, run):
            p = b.p
            if p.kind == "gap":
                svg.rect(X(b.x), Y(b.y0 + b.h), b.w, b.h, "gap")
                continue
            cls = {"appliance": "appl", "filler": "filler", "panel": "filler"}.get(p.kind, "cab")
            svg.rect(X(b.x), Y(b.y0 + b.h), b.w, b.h, cls, data_label=p.label, data_kind=p.kind, data_level=run.level, data_width=str(b.w))
            cx, cy = X(b.x + b.w / 2), Y(b.y0 + b.h / 2)
            if p.kind == "cabinet" and p.catalog_item and p.catalog_item.corner:
                zone, at_end = corner_door_zone(k, run, b)
                c = p.catalog_item.corner
                rest = (b.x + zone, b.x + b.w) if at_end else (b.x, b.x + b.w - zone)
                svg.rect(X(rest[0]), Y(b.y0 + b.h), rest[1] - rest[0], b.h, "filler")
                svg.text(X((rest[0] + rest[1]) / 2), cy, "blind" if c["blind"] else "corner", "s", rotate=-90)
                door_box = Box(p, b.x if at_end else b.x + b.w - zone, b.y0, zone, b.h)
                _draw_fronts(svg, door_box, X, Y, pieces=1 if c["blind"] else 2)
                svg.text(cx, cy - 6, p.catalog_item.nominal or "", "t")
                svg.text(cx, cy + SMALL + 2, short_id(p.catalog_item), "s")
            elif p.kind == "cabinet" and p.catalog_item:
                _draw_fronts(svg, b, X, Y)
                svg.text(cx, cy - 6, p.catalog_item.nominal or "", "t")
                svg.text(cx, cy + SMALL + 2, short_id(p.catalog_item), "s")
            elif p.kind == "appliance" and p.appliance:
                svg.text(cx, cy - 6, p.appliance.kind, "t")
                svg.text(cx, cy + SMALL + 2, f"{p.appliance.width}×{p.appliance.depth}×{p.appliance.height}", "s")
            elif p.kind in ("filler", "panel"):
                svg.text(cx, cy, f"{p.kind[0].upper()} {b.w}", "s", rotate=-90)
        if run.level == "base" and run.items:
            # countertop slabs over the base run, cut around counter-height appliances
            top = k.legs + max(item_height(p, "base") for p in run.items if not p.appliance) if any(not p.appliance for p in run.items) else k.legs + 762
            for a0, a1 in counter_segments(k, run):
                svg.rect(X(a0), Y(top + k.counter_thickness), a1 - a0, k.counter_thickness, "counter")
            svg.text(X(run.end) + 20, Y(top + k.counter_thickness / 2) + SMALL / 3, f"{top + k.counter_thickness} mm", "s", anchor="start")

    # services: glyph at position and height; the legend in the title block carries the words
    counter_top = k.legs + 762 + k.counter_thickness
    for s in wall.services:
        y = s.height if s.height is not None else 60
        if y < counter_top:
            y = 60  # behind a base cabinet anyway; keep it out of the label zone
        svg.circle(X(s.at), Y(y), 38, "svc")
        svg.text(X(s.at), Y(y) + SMALL / 3, SERVICE_GLYPH.get(s.kind, "?"), "s")

    # dimension chains
    row = 0
    for level in ("base", "wall", "high"):
        lr = [r for r in runs if r.level == level]
        if not lr:
            continue
        y = oy + MARGIN // 2 + row * DIM_ROW + DIM_ROW * 0.6
        row += 1
        svg.text(X(-MARGIN // 3), y + SMALL / 3, level, "s", anchor="end")
        for run in lr:
            bounds = [p.start for p in run.items] + [run.end]
            svg.line(X(run.start), y, X(run.end), y, "dim")
            for bx in bounds:
                svg.line(X(bx), y - 40, X(bx), y + 40, "dim")
                svg.line(X(bx), Y(0), X(bx), y - 40, "ext")
            for p in run.items:
                svg.text(X(p.start + p.width / 2), y - 14, str(p.width), "s")
    # overall + cumulative row
    y = oy + MARGIN // 2 + row * DIM_ROW + DIM_ROW * 0.6
    svg.text(X(-MARGIN // 3), y + SMALL / 3, "from start", "s", anchor="end")
    svg.line(X(0), y, X(L), y, "dim")
    marks = sorted({0, L, *[p.start for r in base_runs for p in r.items], *[p.end for r in base_runs for p in r.items]})
    crowded = any(b - a < 220 for a, b in zip(marks, marks[1:]))
    for m in marks:
        svg.line(X(m), y - 40, X(m), y + 40, "dim")
        if crowded:
            svg.text(X(m) + SMALL / 3, y + 60, str(m), "s", anchor="end", rotate=-60)
        else:
            svg.text(X(m), y + 40 + SMALL, str(m), "s")
    svg.text(X(L / 2), y - 50, f"{L} mm overall", "t")

    # scale bar: 1000 mm
    sx, sy = X(0), H - MARGIN // 2
    svg.line(sx, sy, sx + 1000, sy, "floor")
    for i in range(0, 1001, 250):
        svg.line(sx + i, sy - 30, sx + i, sy + 30, "dim")
    svg.text(sx + 500, sy - 40, "1000 mm scale bar", "s")
    return svg.render()


def front_rows(p: Placed) -> list[dict]:
    """Fronts as horizontal rows, top to bottom, in the order the file lists them.

    Each drawer front is a full-width row of its own. Consecutive doors of the
    same nominal height form one row and sit side by side. A row is
    {"kind": "drawer"|"doors", "height_in", "panels": [item, ...]} with one
    entry per physical panel (count expanded).
    """
    rows: list[dict] = []
    for fu in p.fronts:
        h = fu.item.nominal_in.get("h", 0)
        for _ in range(fu.count):
            if fu.item.kind == "drawer_front":
                rows.append({"kind": "drawer", "height_in": h, "panels": [fu.item]})
            elif rows and rows[-1]["kind"] == "doors" and rows[-1]["height_in"] == h:
                rows[-1]["panels"].append(fu.item)
            else:
                rows.append({"kind": "doors", "height_in": h, "panels": [fu.item]})
    return rows


def front_panels(b: Box, pieces: int | None = None) -> list[dict]:
    """Panel rectangles for a frame face, in wall-local mm: x, w along the wall; y0, h up from the floor.

    Rows take their share of the frame height by nominal height; panels in a
    doors row share the width equally. `pieces` overrides the layout with one
    row of equal panels (used for corner cabinets' bi-fold doors).
    """
    r = FRONT_REVEAL_MM
    out: list[dict] = []
    if pieces:
        w = (b.w - r * (pieces + 1)) / pieces
        item = b.p.fronts[0].item if b.p.fronts else None
        for i in range(pieces):
            out.append({"name": f"door{i + 1}", "x": b.x + r + i * (w + r), "w": w, "y0": b.y0 + r, "h": b.h - 2 * r, "item": item})
        return out
    rows = front_rows(b.p)
    total_nom = sum(row["height_in"] for row in rows) or 1
    y_top = b.y0 + b.h - r
    n_door = n_drawer = 0
    for row in rows:
        h = (b.h - r) * row["height_in"] / total_nom - r
        n = len(row["panels"])
        w = (b.w - r * (n + 1)) / n
        for i, item in enumerate(row["panels"]):
            if row["kind"] == "drawer":
                n_drawer += 1
                name = f"drawer{n_drawer}"
            else:
                n_door += 1
                name = f"door{n_door}"
            out.append({"name": name, "x": b.x + r + i * (w + r), "w": w, "y0": y_top - h, "h": h, "item": item})
        y_top -= h + r
    return out


def corner_door_zone(k, run: Run, b: Box) -> tuple[int, int | bool]:
    """(width of the door zone along this wall, at_end) for a corner cabinet: the notch for an L-shaped
    corner, the nominal door width for a blind corner; at_end is True when the corner is at the run's far end."""
    c = b.p.catalog_item.corner
    zone = c["notch_mm"] if c["notch_mm"] else int(round(c["front_width_in"] * 25.4))
    L = k.room.wall(run.wall).planning_length
    at_end = b.x + b.w >= L - CORNER_TOL
    return zone, at_end


def _draw_fronts(svg: Svg, b: Box, X, Y, pieces: int | None = None) -> None:
    """Door and drawer panels as the row layout lays them out, reveal 3 mm."""
    for panel in front_panels(b, pieces):
        svg.rect(X(panel["x"]), Y(panel["y0"] + panel["h"]), panel["w"], panel["h"], "front")


# ---------------------------------------------------------------- plan

def plan_svg(k: Kitchen, scale: int = DEFAULT_SCALE) -> str:
    frames = wall_frames(k.room)
    # extent
    pts = []
    for wid, (x, y, hx, hy) in frames.items():
        L = k.room.walls[wid].planning_length
        nx, ny = -hy, hx  # into the room
        for d in (-260, 0, 900):
            pts += [(x + nx * d, y + ny * d), (x + hx * L + nx * d, y + hy * L + ny * d)]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    W = (maxx - minx) + 2 * MARGIN
    H = (maxy - miny) + 2 * MARGIN + TITLE_H
    svg = Svg(W, H, scale, f"{k.name} — plan")
    ox, oy = MARGIN - minx, TITLE_H + MARGIN - miny

    svg.text(MARGIN, 90, "Plan", "h", anchor="start")
    svg.text(MARGIN, 150, k.name, "t", anchor="start")
    svg.text(MARGIN, 200, "walls drawn from the survey in order, turning 90° at each corner; base cabinets solid, wall cabinets dashed, counter shaded", "s", anchor="start")
    svg.text(W - MARGIN, 90, f"scale 1:{scale} · units mm", "t", anchor="end")

    def P(wid: str, along: float, into: float) -> tuple[float, float]:
        x, y, hx, hy = frames[wid]
        nx, ny = -hy, hx
        return ox + x + hx * along + nx * into, oy + y + hy * along + ny * into

    def rect_along(wid: str, a0: float, a1: float, d0: float, d1: float, cls: str, **attrs: str) -> None:
        c = [P(wid, a0, d0), P(wid, a1, d0), P(wid, a1, d1), P(wid, a0, d1)]
        extra = "".join(f' {kk.replace("_", "-")}="{v}"' for kk, v in attrs.items())
        svg.parts.append(f'<polygon points="{" ".join(f"{x:g},{y:g}" for x, y in c)}" class="{cls}"{extra}/>')

    for wid in k.room.order:
        wall = k.room.walls[wid]
        L = wall.planning_length
        x0, y0 = P(wid, 0, 0)
        x1, y1 = P(wid, L, 0)
        svg.line(x0, y0, x1, y1, "floor")
        mx, my = P(wid, L / 2, -150)
        _, _, hx, hy = frames[wid]
        svg.text(mx, my + (SMALL / 3 if abs(hy) > abs(hx) else 0), f"wall {wid} · {L} mm", "t", rotate=-90 if abs(hy) > abs(hx) else None)
        for o in wall.openings:
            rect_along(wid, o.start, o.end, -40, 40, "open")
        for s in wall.services:
            cx, cy = P(wid, s.at, -70)
            svg.circle(cx, cy, 30, "svc")
            svg.text(cx, cy + SMALL / 3, SERVICE_GLYPH.get(s.kind, "?"), "s")

    for run in k.runs:
        if run.level == "base":
            d = run_depth(run)
            for a0, a1 in counter_segments(k, run):
                rect_along(run.wall, a0, a1, 0, counter_depth(run) + 38, "counter")
    for run in k.runs:
        cls = "wallcab" if run.level == "wall" else None
        for p in run.items:
            if p.kind == "gap":
                continue
            d = item_depth(p, run.level)
            c = cls or {"appliance": "appl", "filler": "filler", "panel": "filler"}.get(p.kind, "cab")
            if p.catalog_item and p.catalog_item.corner:
                cc = p.catalog_item.corner
                L = k.room.wall(run.wall).planning_length
                at_end = p.end >= L - CORNER_TOL
                R, D = cc["reach_mm"], cc["side_depth_mm"]
                rect_along(run.wall, p.start, p.end, 0, D, c, data_label=p.label, data_level=run.level, data_width=str(p.width), data_depth=str(D))
                if cc["notch_mm"]:
                    a0, a1 = (p.end - D, p.end) if at_end else (p.start, p.start + D)
                    rect_along(run.wall, a0, a1, D, R, c, data_label=f"{p.label}/leg", data_level=run.level)
                else:
                    blind = (p.end - (R - int(round(cc["front_width_in"] * 25.4))), p.end) if at_end else (p.start, p.start + R - int(round(cc["front_width_in"] * 25.4)))
                    rect_along(run.wall, blind[0], blind[1], 0, D, "filler")
                if run.level != "wall":
                    cx, cy = P(run.wall, p.start + p.width / 2, D / 2)
                    _, _, hx, hy = frames[run.wall]
                    svg.text(cx, cy + SMALL / 3, p.catalog_item.nominal or "", "s", rotate=(-90 if abs(hy) > abs(hx) else None))
                continue
            rect_along(run.wall, p.start, p.end, 0, d, c, data_label=p.label, data_level=run.level, data_width=str(p.width), data_depth=str(d))
            if run.level != "wall" and p.width >= 300:
                cx, cy = P(run.wall, p.start + p.width / 2, d / 2)
                _, _, hx, hy = frames[run.wall]
                ang = 0 if abs(hx) > abs(hy) else -90
                label = p.catalog_item.nominal if p.catalog_item and p.catalog_item.nominal else (p.appliance.kind if p.appliance else str(p.width))
                svg.text(cx, cy + SMALL / 3, label, "s", rotate=ang or None)

    sx, sy = MARGIN, H - MARGIN // 2
    svg.line(sx, sy, sx + 1000, sy, "floor")
    for i in range(0, 1001, 250):
        svg.line(sx + i, sy - 30, sx + i, sy + 30, "dim")
    svg.text(sx + 500, sy - 40, "1000 mm scale bar", "s")
    return svg.render()


# ---------------------------------------------------------------- driver

def write_drawings(k: Kitchen, out_dir: str | Path, scale: int = DEFAULT_SCALE) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for wid in k.room.order:
        if not any(r.wall == wid for r in k.runs):
            continue
        p = out / f"elevation-{wid}.svg"
        p.write_text(elevation_svg(k, wid, scale))
        written.append(p)
    p = out / "plan.svg"
    p.write_text(plan_svg(k, scale))
    written.append(p)
    return written
