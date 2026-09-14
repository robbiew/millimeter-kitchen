"""Phase 0: the room survey and its consistency checks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from .findings import Finding
from .io import load_validated

LENGTH_TOLERANCE_MM = 6
SQUARE_WARNING_MM = 25
CEILING_SPREAD_WARNING_MM = 12


@dataclass(frozen=True)
class Opening:
    kind: str
    start: int
    width: int
    head: int
    sill: int | None
    label: str | None

    @property
    def end(self) -> int:
        return self.start + self.width


@dataclass(frozen=True)
class Service:
    kind: str
    at: int
    height: int | None
    label: str | None


@dataclass(frozen=True)
class Obstruction:
    kind: str
    start: int
    end: int
    bottom: int | None
    depth: int | None
    label: str | None


@dataclass(frozen=True)
class Wall:
    id: str
    lengths: dict[str, int]
    plumb_dev: int
    openings: tuple[Opening, ...]
    services: tuple[Service, ...]
    obstructions: tuple[Obstruction, ...]

    @property
    def planning_length(self) -> int:
        """The tightest of the three readings. Cabinets must fit the narrowest point."""
        return min(self.lengths.values())


@dataclass(frozen=True)
class Corner:
    walls: tuple[str, str]
    diagonal: int


@dataclass(frozen=True)
class Room:
    name: str
    walls: dict[str, Wall]
    corners: tuple[Corner, ...]
    ceiling: dict[str, int]
    order: tuple[str, ...] = field(default_factory=tuple)

    @property
    def min_ceiling(self) -> int:
        return min(self.ceiling.values())

    def wall(self, wall_id: str) -> Wall:
        try:
            return self.walls[wall_id]
        except KeyError as exc:
            raise KeyError(f"room has no wall '{wall_id}' (walls: {', '.join(self.order)})") from exc


def room_from_dict(data: dict) -> Room:
    walls: dict[str, Wall] = {}
    order: list[str] = []
    for w in data["walls"]:
        walls[w["id"]] = Wall(
            id=w["id"],
            lengths=dict(w["length"]),
            plumb_dev=int(w.get("plumb_dev", 0)),
            openings=tuple(
                Opening(o["kind"], o["from"], o["width"], o["head"], o.get("sill"), o.get("label"))
                for o in w.get("openings", [])
            ),
            services=tuple(Service(s["kind"], s["at"], s.get("height"), s.get("label")) for s in w.get("services", [])),
            obstructions=tuple(
                Obstruction(o["kind"], o["from"], o["to"], o.get("bottom"), o.get("depth"), o.get("label"))
                for o in w.get("obstructions", [])
            ),
        )
        order.append(w["id"])
    corners = tuple(Corner((c["walls"][0], c["walls"][1]), c["diagonal"]) for c in data["corners"])
    return Room(name=data["name"], walls=walls, corners=corners, ceiling=dict(data["ceiling"]), order=tuple(order))


def load_room(path: str | Path) -> Room:
    return room_from_dict(load_validated(path, "room").data)


def check_room(room: Room) -> list[Finding]:
    """Phase 0 acceptance checks. Errors mean the survey is not usable yet."""
    out: list[Finding] = []

    for wall in room.walls.values():
        spread = max(wall.lengths.values()) - min(wall.lengths.values())
        if spread > LENGTH_TOLERANCE_MM:
            out.append(Finding("error", "wall_length_spread", f"three readings differ by {spread} mm (limit {LENGTH_TOLERANCE_MM}); re-measure", wall.id))
        L = wall.planning_length
        for o in wall.openings:
            if o.end > L:
                out.append(Finding("error", "opening_outside_wall", f"{o.kind} {o.label or ''} ends at {o.end} mm on a {L} mm wall", wall.id))
            if o.sill is not None and o.sill >= o.head:
                out.append(Finding("error", "opening_geometry", f"{o.kind} {o.label or ''} sill {o.sill} is not below head {o.head}", wall.id))
        for s in wall.services:
            if s.at > L:
                out.append(Finding("error", "service_outside_wall", f"{s.kind} at {s.at} mm on a {L} mm wall", wall.id))
        for ob in wall.obstructions:
            if ob.end > L or ob.start >= ob.end:
                out.append(Finding("error", "obstruction_geometry", f"{ob.kind} {ob.start}–{ob.end} on a {L} mm wall", wall.id))

    # every adjacent pair in survey order needs a diagonal
    ids = list(room.order)
    pairs = {frozenset(c.walls) for c in room.corners}
    for a, b in zip(ids, ids[1:] + ids[:1]):
        if len(ids) < 2 or (len(ids) == 2 and a == ids[1]):
            break
        if frozenset((a, b)) not in pairs:
            out.append(Finding("error", "corner_missing_diagonal", f"no diagonal recorded for corner {a}/{b}", a))

    for c in room.corners:
        a, b = c.walls
        if a not in room.walls or b not in room.walls:
            out.append(Finding("error", "corner_unknown_wall", f"corner references unknown wall in {c.walls}"))
            continue
        la = room.walls[a].lengths["counter"]
        lb = room.walls[b].lengths["counter"]
        expected = math.hypot(la, lb)
        # law of cosines: angle at the corner between the two walls
        cos_theta = (la * la + lb * lb - c.diagonal * c.diagonal) / (2 * la * lb)
        cos_theta = max(-1.0, min(1.0, cos_theta))
        theta = math.degrees(math.acos(cos_theta))
        dev_deg = theta - 90.0
        # mm out of square at the far end of the shorter wall
        out_of_square = abs(math.tan(math.radians(dev_deg))) * min(la, lb)
        extra = {"angle_deg": round(theta, 2), "expected_diagonal": round(expected), "out_of_square_mm": round(out_of_square)}
        if out_of_square > SQUARE_WARNING_MM:
            out.append(Finding("warning", "corner_out_of_square", f"corner {a}/{b} is {theta:.1f}°, {out_of_square:.0f} mm out at the far end of the shorter wall; fillers must absorb this", a, extra=extra))

    spread = max(room.ceiling.values()) - min(room.ceiling.values())
    if spread > CEILING_SPREAD_WARNING_MM:
        out.append(Finding("warning", "ceiling_spread", f"ceiling varies by {spread} mm; high cabinets are sized from {room.min_ceiling} mm"))

    return out
