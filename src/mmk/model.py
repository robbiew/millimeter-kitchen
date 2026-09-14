"""Phase 1: the kitchen layout, resolved against its room and catalog.

Resolution turns each run's item list into placed intervals along the wall so
that rules can reason in millimeters from the wall start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog, Item, load_catalog
from .io import FileError, load_validated, resolve_catalog_path
from .room import Room, load_room

DEFAULT_WALL_CABINET_BOTTOM = 1372  # 54"
DEFAULT_LEGS = 114                   # SEKTION legs, nominal 4 1/2"
DEFAULT_COUNTER_THICKNESS = 38       # 1 1/2"
DEFAULT_BACKSPLASH_HEIGHT = 457      # 18"


@dataclass(frozen=True)
class Appliance:
    ref: str
    name: str
    kind: str
    width: int
    depth: int
    height: int
    clearance_front: int | None
    clearance_to_wall: int | None
    uses_gas: bool
    needs_water: bool


@dataclass(frozen=True)
class FrontUse:
    item: Item
    count: int


@dataclass(frozen=True)
class Placed:
    """One item on a run, resolved to an interval along the wall."""

    index: int
    kind: str
    label: str
    start: int
    width: int
    catalog_item: Item | None = None
    appliance: Appliance | None = None
    fronts: tuple[FrontUse, ...] = ()
    unresolved: str | None = None  # why width could not be determined

    @property
    def end(self) -> int:
        return self.start + self.width

    def overlaps(self, a: int, b: int) -> bool:
        return self.start < b and a < self.end


@dataclass(frozen=True)
class Run:
    wall: str
    level: str
    start: int
    end: int
    bottom: int
    items: tuple[Placed, ...]

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def used(self) -> int:
        return sum(p.width for p in self.items)


@dataclass(frozen=True)
class Kitchen:
    name: str
    path: Path
    room: Room
    catalog: Catalog
    appliances: dict[str, Appliance]
    runs: tuple[Run, ...]
    legs: int
    counter_thickness: int
    wall_cabinet_bottom: int
    materials: dict[str, str] = field(default_factory=dict)  # role -> finish key, as written in the file
    backsplash_height: int = DEFAULT_BACKSPLASH_HEIGHT
    problems: list[str] = field(default_factory=list)  # resolution problems (unknown ids etc.)


def _appliances(data: dict) -> dict[str, Appliance]:
    out = {}
    for ref, a in data.get("appliances", {}).items():
        out[ref] = Appliance(
            ref=ref, name=a["name"], kind=a["kind"], width=a["width"], depth=a["depth"], height=a["height"],
            clearance_front=a.get("clearance_front"), clearance_to_wall=a.get("clearance_to_wall"),
            uses_gas=bool(a.get("uses_gas", False)), needs_water=bool(a.get("needs_water", False)),
        )
    return out


def _label(index: int, raw: dict) -> str:
    if raw.get("label"):
        return raw["label"]
    if raw["kind"] == "appliance":
        return f"{index}:{raw.get('ref', 'appliance')}"
    if raw.get("id"):
        return f"{index}:{raw['id']}"
    return f"{index}:{raw['kind']}"


def resolve(data: dict, path: Path, room: Room, catalog: Catalog) -> Kitchen:
    problems: list[str] = []
    appliances = _appliances(data)
    counter = data.get("counter", {})
    wall_bottom = int(data.get("wall_cabinet_bottom", DEFAULT_WALL_CABINET_BOTTOM))
    runs: list[Run] = []

    for r in data["runs"]:
        wall = room.wall(r["wall"])
        start = int(r.get("from", 0))
        end = int(r.get("to", wall.planning_length))
        bottom = int(r.get("bottom", wall_bottom)) if r["level"] == "wall" else 0
        placed: list[Placed] = []
        cursor = start
        for i, raw in enumerate(r["items"]):
            kind = raw["kind"]
            label = _label(i, raw)
            width = 0
            cat_item = None
            appl = None
            fronts: list[FrontUse] = []
            unresolved = None
            if kind == "cabinet":
                cat_item = catalog.get(raw.get("id", ""))
                if cat_item is None or cat_item.kind != "frame":
                    unresolved = f"unknown frame id '{raw.get('id')}'"
                    problems.append(f"{r['wall']}/{label}: {unresolved}")
                else:
                    width = cat_item.w
                for f in raw.get("fronts", []):
                    fi = catalog.get(f["id"])
                    if fi is None:
                        problems.append(f"{r['wall']}/{label}: unknown front id '{f['id']}'")
                        continue
                    fronts.append(FrontUse(fi, int(f.get("count", 1))))
            elif kind == "appliance":
                appl = appliances.get(raw.get("ref", ""))
                if appl is None:
                    unresolved = f"unknown appliance ref '{raw.get('ref')}'"
                    problems.append(f"{r['wall']}/{label}: {unresolved}")
                else:
                    width = appl.width
            elif kind in ("filler", "panel", "gap"):
                if "width" in raw:
                    width = int(raw["width"])
                elif raw.get("id") and catalog.get(raw["id"]):
                    width = catalog[raw["id"]].w
                    cat_item = catalog[raw["id"]]
                else:
                    unresolved = f"{kind} needs a width"
                    problems.append(f"{r['wall']}/{label}: {unresolved}")
                if raw.get("id") and cat_item is None:
                    cat_item = catalog.get(raw["id"])
            placed.append(Placed(i, kind, label, cursor, width, cat_item, appl, tuple(fronts), unresolved))
            cursor += width
        runs.append(Run(r["wall"], r["level"], start, end, bottom, tuple(placed)))

    return Kitchen(
        name=data["name"], path=path, room=room, catalog=catalog, appliances=appliances, runs=tuple(runs),
        legs=int(counter.get("legs", DEFAULT_LEGS)),
        counter_thickness=int(counter.get("thickness", DEFAULT_COUNTER_THICKNESS)),
        wall_cabinet_bottom=wall_bottom, materials=dict(data.get("materials", {})),
        backsplash_height=int(data.get("backsplash_height", DEFAULT_BACKSPLASH_HEIGHT)), problems=problems,
    )


def load_kitchen(path: str | Path) -> Kitchen:
    loaded = load_validated(path, "kitchen")
    data = loaded.data
    room_path = loaded.path.parent / data["room"]
    if not room_path.exists():
        raise FileError(f"{loaded.path.name}: room file '{data['room']}' not found")
    room = load_room(room_path)
    catalog = load_catalog(resolve_catalog_path(data["catalog"], loaded.path))
    return resolve(data, loaded.path, room, catalog)


def wall_frames(room: Room) -> dict[str, tuple[float, float, float, float]]:
    """Plan-space origin (x, y) and unit heading (hx, hy) of each wall, y down on paper.

    Walks the survey order and turns 90° clockwise at each corner, so the room is
    always to the right of travel. Elevations, the plan and the 3D scene all use
    this so a cabinet lands in the same place in every output.
    """
    frames: dict[str, tuple[float, float, float, float]] = {}
    x, y = 0.0, 0.0
    hx, hy = 1.0, 0.0
    for wid in room.order:
        frames[wid] = (x, y, hx, hy)
        L = room.walls[wid].planning_length
        x, y = x + hx * L, y + hy * L
        hx, hy = -hy, hx
    return frames
