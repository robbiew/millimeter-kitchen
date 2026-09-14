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


def elevation_boxes(k: Kitchen, run: Run) -> list[Box]:
    out = []
    for p in run.items:
        if run.level == "base":
            y0, h = (0, p.appliance.height) if p.appliance else (k.legs, item_height(p, "base"))
        elif run.level == "high":
            y0, h = k.legs, item_height(p, "high")
        else:
            y0, h = run.bottom, item_height(p, "wall")
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
            if p.kind == "cabinet" and p.catalog_item:
                _draw_fronts(svg, b, X, Y)
                svg.text(cx, cy - 6, p.catalog_item.nominal or "", "t")
                svg.text(cx, cy + SMALL + 2, short_id(p.catalog_item), "s")
            elif p.kind == "appliance" and p.appliance:
                svg.text(cx, cy - 6, p.appliance.kind, "t")
                svg.text(cx, cy + SMALL + 2, f"{p.appliance.width}×{p.appliance.depth}×{p.appliance.height}", "s")
            elif p.kind in ("filler", "panel"):
                svg.text(cx, cy, f"{p.kind[0].upper()} {b.w}", "s", rotate=-90)
        if run.level == "base" and run.items:
            # countertop slab over the base run
            top = k.legs + max(item_height(p, "base") for p in run.items if not p.appliance) if any(not p.appliance for p in run.items) else k.legs + 762
            svg.rect(X(run.start) - 0, Y(top + k.counter_thickness), run.length, k.counter_thickness, "counter")
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


def _draw_fronts(svg: Svg, b: Box, X, Y) -> None:
    """Split lines for doors (side by side) and drawer fronts (stacked), reveal 3 mm."""
    p = b.p
    doors = [fu for fu in p.fronts if fu.item.kind == "front"]
    drawers = [fu for fu in p.fronts if fu.item.kind == "drawer_front"]
    r = FRONT_REVEAL_MM
    if doors and not drawers:
        n = sum(fu.count for fu in doors)
        w = (b.w - r * (n + 1)) / n
        for i in range(n):
            x = b.x + r + i * (w + r)
            svg.rect(X(x), Y(b.y0 + b.h - r), w, b.h - 2 * r, "front")
    elif drawers and not doors:
        # stack from the top, each drawer front's nominal height scaled to the frame
        total_nom = sum(fu.item.nominal_in.get("h", 0) * fu.count for fu in drawers) or 1
        y_top = b.y0 + b.h - r
        for fu in drawers:
            for _ in range(fu.count):
                h = (b.h - r) * fu.item.nominal_in.get("h", 0) / total_nom - r
                svg.rect(X(b.x + r), Y(y_top), b.w - 2 * r, h, "front")
                y_top -= h + r


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
            rect_along(run.wall, run.start, run.end, 0, d + (k.counter_thickness and 38), "counter")
    for run in k.runs:
        cls = "wallcab" if run.level == "wall" else None
        for p in run.items:
            if p.kind == "gap":
                continue
            d = item_depth(p, run.level)
            c = cls or {"appliance": "appl", "filler": "filler", "panel": "filler"}.get(p.kind, "cab")
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
