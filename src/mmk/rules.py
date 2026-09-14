"""Phase 1 fit rules. Each rule is a pure function Kitchen -> list[Finding].

A rule has a known-good case in examples/kitchen.fits.json and a known-bad
fixture in examples/bad/. Add a fixture before adding a rule.
"""

from __future__ import annotations

from collections.abc import Callable

from .findings import Finding
from .model import Kitchen, Run

CLOSURE_TOLERANCE_MM = 3
MIN_WALL_FILLER_MM = 51  # IKEA's 2" guidance at a wall end
DEFAULT_DISHWASHER_WALL_CLEARANCE_MM = 51
HOOD_TO_COOKTOP_MIN_MM = 610  # 24" over electric, most gas manufacturers want 24–30"

Rule = Callable[[Kitchen], list[Finding]]


def rule_resolution(k: Kitchen) -> list[Finding]:
    """Anything the resolver could not identify is an error before geometry is even checked."""
    return [Finding("error", "unknown_item", p) for p in k.problems]


def rule_ikea_fronts_only(k: Kitchen) -> list[Finding]:
    out = []
    for run in k.runs:
        for p in run.items:
            for fu in p.fronts:
                if fu.item.brand != "IKEA":
                    out.append(Finding("error", "ikea_fronts_only", f"front {fu.item.id} is {fu.item.brand}; only IKEA fronts are in scope", run.wall, p.label))
                if not fu.item.is_front:
                    out.append(Finding("error", "front_fit", f"{fu.item.id} is a {fu.item.kind}, not a front", run.wall, p.label))
    return out


def rule_run_closure(k: Kitchen) -> list[Finding]:
    """The items on a run must exactly fill the run's span (default: the whole wall)."""
    out = []
    for run in k.runs:
        if any(p.unresolved for p in run.items):
            continue  # reported by rule_resolution; widths are meaningless here
        diff = run.used - run.length
        if diff > CLOSURE_TOLERANCE_MM:
            last = run.items[-1].label if run.items else None
            out.append(Finding("error", "run_closure", f"{run.level} run is {diff} mm too long for its {run.length} mm span (items total {run.used} mm)", run.wall, last, {"overshoot_mm": diff}))
        elif diff < -CLOSURE_TOLERANCE_MM:
            out.append(Finding("error", "run_closure", f"{run.level} run leaves a {-diff} mm gap in its {run.length} mm span; add or widen a filler", run.wall, None, {"gap_mm": -diff}))
    return out


def _touches_wall_start(run: Run) -> bool:
    return run.start == 0


def _touches_wall_end(k: Kitchen, run: Run) -> bool:
    return run.end >= k.room.wall(run.wall).planning_length


def rule_wall_filler_min(k: Kitchen) -> list[Finding]:
    """Where a run meets a room wall it must begin/end with a filler of at least 51 mm."""
    out = []
    for run in k.runs:
        if not run.items:
            continue
        ends = []
        if _touches_wall_start(run):
            ends.append(("start", run.items[0]))
        if _touches_wall_end(k, run):
            ends.append(("end", run.items[-1]))
        for which, p in ends:
            if p.kind == "gap":
                continue  # an explicit gap is a deliberate open end (e.g. a doorway)
            if p.kind != "filler" or p.width < MIN_WALL_FILLER_MM:
                what = f"{p.kind} '{p.label}'" if p.kind != "filler" else f"a {p.width} mm filler"
                out.append(Finding("error", "wall_filler_min", f"{run.level} run meets the wall at its {which} with {what}; IKEA wants a filler of at least {MIN_WALL_FILLER_MM} mm there", run.wall, p.label))
    return out


def rule_appliance_side_clearance(k: Kitchen) -> list[Finding]:
    """Appliances that need side clearance to a room wall (dishwasher doors) must not sit at a wall end."""
    out = []
    for run in k.runs:
        wall_len = k.room.wall(run.wall).planning_length
        for p in run.items:
            if p.kind != "appliance" or p.appliance is None:
                continue
            need = p.appliance.clearance_to_wall
            if need is None and p.appliance.kind == "dishwasher":
                need = DEFAULT_DISHWASHER_WALL_CLEARANCE_MM
            if not need:
                continue
            left = p.start
            right = wall_len - p.end
            if left < need or right < need:
                side = "left" if left < need else "right"
                have = left if side == "left" else right
                out.append(Finding("error", "appliance_side_clearance", f"{p.appliance.kind} '{p.appliance.name}' has {have} mm to the wall on its {side}; needs {need} mm for the door to clear", run.wall, p.label))
    return out


def rule_opening_conflict(k: Kitchen) -> list[Finding]:
    """Nothing may cover a window or door. Wall cabinets may sit above a window only if their bottom clears the head."""
    out = []
    for run in k.runs:
        wall = k.room.wall(run.wall)
        for p in run.items:
            if p.kind in ("gap",) or p.width == 0:
                continue
            for o in wall.openings:
                if not p.overlaps(o.start, o.end):
                    continue
                if run.level == "base":
                    if o.kind == "door" or (o.sill is not None and o.sill < k.legs + 762 + k.counter_thickness):
                        out.append(Finding("error", "opening_conflict", f"{p.kind} '{p.label}' ({p.start}–{p.end}) overlaps {o.kind} '{o.label or ''}' ({o.start}–{o.end}) whose sill is at {o.sill} mm", run.wall, p.label))
                elif run.level == "high":
                    out.append(Finding("error", "opening_conflict", f"high cabinet '{p.label}' ({p.start}–{p.end}) overlaps {o.kind} '{o.label or ''}' ({o.start}–{o.end})", run.wall, p.label))
                else:  # wall level
                    if run.bottom < o.head:
                        out.append(Finding("error", "opening_conflict", f"wall cabinet '{p.label}' ({p.start}–{p.end}) hangs to {run.bottom} mm over {o.kind} '{o.label or ''}' whose head is at {o.head} mm", run.wall, p.label))
    return out


def rule_service_conflict(k: Kitchen) -> list[Finding]:
    """A drain must land inside a sink base; a gas stub inside a gas appliance."""
    out = []
    for run in k.runs:
        if run.level != "base":
            continue
        wall = k.room.wall(run.wall)
        for s in wall.services:
            if s.kind not in ("sink_drain", "gas"):
                continue
            covering = [p for p in run.items if p.start <= s.at < p.end]
            if not covering:
                continue  # nothing over it; a later phase checks that the sink actually exists
            p = covering[0]
            ok = False
            if s.kind == "sink_drain":
                ok = (p.catalog_item is not None and p.catalog_item.type == "sink_base") or (p.appliance is not None and p.appliance.kind == "sink")
                want = "a sink base"
            else:
                ok = p.appliance is not None and p.appliance.uses_gas
                want = "a gas appliance"
            if not ok:
                out.append(Finding("error", "service_conflict", f"{s.kind} at {s.at} mm is behind {p.kind} '{p.label}' ({p.start}–{p.end}); it must be inside {want}", run.wall, p.label))
    return out


def rule_front_fit(k: Kitchen) -> list[Finding]:
    """Fronts must tile the frame face: doors side by side to the frame width at full height,
    drawer fronts stacked to the frame height at full width. Compared in nominal inches."""
    out = []
    for run in k.runs:
        for p in run.items:
            if p.kind != "cabinet" or p.catalog_item is None or not p.fronts:
                continue
            frame = p.catalog_item
            fw, fh = frame.nominal_in.get("w"), frame.nominal_in.get("h")
            if fw is None or fh is None:
                continue
            doors = [fu for fu in p.fronts if fu.item.kind == "front"]
            drawers = [fu for fu in p.fronts if fu.item.kind == "drawer_front"]
            for fu in doors + drawers:
                if fu.item.nominal_in.get("w") is None or fu.item.nominal_in.get("h") is None:
                    out.append(Finding("error", "front_fit", f"front {fu.item.id} has no nominal size", run.wall, p.label))
            if doors:
                bad = [fu for fu in doors if fu.item.nominal_in.get("h") != fh]
                for fu in bad:
                    out.append(Finding("error", "front_fit", f"door {fu.item.id} is {fu.item.nominal_in.get('h')}\" tall on a {fh}\" frame", run.wall, p.label))
                total_w = sum(fu.item.nominal_in.get("w", 0) * fu.count for fu in doors)
                if total_w != fw:
                    out.append(Finding("error", "front_fit", f"doors total {total_w}\" wide on a {fw}\" frame", run.wall, p.label))
            if drawers:
                bad = [fu for fu in drawers if fu.item.nominal_in.get("w") != fw]
                for fu in bad:
                    out.append(Finding("error", "front_fit", f"drawer front {fu.item.id} is {fu.item.nominal_in.get('w')}\" wide on a {fw}\" frame", run.wall, p.label))
                total_h = sum(fu.item.nominal_in.get("h", 0) * fu.count for fu in drawers)
                if total_h != fh:
                    out.append(Finding("error", "front_fit", f"drawer fronts stack to {total_h}\" on a {fh}\" frame", run.wall, p.label))
            if doors and drawers:
                # a door-and-drawer combo (e.g. 1 drawer over 2 doors) is common; not modeled in phase 1
                out.append(Finding("warning", "front_fit", "doors and drawer fronts on one frame are not checked together yet", run.wall, p.label))
    return out


def rule_ceiling(k: Kitchen) -> list[Finding]:
    out = []
    for run in k.runs:
        if run.level != "high":
            continue
        for p in run.items:
            if p.catalog_item and p.catalog_item.h:
                top = k.legs + p.catalog_item.h
                if top > k.room.min_ceiling:
                    out.append(Finding("error", "ceiling", f"high cabinet '{p.label}' reaches {top} mm on legs; ceiling is {k.room.min_ceiling} mm at its lowest", run.wall, p.label))
    return out


def rule_unverified_catalog(k: Kitchen) -> list[Finding]:
    """Purchasable only when every used entry was verified against its product page."""
    unverified: list[str] = []
    for run in k.runs:
        for p in run.items:
            for it in [p.catalog_item] + [fu.item for fu in p.fronts]:
                if it and not it.verified and it.id not in unverified:
                    unverified.append(it.id)
    if not unverified:
        return []
    shown = ", ".join(unverified[:4]) + (f", … ({len(unverified)} total)" if len(unverified) > 4 else "")
    return [Finding("warning", "unverified_dimensions", f"dimensions for {shown} come from a size guide, not the product page; run tools/scrape_sektion.py before buying", extra={"ids": unverified})]


RULES: tuple[Rule, ...] = (
    rule_resolution,
    rule_ikea_fronts_only,
    rule_run_closure,
    rule_wall_filler_min,
    rule_appliance_side_clearance,
    rule_opening_conflict,
    rule_service_conflict,
    rule_front_fit,
    rule_ceiling,
    rule_unverified_catalog,
)


def validate(k: Kitchen) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(k))
    return findings
