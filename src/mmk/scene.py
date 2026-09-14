"""Phase 3: the 3D scene as axis-aligned boxes in world millimeters.

World axes are glTF's: X right, Y up, Z toward the viewer. Plan x maps to X and
plan y (down the page) maps to Z, so the plan drawing and the scene agree.
Everything here is derived from the resolved Kitchen; nothing is authored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .draw import FRONT_REVEAL_MM, elevation_boxes, item_depth, run_depth
from .model import Kitchen, Run, wall_frames

WALL_THICKNESS = 100
FLOOR_THICKNESS = 50
FRONT_THICKNESS = 19
TOE_KICK_SETBACK = 76
COUNTER_OVERHANG_DEFAULT = 38
GLASS_THICKNESS = 12
ROOM_DEPTH_FOR_FLOOR = 2600
CAMERA_HEIGHT = 1500
CAMERA_TARGET_HEIGHT = 1100
CAMERA_VFOV_DEG = 50.0
CAMERA_ASPECT = 1.6

# material name -> RGBA base color (phase 4 replaces these with real finishes)
MATERIALS: dict[str, tuple[float, float, float, float]] = {
    "frame": (0.93, 0.93, 0.92, 1),
    "front": (0.85, 0.83, 0.80, 1),
    "front:voxtorp-walnut": (0.42, 0.27, 0.17, 1),
    "front:bodbyn-off-white": (0.94, 0.92, 0.86, 1),
    "front:axstad-matt-white": (0.96, 0.96, 0.96, 1),
    "counter": (0.78, 0.78, 0.76, 1),
    "appliance": (0.66, 0.67, 0.69, 1),
    "filler": (0.90, 0.90, 0.89, 1),
    "toe_kick": (0.35, 0.35, 0.35, 1),
    "wall": (0.92, 0.91, 0.88, 1),
    "floor": (0.62, 0.50, 0.38, 1),
    "glass": (0.70, 0.85, 0.95, 0.35),
}


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in world millimeters."""

    name: str
    kind: str          # cabinet | front | appliance | filler | counter | toe_kick | wall | floor | glass
    material: str
    min: tuple[float, float, float]
    max: tuple[float, float, float]
    extras: dict = field(default_factory=dict)

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(b - a for a, b in zip(self.min, self.max))


@dataclass(frozen=True)
class Camera:
    name: str
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    vfov_deg: float = CAMERA_VFOV_DEG
    aspect: float = CAMERA_ASPECT


@dataclass(frozen=True)
class Scene:
    name: str
    boxes: tuple[Box, ...]
    cameras: tuple[Camera, ...]
    materials: dict[str, tuple[float, float, float, float]]


class _Frame:
    """Places wall-local (along, into, up) coordinates into world XYZ."""

    def __init__(self, px: float, py: float, hx: float, hy: float):
        self.o = (px, 0.0, py)
        self.h = (hx, 0.0, hy)
        self.n = (-hy, 0.0, hx)  # into the room

    def point(self, along: float, into: float, up: float) -> tuple[float, float, float]:
        return (
            self.o[0] + self.h[0] * along + self.n[0] * into,
            up,
            self.o[2] + self.h[2] * along + self.n[2] * into,
        )

    def box(self, name: str, kind: str, material: str, a0: float, a1: float, i0: float, i1: float, y0: float, y1: float, **extras) -> Box:
        corners = [self.point(a, i, y) for a in (a0, a1) for i in (i0, i1) for y in (y0, y1)]
        mn = tuple(min(c[k] for c in corners) for k in range(3))
        mx = tuple(max(c[k] for c in corners) for k in range(3))
        return Box(name, kind, material, mn, mx, dict(extras))


def _front_material(p) -> str:
    for fu in p.fronts:
        slug = fu.item.id.split(":")[1] if fu.item.id.count(":") >= 2 else ""
        key = f"front:{slug}"
        if key in MATERIALS:
            return key
    return "front"


def _fronts(fr: _Frame, run: Run, b, face: float) -> list[Box]:
    """Door and drawer panels in front of the frame face, same splits as the elevation."""
    p = b.p
    doors = [fu for fu in p.fronts if fu.item.kind == "front"]
    drawers = [fu for fu in p.fronts if fu.item.kind == "drawer_front"]
    r = FRONT_REVEAL_MM
    mat = _front_material(p)
    out = []
    if doors and not drawers:
        n = sum(fu.count for fu in doors)
        w = (b.w - r * (n + 1)) / n
        for i in range(n):
            x = b.x + r + i * (w + r)
            out.append(fr.box(f"{p.label}/door{i + 1}", "front", mat, x, x + w, face, face + FRONT_THICKNESS, b.y0 + r, b.y0 + b.h - r, front=doors[0].item.id))
    elif drawers and not doors:
        total_nom = sum(fu.item.nominal_in.get("h", 0) * fu.count for fu in drawers) or 1
        y_top = b.y0 + b.h - r
        i = 0
        for fu in drawers:
            for _ in range(fu.count):
                h = (b.h - r) * fu.item.nominal_in.get("h", 0) / total_nom - r
                i += 1
                out.append(fr.box(f"{p.label}/drawer{i}", "front", mat, b.x + r, b.x + b.w - r, face, face + FRONT_THICKNESS, y_top - h, y_top, front=fu.item.id))
                y_top -= h + r
    return out


def build_scene(k: Kitchen) -> Scene:
    frames = {wid: _Frame(*f) for wid, f in wall_frames(k.room).items()}
    boxes: list[Box] = []
    ceiling = k.room.min_ceiling

    # room: walls (split around openings), floor
    for wid in k.room.order:
        wall = k.room.walls[wid]
        fr = frames[wid]
        L = wall.planning_length
        cuts = sorted(wall.openings, key=lambda o: o.start)
        cursor = 0
        for o in cuts:
            if o.start > cursor:
                boxes.append(fr.box(f"wall {wid} {cursor}-{o.start}", "wall", "wall", cursor, o.start, -WALL_THICKNESS, 0, 0, ceiling))
            sill = o.sill if o.sill is not None else 0
            if sill > 0:
                boxes.append(fr.box(f"wall {wid} under {o.label or o.kind}", "wall", "wall", o.start, o.end, -WALL_THICKNESS, 0, 0, sill))
            if o.head < ceiling:
                boxes.append(fr.box(f"wall {wid} over {o.label or o.kind}", "wall", "wall", o.start, o.end, -WALL_THICKNESS, 0, o.head, ceiling))
            if o.kind == "window":
                boxes.append(fr.box(f"window {wid} {o.label or ''}".strip(), "glass", "glass", o.start, o.end, -WALL_THICKNESS / 2 - GLASS_THICKNESS / 2, -WALL_THICKNESS / 2 + GLASS_THICKNESS / 2, sill, o.head))
            cursor = o.end
        if cursor < L:
            boxes.append(fr.box(f"wall {wid} {cursor}-{L}", "wall", "wall", cursor, L, -WALL_THICKNESS, 0, 0, ceiling))

    # floor: bounding box of the walls pushed ROOM_DEPTH_FOR_FLOOR into the room
    pts = []
    for wid, fr in frames.items():
        L = k.room.walls[wid].planning_length
        for a in (0, L):
            for i in (0, ROOM_DEPTH_FOR_FLOOR):
                pts.append(fr.point(a, i, 0))
    fx0, fx1 = min(p[0] for p in pts), max(p[0] for p in pts)
    fz0, fz1 = min(p[2] for p in pts), max(p[2] for p in pts)
    boxes.append(Box("floor", "floor", "floor", (fx0, -FLOOR_THICKNESS, fz0), (fx1, 0, fz1)))

    # cabinets, appliances, fillers, fronts, toe kicks, counters
    for run in k.runs:
        fr = frames[run.wall]
        for b in elevation_boxes(k, run):
            p = b.p
            if p.kind == "gap" or p.width == 0:
                continue
            d = item_depth(p, run.level)
            if p.kind == "cabinet":
                boxes.append(fr.box(p.label, "cabinet", "frame", b.x, b.x + b.w, 0, d, b.y0, b.y0 + b.h,
                                    id=p.catalog_item.id if p.catalog_item else None, level=run.level))
                boxes.extend(_fronts(fr, run, b, d))
                if run.level == "base":
                    boxes.append(fr.box(f"{p.label}/toe_kick", "toe_kick", "toe_kick", b.x, b.x + b.w, TOE_KICK_SETBACK, d, 0, b.y0))
            elif p.kind == "appliance":
                boxes.append(fr.box(p.label, "appliance", "appliance", b.x, b.x + b.w, 0, d, b.y0, b.y0 + b.h, appliance=p.appliance.kind if p.appliance else None, level=run.level))
            elif p.kind in ("filler", "panel"):
                boxes.append(fr.box(p.label, "filler", "filler", b.x, b.x + b.w, TOE_KICK_SETBACK if run.level == "base" else 0, d + (FRONT_THICKNESS if p.kind == "filler" else 0), b.y0, b.y0 + b.h, level=run.level))
        if run.level == "base" and run.items:
            cab_heights = [b.h + b.y0 for b in elevation_boxes(k, run) if b.p.kind == "cabinet"]
            top = max(cab_heights) if cab_heights else k.legs + 762
            boxes.append(fr.box(f"counter {run.wall} {run.start}-{run.end}", "counter", "counter", run.start, run.end, 0, run_depth(run) + COUNTER_OVERHANG_DEFAULT, top, top + k.counter_thickness, wall=run.wall))

    # cameras: one per wall that has runs, plus an overview from the open side of the room
    cams: list[Camera] = []
    for wid in k.room.order:
        if not any(r.wall == wid for r in k.runs):
            continue
        fr = frames[wid]
        L = k.room.walls[wid].planning_length
        hfov = 2 * math.atan(math.tan(math.radians(CAMERA_VFOV_DEG / 2)) * CAMERA_ASPECT)
        dist = min(max((L / 2) / math.tan(hfov / 2) * 1.15, 1800), 5000)
        cams.append(Camera(f"wall-{wid}", fr.point(L / 2, dist, CAMERA_HEIGHT), fr.point(L / 2, 0, CAMERA_TARGET_HEIGHT)))
    cx, cz = (fx0 + fx1) / 2, (fz0 + fz1) / 2
    first = frames[k.room.order[0]]
    far = first.point(-600, ROOM_DEPTH_FOR_FLOOR + 800, 0)
    cams.append(Camera("overview", (far[0], 1900, far[2]), (cx, 900, cz)))

    return Scene(k.name, tuple(boxes), tuple(cams), dict(MATERIALS))
