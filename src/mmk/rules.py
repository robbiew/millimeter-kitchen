"""Phase 1 fit rules. Each rule is a pure function Kitchen -> list[Finding].

A rule has a known-good case in examples/kitchen.fits.json and a known-bad
fixture in examples/bad/. Add a fixture before adding a rule.
"""

from __future__ import annotations

from collections.abc import Callable

from .findings import Finding
from .finishes import ROLES, load_finishes
from .draw import CORNER_TOL, corner_reach, front_rows, item_depth, next_wall, prev_wall, run_at_end, run_at_start
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
            if p.catalog_item and p.catalog_item.corner:
                continue  # a corner cabinet meets the corner, not a side wall
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
            if frame.corner:
                if drawers:
                    out.append(Finding("error", "front_fit", "a corner cabinet takes doors, not drawer fronts", run.wall, p.label))
                want_w = frame.corner["front_width_in"]
                total_w = sum(fu.item.nominal_in.get("w", 0) * fu.count for fu in doors)
                if doors and total_w != want_w:
                    out.append(Finding("error", "front_fit", f"corner doors total {total_w}\" on a frame that takes {want_w}\"", run.wall, p.label))
                for fu in doors:
                    if fu.item.nominal_in.get("h") != fh:
                        out.append(Finding("error", "front_fit", f"door {fu.item.id} is {fu.item.nominal_in.get('h')}\" tall on a {fh}\" frame", run.wall, p.label))
                    if frame.corner["notch_mm"] and fu.item.type != "corner_door":
                        out.append(Finding("error", "front_fit", f"{fu.item.id} is not a corner door set; an L-shaped corner cabinet takes a 2-piece corner door", run.wall, p.label))
                continue
            # rows top to bottom: each drawer front is a full-width row; consecutive same-height doors share a row
            rows = front_rows(p)
            for row in rows:
                width = sum(it.nominal_in.get("w", 0) for it in row["panels"])
                if width != fw:
                    what = "doors total" if row["kind"] == "doors" else f"drawer front {row['panels'][0].id} is"
                    out.append(Finding("error", "front_fit", f"{what} {width:g}\" wide on a {fw:g}\" frame", run.wall, p.label))
            stack = sum(row["height_in"] for row in rows)
            if stack != fh:
                desc = " + ".join(f"{row['height_in']:g}" for row in rows)
                out.append(Finding("error", "front_fit", f"fronts stack to {stack:g}\" ({desc}) on a {fh:g}\" frame", run.wall, p.label))
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


def rule_corners(k: Kitchen) -> list[Finding]:
    """Corner cabinets sit at the corner between consecutive walls; adjacent runs must not overlap in plan."""
    out = []
    order = list(k.room.order)
    for run in k.runs:
        L = k.room.wall(run.wall).planning_length
        for i, p in enumerate(run.items):
            if not (p.catalog_item and p.catalog_item.corner):
                continue
            at_end = i == len(run.items) - 1 and run.end >= L - CORNER_TOL
            at_start = i == 0 and run.start <= CORNER_TOL
            neighbour = next_wall(k, run.wall) if at_end else (prev_wall(k, run.wall) if at_start else None)
            if not (at_end or at_start):
                out.append(Finding("error", "corner_placement", f"corner cabinet '{p.label}' must be the first or last item of its run, touching the corner", run.wall, p.label))
            elif neighbour is None:
                out.append(Finding("error", "corner_placement", f"corner cabinet '{p.label}' sits at the {'end' if at_end else 'start'} of wall {run.wall}, but no wall meets it there in the survey order", run.wall, p.label))
    for a, b in zip(order, order[1:]):
        La = k.room.wall(a).planning_length
        for level in ("base", "wall", "high"):
            ra = run_at_end(k, a, level)
            rb = run_at_start(k, b, level)
            if ra is None or rb is None:
                continue
            ia, ib = ra.items[-1], rb.items[0]
            occ_a = corner_reach(ia, level)                      # along wall b, from the corner
            occ_b = corner_reach(ib, level) if rb.start <= CORNER_TOL else 0   # along wall a, from the corner
            corner_a = bool(ia.catalog_item and ia.catalog_item.corner)
            corner_b = bool(ib.catalog_item and ib.catalog_item.corner)
            if rb.start < occ_a - CORNER_TOL and ra.end > La - occ_b - CORNER_TOL:
                out.append(Finding("error", "corner_overlap", f"{level}: '{ia.label}' on wall {a} reaches {occ_a} mm along wall {b}, but '{ib.label}' starts at {rb.start} mm; move it to {occ_a} mm or beyond", b, ib.label))
            elif corner_a and rb.start > occ_a + CORNER_TOL:
                out.append(Finding("warning", "corner_gap", f"{level}: {rb.start - occ_a} mm of dead space between corner cabinet '{ia.label}' and '{ib.label}'", b, ib.label))
            elif corner_b and ra.end < La - occ_b - CORNER_TOL:
                out.append(Finding("warning", "corner_gap", f"{level}: {La - occ_b - ra.end} mm of dead space between '{ia.label}' and corner cabinet '{ib.label}'", a, ia.label))
            elif not corner_a and not corner_b and rb.start > occ_a + CORNER_TOL and ra.end >= La - CORNER_TOL:
                out.append(Finding("warning", "corner_gap", f"{level}: the corner between walls {a} and {b} is dead space ({rb.start - occ_a} mm past the {occ_a} mm the wall-{a} cabinets occupy); a corner cabinet would use it", b, ib.label))
    return out


def rule_unique_labels(k: Kitchen) -> list[Finding]:
    """Edits address items by label, so a label may appear once in the whole file."""
    seen: dict[str, str] = {}
    out = []
    for run in k.runs:
        for p in run.items:
            if p.label in seen:
                out.append(Finding("error", "duplicate_label", f"label '{p.label}' is used on wall {seen[p.label]} and wall {run.wall}; labels must be unique", run.wall, p.label))
            else:
                seen[p.label] = run.wall
    return out


def rule_finishes(k: Kitchen) -> list[Finding]:
    """Every finish named in the file must exist in the library and suit its role."""
    lib = load_finishes()
    out = []
    for role, key in k.materials.items():
        if role not in ROLES:
            out.append(Finding("error", "finish_unknown", f"'{role}' is not a material role (one of {', '.join(ROLES)})"))
        elif key not in lib:
            out.append(Finding("error", "finish_unknown", f"materials.{role} = '{key}' is not in {lib.id}; run `mmk finishes list --role {role}`"))
        elif lib[key].role != role:
            out.append(Finding("error", "finish_role", f"materials.{role} = '{key}' is a {lib[key].role} finish, not a {role} finish"))
    return out


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
    rule_corners,
    rule_unique_labels,
    rule_finishes,
    rule_unverified_catalog,
)


def validate(k: Kitchen) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(k))
    return findings
