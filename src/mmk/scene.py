"""Phase 3: the 3D scene as axis-aligned boxes in world millimeters.

World axes are glTF's: X right, Y up, Z toward the viewer. Plan x maps to X and
plan y (down the page) maps to Z, so the plan drawing and the scene agree.
Everything here is derived from the resolved Kitchen; nothing is authored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .draw import CORNER_TOL, FRONT_REVEAL_MM, counter_depth, counter_segments, elevation_boxes, front_panels, item_depth, run_depth
from .finishes import ROLES, Finish, FinishLibrary, load_finishes
from .model import Kitchen, Run, wall_frames

WALL_THICKNESS = 100
FLOOR_THICKNESS = 50
FRONT_THICKNESS = 19
TOE_KICK_SETBACK = 76
COUNTER_OVERHANG_DEFAULT = 38
GLASS_THICKNESS = 12
ROOM_DEPTH_FOR_FLOOR = 2600
CAMERA_HEIGHT = 1400
CAMERA_VFOV_DEG = 50.0
CAMERA_ASPECT = 1.6
CAMERA_MARGIN = 1.15  # framing slack on both axes

BACKSPLASH_THICKNESS = 8


def resolve_materials(k: Kitchen, lib: FinishLibrary) -> dict[str, Finish]:
    """Role -> Finish for this kitchen: the file's `materials` block over the library defaults."""
    out = {}
    for role in ROLES:
        key = k.materials.get(role, lib.defaults[role])
        out[role] = lib[key]
    return out


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
    materials: dict[str, Finish]  # material name used on boxes -> finish


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


def _front_material(p, lib: FinishLibrary, default: Finish) -> str:
    """A front's finish is its catalog series slug (front:<slug>:...) when the library has it."""
    for fu in p.fronts:
        slug = fu.item.id.split(":")[1] if fu.item.id.count(":") >= 2 else ""
        if slug in lib and lib[slug].role == "front":
            return slug
    return default.key


def _fronts(fr: _Frame, run: Run, b, face: float, mat: str) -> list[Box]:
    """Door and drawer panels in front of the frame face, from the same row layout as the elevation."""
    p = b.p
    return [fr.box(f"{p.label}/{panel['name']}", "front", mat, panel["x"], panel["x"] + panel["w"], face, face + FRONT_THICKNESS,
                   panel["y0"], panel["y0"] + panel["h"], front=panel["item"].id if panel["item"] else None)
            for panel in front_panels(b)]


def _corner_boxes(fr: _Frame, run: Run, b, k: Kitchen, mat_frame: str, mat_front: str, mat_kick: str) -> list[Box]:
    """A corner cabinet as boxes: one or two legs, door panels on the exposed faces, toe kicks under the legs."""
    p = b.p
    c = p.catalog_item.corner
    R, D, N = c["reach_mm"], c["side_depth_mm"], c["notch_mm"]
    L = k.room.wall(run.wall).planning_length
    at_end = b.x + b.w >= L - CORNER_TOL
    x0, x1 = b.x, b.x + b.w
    y0, y1 = b.y0, b.y0 + b.h
    r = FRONT_REVEAL_MM
    out = [fr.box(p.label, "cabinet", mat_frame, x0, x1, 0, D, y0, y1, id=p.catalog_item.id, level=run.level, corner=True)]
    if run.level == "base":
        out.append(fr.box(f"{p.label}/toe_kick", "toe_kick", mat_kick, x0, x1, TOE_KICK_SETBACK, D, 0, y0))
    front_id = p.fronts[0].item.id if p.fronts else None
    if N:
        # second leg along the adjacent wall, and a bi-fold door: one panel on each notch face
        leg = (x1 - D, x1) if at_end else (x0, x0 + D)
        out.append(fr.box(f"{p.label}/leg", "cabinet", mat_frame, leg[0], leg[1], D, R, y0, y1, corner=True))
        if run.level == "base":
            out.append(fr.box(f"{p.label}/leg/toe_kick", "toe_kick", mat_kick, leg[0], leg[1], D, R - TOE_KICK_SETBACK, 0, y0))
        face1 = (x0 + r, x0 + N - r) if at_end else (x1 - N + r, x1 - r)
        out.append(fr.box(f"{p.label}/door1", "front", mat_front, face1[0], face1[1], D, D + FRONT_THICKNESS, y0 + r, y1 - r, front=front_id))
        along2 = (x1 - D - FRONT_THICKNESS, x1 - D) if at_end else (x0 + D, x0 + D + FRONT_THICKNESS)
        out.append(fr.box(f"{p.label}/door2", "front", mat_front, along2[0], along2[1], D + r, R - r, y0 + r, y1 - r, front=front_id))
    else:
        fw = int(round(c["front_width_in"] * 25.4))
        zone = (x0 + r, x0 + fw - r) if at_end else (x1 - fw + r, x1 - r)
        out.append(fr.box(f"{p.label}/door1", "front", mat_front, zone[0], zone[1], D, D + FRONT_THICKNESS, y0 + r, y1 - r, front=front_id))
    return out


def build_scene(k: Kitchen, lib: FinishLibrary | None = None) -> Scene:
    lib = lib or load_finishes()
    mats = resolve_materials(k, lib)
    M = {role: f.key for role, f in mats.items()}  # role -> material name
    used: dict[str, Finish] = {f.key: f for f in mats.values()}
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
                boxes.append(fr.box(f"wall {wid} {cursor}-{o.start}", "wall", M["wall"], cursor, o.start, -WALL_THICKNESS, 0, 0, ceiling))
            sill = o.sill if o.sill is not None else 0
            if sill > 0:
                boxes.append(fr.box(f"wall {wid} under {o.label or o.kind}", "wall", M["wall"], o.start, o.end, -WALL_THICKNESS, 0, 0, sill))
            if o.head < ceiling:
                boxes.append(fr.box(f"wall {wid} over {o.label or o.kind}", "wall", M["wall"], o.start, o.end, -WALL_THICKNESS, 0, o.head, ceiling))
            if o.kind == "window":
                boxes.append(fr.box(f"window {wid} {o.label or ''}".strip(), "glass", M["glass"], o.start, o.end, -WALL_THICKNESS / 2 - GLASS_THICKNESS / 2, -WALL_THICKNESS / 2 + GLASS_THICKNESS / 2, sill, o.head))
            cursor = o.end
        if cursor < L:
            boxes.append(fr.box(f"wall {wid} {cursor}-{L}", "wall", M["wall"], cursor, L, -WALL_THICKNESS, 0, 0, ceiling))

    # floor: bounding box of the walls pushed ROOM_DEPTH_FOR_FLOOR into the room
    pts = []
    for wid, fr in frames.items():
        L = k.room.walls[wid].planning_length
        for a in (0, L):
            for i in (0, ROOM_DEPTH_FOR_FLOOR):
                pts.append(fr.point(a, i, 0))
    fx0, fx1 = min(p[0] for p in pts), max(p[0] for p in pts)
    fz0, fz1 = min(p[2] for p in pts), max(p[2] for p in pts)
    boxes.append(Box("floor", "floor", M["floor"], (fx0, -FLOOR_THICKNESS, fz0), (fx1, 0, fz1)))

    # cabinets, appliances, fillers, fronts, toe kicks, counters
    for run in k.runs:
        fr = frames[run.wall]
        for b in elevation_boxes(k, run):
            p = b.p
            if p.kind == "gap" or p.width == 0:
                continue
            d = item_depth(p, run.level)
            if p.kind == "cabinet" and p.catalog_item and p.catalog_item.corner:
                fmat = _front_material(p, lib, mats["front"])
                used[fmat] = lib[fmat]
                boxes.extend(_corner_boxes(fr, run, b, k, M["frame"], fmat, M["toe_kick"]))
            elif p.kind == "cabinet":
                boxes.append(fr.box(p.label, "cabinet", M["frame"], b.x, b.x + b.w, 0, d, b.y0, b.y0 + b.h,
                                    id=p.catalog_item.id if p.catalog_item else None, level=run.level))
                fmat = _front_material(p, lib, mats["front"])
                used[fmat] = lib[fmat]
                boxes.extend(_fronts(fr, run, b, d, fmat))
                if run.level == "base":
                    boxes.append(fr.box(f"{p.label}/toe_kick", "toe_kick", M["toe_kick"], b.x, b.x + b.w, TOE_KICK_SETBACK, d, 0, b.y0))
            elif p.kind == "appliance":
                boxes.append(fr.box(p.label, "appliance", M["appliance"], b.x, b.x + b.w, 0, d, b.y0, b.y0 + b.h, appliance=p.appliance.kind if p.appliance else None, level=run.level))
            elif p.kind in ("filler", "panel"):
                boxes.append(fr.box(p.label, "filler", M["frame"], b.x, b.x + b.w, TOE_KICK_SETBACK if run.level == "base" else 0, d + (FRONT_THICKNESS if p.kind == "filler" else 0), b.y0, b.y0 + b.h, level=run.level))
        if run.level == "base" and run.items:
            cab_heights = [b.h + b.y0 for b in elevation_boxes(k, run) if b.p.kind == "cabinet"]
            top = max(cab_heights) if cab_heights else k.legs + 762
            for a0, a1 in counter_segments(k, run):
                boxes.append(fr.box(f"counter {run.wall} {a0}-{a1}", "counter", M["counter"], a0, a1, 0, counter_depth(run) + COUNTER_OVERHANG_DEFAULT, top, top + k.counter_thickness, wall=run.wall))
            # backsplash: from the counter top up to the wall cabinets above, else backsplash_height
            wall_runs = [r for r in k.runs if r.wall == run.wall and r.level == "wall"]
            top_y = top + k.counter_thickness
            cursor = run.start
            spans: list[tuple[int, int, int]] = []
            for wr in sorted(wall_runs, key=lambda r: r.start):
                a0, a1 = max(wr.start, run.start), min(wr.end, run.end)
                if a0 >= a1:
                    continue
                if a0 > cursor:
                    spans.append((cursor, a0, top_y + k.backsplash_height))
                spans.append((a0, a1, wr.bottom))
                cursor = a1
            if cursor < run.end:
                spans.append((cursor, run.end, top_y + k.backsplash_height))
            for a0, a1, y1 in spans:
                if y1 > top_y:
                    boxes.append(fr.box(f"backsplash {run.wall} {a0}-{a1}", "backsplash", M["backsplash"], a0, a1, 0, BACKSPLASH_THICKNESS, top_y, y1, wall=run.wall))

    # cameras: one per wall that has runs, plus an overview from the open side of the room
    cams: list[Camera] = []
    for wid in k.room.order:
        if not any(r.wall == wid for r in k.runs):
            continue
        fr = frames[wid]
        L = k.room.walls[wid].planning_length
        top = max((b.y0 + b.h for r in k.runs if r.wall == wid for b in elevation_boxes(k, r)), default=k.legs + 762)
        target_y = top / 2
        half_v = math.tan(math.radians(CAMERA_VFOV_DEG / 2))
        half_h = half_v * CAMERA_ASPECT
        # distance that fits the wall width and the floor-to-top height, whichever needs more
        dist_w = (L / 2) * CAMERA_MARGIN / half_h
        dist_h = max(top - target_y, target_y + (CAMERA_HEIGHT - target_y)) * CAMERA_MARGIN / half_v
        dist = min(max(dist_w, dist_h, 1800), 6000)
        cams.append(Camera(f"wall-{wid}", fr.point(L / 2, dist, CAMERA_HEIGHT), fr.point(L / 2, 0, target_y)))
    cx, cz = (fx0 + fx1) / 2, (fz0 + fz1) / 2
    first = frames[k.room.order[0]]
    far = first.point(-600, ROOM_DEPTH_FOR_FLOOR + 800, 0)
    cams.append(Camera("overview", (far[0], 1900, far[2]), (cx, 900, cz)))

    return Scene(k.name, tuple(boxes), tuple(cams), used)
