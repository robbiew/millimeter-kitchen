"""Phase 1 fit rules. Each rule is a pure function Kitchen -> list[Finding].

A rule has a known-good case in examples/kitchen.fits.json and a known-bad
fixture in examples/bad/. Add a fixture before adding a rule.
"""

from __future__ import annotations

import math

from collections.abc import Callable

from .findings import Finding
from .finishes import ROLES, load_finishes
from .draw import CORNER_SLACK, CORNER_TOL, FRONT_THICKNESS, backsplash_spans, corner_clearances, corner_reach, elevation_boxes, exposed_sides, front_rows, item_depth, next_wall, prev_wall, run_at_end, run_at_start
from .model import Kitchen, Run

CLOSURE_TOLERANCE_MM = 3
MIN_WALL_FILLER_MM = 51  # IKEA's 2" guidance at a wall end
MIN_CUT_WIDTH_MM = 25    # narrowest strip a filler or panel can be cut and fixed to; a wall end still needs MIN_WALL_FILLER_MM
# Clearance a front needs beside an obstruction, from IKEA Canada "When do I need to use filler pieces when installing my
# IKEA kitchen": "Minimum filler for a cabinet with drawers beside a wall: 1"", "... with door beside a wall: 2" or more
# with larger handles", "... for a refrigerator door beside a wall: 4"". At an inside corner the obstruction is the other run.
MIN_CLEARANCE_DRAWER_MM = 25
MIN_CLEARANCE_DOOR_MM = 51
MIN_CLEARANCE_FRIDGE_MM = 102
FIXED_APPLIANCES = ("sink", "cooktop", "hood")   # nothing on them swings or pulls out sideways
DEFAULT_DISHWASHER_WALL_CLEARANCE_MM = 51
HOOD_CLEARANCE_ELECTRIC_MM = 610  # 24" between cooktop and whatever hangs above it
HOOD_CLEARANCE_GAS_MM = 762       # 30" for gas; the hood's own sheet may ask for more

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


def rule_run_overlap(k: Kitchen) -> list[Finding]:
    """Two runs on the same wall and level must not share any of their span (a wall may be split around a window, never doubled up)."""
    out = []
    by_key: dict[tuple[str, str], list] = {}
    for run in k.runs:
        by_key.setdefault((run.wall, run.level), []).append(run)
    for (wall, level), runs in by_key.items():
        runs = sorted(runs, key=lambda r: (r.start, r.end))
        for prev, run in zip(runs, runs[1:]):
            if run.start < prev.end:
                first = run.items[0].label if run.items else None
                out.append(Finding("error", "run_overlap", f"two {level} runs on wall {wall} overlap: {prev.start}-{prev.end} mm and {run.start}-{run.end} mm share {min(prev.end, run.end) - run.start} mm; split runs must not touch the same span", wall, first, {"overlap_mm": min(prev.end, run.end) - run.start}))
    return out


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


def rule_cut_width_min(k: Kitchen) -> list[Finding]:
    """Every filler and panel is a strip that gets cut: it needs at least MIN_CUT_WIDTH_MM. A gap is an open span and needs any width at all.

    A zero-width item satisfies run closure without changing a total, so this is the rule that catches an item a
    client sent with no width (issue #2). The minimum for a cut strip is a workshop assumption, not an IKEA figure.
    """
    out = []
    for run in k.runs:
        for p in run.items:
            if p.kind in ("filler", "panel") and p.width < MIN_CUT_WIDTH_MM:
                out.append(Finding("error", "cut_width_min", f"{p.kind} '{p.label}' is {p.width} mm wide; a strip narrower than {MIN_CUT_WIDTH_MM} mm cannot be cut and fixed, so widen it or drop it", run.wall, p.label, {"width_mm": p.width}))
            elif p.kind == "gap" and p.width < 1:
                out.append(Finding("error", "cut_width_min", f"gap '{p.label}' has no width; a gap is an open span, so give it its width or drop it", run.wall, p.label, {"width_mm": p.width}))
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
        bottoms = {b.p.label: b.y0 for b in elevation_boxes(k, run)}
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
                    bottom = bottoms.get(p.label, run.bottom)
                    if bottom < o.head:
                        out.append(Finding("error", "opening_conflict", f"wall cabinet '{p.label}' ({p.start}–{p.end}) hangs to {bottom} mm over {o.kind} '{o.label or ''}' whose head is at {o.head} mm", run.wall, p.label))
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


def rule_hood_clearance(k: Kitchen) -> list[Finding]:
    """Whatever hangs over a range or cooktop must clear it by 24 in, 30 in for gas."""
    out = []
    for base in k.runs:
        if base.level != "base":
            continue
        for p in base.items:
            if p.kind != "appliance" or not p.appliance or p.appliance.kind not in ("range", "cooktop"):
                continue
            need = HOOD_CLEARANCE_GAS_MM if p.appliance.uses_gas else HOOD_CLEARANCE_ELECTRIC_MM
            cook_top = p.appliance.height if p.appliance.kind == "range" else k.legs + 762 + k.counter_thickness
            for wr in k.runs:
                if wr.wall != base.wall or wr.level != "wall":
                    continue
                for b in elevation_boxes(k, wr):
                    if b.p.kind == "gap" or not b.p.overlaps(p.start, p.end):
                        continue
                    gap = b.y0 - cook_top
                    if gap < need:
                        out.append(Finding("error", "hood_clearance", f"'{b.p.label}' hangs {gap} mm above the {'gas ' if p.appliance.uses_gas else ''}{p.appliance.kind} '{p.label}'; {need} mm is required. Use a shorter cabinet there (its top stays aligned with the run) or raise the run", wr.wall, b.p.label))
    return out


def rule_ceiling(k: Kitchen) -> list[Finding]:
    out = []
    for run in k.runs:
        if run.level == "wall" and run.items:
            top = max(b.y0 + b.h for b in elevation_boxes(k, run))
            if top > k.room.min_ceiling:
                out.append(Finding("error", "ceiling", f"wall run on {run.wall} tops out at {top} mm; ceiling is {k.room.min_ceiling} mm at its lowest", run.wall, run.items[0].label))
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
            g = corner_clearances(k, a, b, level)
            theta = g["theta"]
            occ_b = corner_reach(ib, level) if rb.start <= CORNER_TOL else 0   # along wall a, from the corner
            corner_a = g["corner_cabinet_a"]
            corner_b = bool(ib.catalog_item and ib.catalog_item.corner)
            square = f" (corner is {theta:.1f}°)" if abs(theta - 90) > 0.5 else ""
            if rb.start < g["min_start_b"] - CORNER_TOL and ra.end > La - occ_b - CORNER_TOL:
                out.append(Finding("error", "corner_overlap", f"{level}: '{ia.label}' on wall {a} needs wall-{b} cabinets to start at {g['min_start_b']} mm{square}, but '{ib.label}' starts at {rb.start} mm; move it to {g['min_start_b']} mm or beyond", b, ib.label))
            elif corner_a and rb.start > g["min_start_b"] + CORNER_TOL:
                out.append(Finding("warning", "corner_gap", f"{level}: {rb.start - g['min_start_b']} mm of dead space between corner cabinet '{ia.label}' and '{ib.label}'", b, ib.label))
            elif corner_b and ra.end < La - occ_b - CORNER_TOL:
                out.append(Finding("warning", "corner_gap", f"{level}: {La - occ_b - ra.end} mm of dead space between '{ia.label}' and corner cabinet '{ib.label}'", a, ia.label))
            elif not corner_a and not corner_b and rb.start > g["min_start_b"] + CORNER_SLACK and ra.end >= La - CORNER_TOL:
                out.append(Finding("warning", "corner_gap", f"{level}: the corner between walls {a} and {b} is dead space ({rb.start - g['min_start_b']} mm past the {g['min_start_b']} mm the wall-{a} cabinets need); a corner cabinet would use it", b, ib.label))
            # an acute corner pushes the last wall-a cabinet's front corner into wall b: it needs a filler at least this wide
            if g["min_end_filler_a"] > CORNER_TOL and ra.end >= La - CORNER_TOL:
                have = ia.width if ia.kind in ("filler", "gap", "panel") else 0   # a dead corner's gap keeps the cabinet's front corner clear too
                if have < g["min_end_filler_a"]:
                    out.append(Finding("error", "corner_filler", f"{level}: the corner between walls {a} and {b} is {theta:.1f}°, so the last cabinet on wall {a} needs a filler of at least {g['min_end_filler_a']} mm at the corner (its front corner would hit wall {b}); '{ia.label}' gives {have} mm", a, ia.label))
            if (corner_a or corner_b) and abs(theta - 90) > 1.0:
                out.append(Finding("warning", "corner_out_of_square", f"{level}: corner cabinet at a {theta:.1f}° corner; plan a scribe strip, the frame is square", a if corner_a else b, ia.label if corner_a else ib.label))
    return out


def _front_clearance(p) -> int:
    """IKEA's beside-an-obstruction minimum for this item's fronts; 0 for an item with nothing that opens."""
    if p.kind == "appliance":
        if p.appliance is None or p.appliance.kind in FIXED_APPLIANCES:
            return 0
        return MIN_CLEARANCE_FRIDGE_MM if p.appliance.kind in ("fridge", "refrigerator") else MIN_CLEARANCE_DOOR_MM
    if p.kind != "cabinet" or not p.fronts:
        return 0
    return MIN_CLEARANCE_DOOR_MM if any(fu.item.kind == "front" for fu in p.fronts) else MIN_CLEARANCE_DRAWER_MM


def _opening_reach(p, level: str) -> int:
    """How far an item's fronts travel in front of the run when opened: a drawer pulls out by the item's depth, an
    appliance by its depth or the front clearance its sheet declares, whichever is more; a door swings out by its
    panel width (the widest row of doors, panels sharing a row equally)."""
    if p.kind == "appliance":
        return max(item_depth(p, level), (p.appliance.clearance_front or 0) if p.appliance else 0)
    if any(fu.item.kind == "drawer_front" for fu in p.fronts):
        return item_depth(p, level)
    widest = 0
    for row in front_rows(p):
        widest = max(widest, p.width // max(1, len(row["panels"])))
    return widest


def rule_corner_swing(k: Kitchen) -> list[Finding]:
    """At an inside corner with no corner cabinet, fronts on both runs must clear each other (issue #6).

    Run b's first front stands facing run a's front plane (a's depth plus the front thickness) and needs IKEA's
    beside-an-obstruction clearance from it. Run a's fronts that lie within b's depth of the corner open straight
    into run b, or sit hidden behind the filler leg that closes the corner, so they must end that clearance before
    the column b occupies; the exception is an open notch, where run b itself starts beyond the front's full travel.
    The dead corner that results is closed by an L-shaped filler: a leg on each run, and b's cabinet side.
    """
    out = []
    order = list(k.room.order)
    for a, b in zip(order, order[1:]):
        La = k.room.wall(a).planning_length
        for level in ("base", "wall", "high"):
            ra, rb = run_at_end(k, a, level), run_at_start(k, b, level)
            if ra is None or rb is None or not ra.items or not rb.items:
                continue
            if any(p.catalog_item and p.catalog_item.corner for p in (ra.items[-1], rb.items[0])):
                continue   # corner cabinets have their own rules (rule_corners)
            if any(p.unresolved for p in ra.items + rb.items):
                continue
            g = corner_clearances(k, a, b, level)
            depth_a = g["depth_a"]
            first_body_b = next((p for p in rb.items if p.kind in ("cabinet", "appliance")), None)
            depth_b = item_depth(first_body_b, level) if first_body_b else 0
            if not first_body_b or depth_a <= 0:
                continue
            # (2) run b's first opening front faces run a's front plane, projected along wall b through the surveyed angle
            # the same way corner_clearances projects the frames (at 90 degrees this is depth_a plus the front)
            t = math.radians(g["theta"])
            plane_b = int(math.ceil((depth_a + FRONT_THICKNESS + max(0.0, depth_b * math.cos(t))) / math.sin(t)))
            q = next((p for p in rb.items if _front_clearance(p) > 0), None)
            if q is not None:
                need = plane_b + _front_clearance(q)
                if q.start < need - CORNER_TOL:
                    square = f" (corner is {g['theta']:.1f}°)" if abs(g["theta"] - 90) > 0.5 else ""
                    out.append(Finding("error", "corner_swing", f"{level}: '{q.label}' starts {q.start} mm along wall {b}, facing the wall-{a} fronts at {plane_b} mm{square}; IKEA wants {_front_clearance(q)} mm beside an obstruction (more with larger handles), so start it at {need} mm or later, with a filler in front of the corner", b, q.label, {"need_start_mm": need}))
            # an open notch is measured to the first thing that stands in run b, not to a leading gap
            notch_start = next((p.start for p in rb.items if p.kind != "gap"), rb.start)
            # (1) run a's fronts inside the column that run b occupies open into b's first cabinet's side
            for p in ra.items:
                c = _front_clearance(p)
                if c == 0:
                    continue
                column = La - depth_b - c
                if p.end <= column + CORNER_TOL:
                    continue
                if notch_start >= plane_b + _opening_reach(p, level):
                    continue   # an open notch: run b, filler leg included, starts beyond this front's full travel
                what = "door" if c == MIN_CLEARANCE_DOOR_MM and p.kind == "cabinet" else ("drawers" if p.kind == "cabinet" else p.appliance.kind)
                out.append(Finding("error", "corner_swing", f"{level}: '{p.label}' ends {La - p.end} mm from the corner, inside the {depth_b} mm the wall-{b} cabinets occupy, so its {what} open into wall-{b} run or sit behind its corner filler; end it at least {depth_b + c} mm before the corner (IKEA: {c} mm beside an obstruction, more with larger handles), or use a corner cabinet", a, p.label, {"need_end_mm": column}))
    return out


def rule_exposed_side(k: Kitchen) -> list[Finding]:
    """A cabinet side that shows needs a cover panel; the purchase pack derives it from the same list (issue #7)."""
    from .purchase import cover_panel_id   # the pack's panel choice, so the warning names what the pack will buy

    out = []
    for run, side, p, faces in exposed_sides(k):
        pid = cover_panel_id(k, run.level)
        out.append(Finding("warning", "exposed_side", f"{run.level}: the {side} side of '{p.label}' faces {faces} and shows; it needs a cover panel" + (f" ({pid} in the purchase pack)" if pid else ""), run.wall, p.label, {"side": side}))
    return out


def rule_filler_stock(k: Kitchen) -> list[Finding]:
    """A filler or panel wider than the cover panel it is ripped from cannot be one piece (issue #7)."""
    from .purchase import filler_stock_width

    out = []
    for run in k.runs:
        stock = None
        for p in run.items:
            if p.kind not in ("filler", "panel"):
                continue
            stock = filler_stock_width(k, run.level) if stock is None else stock
            if p.width > stock:
                out.append(Finding("warning", "filler_stock", f"{run.level}: {p.kind} '{p.label}' is {p.width} mm wide but the {run.level} cover panels it is ripped from are {stock} mm; plan two pieces or a different panel", run.wall, p.label, {"stock_mm": stock}))
    return out


def rule_backsplash_window(k: Kitchen) -> list[Finding]:
    """The backsplash band runs into a window whose sill is below the band's top (issue #8). The owner decides what
    happens there (tile to the sill, a lower band under the window, another backsplash_height), so this is a warning."""
    out = []
    for run in k.runs:
        if run.level != "base" or not run.items:
            continue
        wall = k.room.wall(run.wall)
        for o in wall.openings:
            if o.kind != "window" or o.sill is None:
                continue
            for a0, a1, y1 in backsplash_spans(k, run):
                lo, hi = max(a0, o.start), min(a1, o.end)
                if lo < hi and y1 > o.sill:
                    name = f"window '{o.label}'" if o.label else "the window"
                    out.append(Finding("warning", "backsplash_window", f"the backsplash band (to {y1} mm) runs {y1 - o.sill} mm into {name} (sill {o.sill} mm) over {lo}–{hi} mm; tile to the sill, lower the band there, or change backsplash_height", run.wall, o.label, {"overlap_mm": y1 - o.sill, "from": lo, "to": hi}))
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
    rule_run_overlap,
    rule_wall_filler_min,
    rule_cut_width_min,
    rule_appliance_side_clearance,
    rule_opening_conflict,
    rule_service_conflict,
    rule_front_fit,
    rule_hood_clearance,
    rule_ceiling,
    rule_corners,
    rule_corner_swing,
    rule_exposed_side,
    rule_filler_stock,
    rule_backsplash_window,
    rule_unique_labels,
    rule_finishes,
    rule_unverified_catalog,
)


def validate(k: Kitchen) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(k))
    return findings
