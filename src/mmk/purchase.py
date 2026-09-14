"""Phase 6: the purchase pack.

Everything the layout implies but does not list: suspension rail, legs,
hinges, MAXIMERA drawers behind drawer fronts, cover panels on exposed
sides, toe kick, filler stock, plus the countertop outline. Every derived
quantity carries the rule that produced it, so a line can be argued with.
Nothing here is a dimension source; it reads the resolved kitchen only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from .bom import BomLine, bill_of_materials
from .catalog import Item
from .draw import corner_start, counter_depth, counter_segments, item_depth, run_depth
from .model import Kitchen, Run, wall_frames
from .scene import COUNTER_OVERHANG_DEFAULT

RAIL_ID = "rail:sektion:88"
LEGS_ID = "legs:sektion:4pack"
HINGE_ID = "hinge:utrusta:2pack"
TOE_KICK_ID = "toe_kick:forbattra:87"
DRAWER_HEIGHT_FOR_FRONT = {5: "low", 10: "medium", 15: "high", 20: "high"}
COVER_PANEL_FOR_LEVEL = {"base": "cover_panel:forbattra:25x30", "wall": "cover_panel:forbattra:13x30", "high": "cover_panel:forbattra:25x90"}
HINGE_PACKS_TALL_DOOR = 2
TALL_DOOR_IN = 40

NOT_IN_SCOPE = (
    "sink, faucet and drain kit",
    "range hood and ducting",
    "cabinet and under-cabinet lighting",
    "handles and knobs (ENKÖPING, BODBYN and AXSTAD all need them)",
    "shelves beyond what frames include, drawer dividers, organisers",
    "countertop fabrication, sink cut-out and seams (see countertop.svg)",
    "backsplash tile, grout and trim",
)


@dataclass
class PurchaseLine(BomLine):
    rule: str = ""
    derived: bool = False


@dataclass
class PurchasePack:
    lines: list[PurchaseLine]
    assumptions: list[str]
    not_in_scope: tuple[str, ...] = NOT_IN_SCOPE
    countertop: list[dict] = field(default_factory=list)

    @property
    def unverified(self) -> list[PurchaseLine]:
        return [l for l in self.lines if not l.verified]

    @property
    def missing_articles(self) -> list[PurchaseLine]:
        return [l for l in self.lines if l.article is None and l.kind not in ("appliance", "finish", "filler")]


def _line(item: Item, qty: int, rule: str, detail: str = "") -> PurchaseLine:
    return PurchaseLine(item.id, item.kind, item.name, qty, item.article, item.verified, detail, rule, True)


def _is_corner_start(k: Kitchen, run: Run) -> bool:
    """A run that starts within what the previous wall's cabinets occupy (their depth, or a corner cabinet's reach) starts in the corner."""
    return corner_start(k, run)[0]


def exposed_sides(k: Kitchen) -> list[tuple[Run, str, object]]:
    """(run, 'start'|'end', item) for every run end that is neither at a wall nor in a corner."""
    out = []
    for run in k.runs:
        if not run.items:
            continue
        L = k.room.wall(run.wall).planning_length
        first, last = run.items[0], run.items[-1]
        if run.start > 0 and not _is_corner_start(k, run) and first.kind not in ("gap", "filler"):
            out.append((run, "start", first))
        if run.end < L and last.kind not in ("gap", "filler"):
            out.append((run, "end", last))
    return out


def derive(k: Kitchen) -> PurchasePack:
    cat = k.catalog
    lines: list[PurchaseLine] = [PurchaseLine(**l.__dict__) for l in bill_of_materials(k)]
    assumptions: list[str] = []

    def add(item_id: str, qty: int, rule: str, detail: str = "") -> None:
        if qty <= 0:
            return
        item = cat.get(item_id)
        if item is None:
            lines.append(PurchaseLine(item_id, "unknown", item_id, qty, None, False, detail, rule, True))
            return
        for l in lines:
            if l.id == item_id:
                l.qty += qty
                if detail and detail not in l.detail:
                    l.detail = f"{l.detail}; {detail}" if l.detail else detail
                return
        lines.append(_line(item, qty, rule, detail))

    # rail: per wall, all levels that hang on it
    rail = cat.get(RAIL_ID)
    stock = rail.stock_mm if rail and rail.stock_mm else 2235
    for wid in k.room.order:
        for level in ("base", "wall", "high"):
            length = sum(r.length for r in k.runs if r.wall == wid and r.level == level)
            if length:
                n = math.ceil(length / stock)
                add(RAIL_ID, n, "rail", f"wall {wid} {level}: {length} mm / {stock} mm stock")
    assumptions.append(f"Suspension rail: every base, wall and high run hangs on rail; one {stock} mm rail per started {stock} mm, per wall and level. Rails can be cut and joined, so a wall with several short runs may need fewer.")

    # legs: one pack per base/high cabinet
    n_legs = sum(1 for r in k.runs if r.level in ("base", "high") for p in r.items if p.kind == "cabinet")
    add(LEGS_ID, n_legs, "legs", f"{n_legs} base/high cabinets")
    assumptions.append("Legs: one 4-pack per base or high cabinet. Cabinets 36\" and wider are sometimes given extra legs; IKEA's planner is the arbiter.")

    # hinges: per door
    packs = 0
    doors = 0
    for r in k.runs:
        for p in r.items:
            for fu in p.fronts:
                if fu.item.kind == "front":
                    doors += fu.count
                    if fu.item.type == "corner_door":
                        packs += fu.count  # bi-fold set: one pack per set in this model; IKEA lists corner hinges separately
                    else:
                        packs += fu.count * (HINGE_PACKS_TALL_DOOR if fu.item.nominal_in.get("h", 0) > TALL_DOOR_IN else 1)
    add(HINGE_ID, packs, "hinges", f"{doors} doors")
    assumptions.append(f"Hinges: one 2-pack per door up to {TALL_DOOR_IN}\" tall, {HINGE_PACKS_TALL_DOOR} packs per taller door; one pack per corner bi-fold set (IKEA sells a corner hinge; check the planner). Horizontal (30x15, 36x15) doors may take a lift hinge instead.")

    # drawers behind drawer fronts
    for r in k.runs:
        for p in r.items:
            if p.kind != "cabinet" or not p.catalog_item:
                continue
            w = p.catalog_item.nominal_in.get("w")
            d = 24 if (p.catalog_item.d or 610) >= 600 else 15
            for fu in p.fronts:
                if fu.item.kind != "drawer_front":
                    continue
                h_in = fu.item.nominal_in.get("h", 0)
                size = DRAWER_HEIGHT_FOR_FRONT.get(int(h_in))
                if size is None:
                    assumptions.append(f"{p.label}: no drawer rule for a {h_in}\" front; add one by hand.")
                    continue
                add(f"drawer:maximera:{w:g}x{d}:{size}", fu.count, "drawers", f"behind {fu.item.id} on {p.label}")
    assumptions.append("Drawers: one MAXIMERA drawer per drawer front, sized by front height (5\" low, 10\" medium, 15\" and 20\" high) and frame depth. Interior drawers behind doors are not derived.")

    # cover panels on exposed sides
    for run, side, item in exposed_sides(k):
        pid = COVER_PANEL_FOR_LEVEL.get(run.level)
        if pid:
            add(pid, 1, "cover panel", f"{item.label} {side} side is exposed")
    assumptions.append("Cover panels: one per exposed cabinet side (a run end that is not against a wall and not in a corner). Dishwasher side panels and end panels that the appliance hides are not added.")

    # toe kick
    tk = cat.get(TOE_KICK_ID)
    tk_stock = tk.stock_mm if tk and tk.stock_mm else 2210
    base_len = sum(r.length for r in k.runs if r.level == "base")
    add(TOE_KICK_ID, math.ceil(base_len / tk_stock) if base_len else 0, "toe kick", f"{base_len} mm of base run / {tk_stock} mm strip")
    assumptions.append("Toe kick: base run length divided by the strip length, rounded up; ignores the appliance gaps where no kick is needed.")

    # filler stock from cover panels
    for level, pid in COVER_PANEL_FOR_LEVEL.items():
        widths = [p.width for r in k.runs if r.level == level for p in r.items if p.kind == "filler"]
        if not widths:
            continue
        panel = cat.get(pid)
        panel_w = panel.w if panel else 635
        n = math.ceil(sum(widths) / panel_w)
        add(pid, n, "filler stock", f"{level} fillers {', '.join(str(w) for w in widths)} mm ripped from {panel_w} mm wide panels")
    assumptions.append("Fillers: ripped from cover panels of the same level; count assumes the strips can share a panel by total width. Check the grain direction on wood-effect finishes.")

    return PurchasePack(lines, assumptions, countertop=countertop_slabs(k))


# ---------------------------------------------------------------- countertop

def countertop_slabs(k: Kitchen) -> list[dict]:
    """One slab per base run in plan coordinates: along/into extents and the corner it shares, if any."""
    frames = wall_frames(k.room)
    slabs = []
    for run in k.runs:
        if run.level != "base" or not run.items:
            continue
        depth = counter_depth(run) + COUNTER_OVERHANG_DEFAULT
        for i, (a0, a1) in enumerate(counter_segments(k, run)):
            slabs.append({"wall": run.wall, "start": a0, "end": a1, "length_mm": a1 - a0, "depth_mm": depth,
                          "corner_start": i == 0 and _is_corner_start(k, run), "frame": frames[run.wall],
                          "cut_by": [p.label for p in run.items if p.kind == "appliance" and p.appliance and (p.end == a0 or p.start == a1)]})
    return slabs


def countertop_svg(k: Kitchen, scale: int = 20) -> str:
    slabs = countertop_slabs(k)
    pts = []
    polys = []
    for s in slabs:
        x, y, hx, hy = s["frame"]
        nx, ny = -hy, hx
        a0, a1, d = s["start"], s["end"], s["depth_mm"]
        corners = [(x + hx * a + nx * i, y + hy * a + ny * i) for a, i in ((a0, 0), (a1, 0), (a1, d), (a0, d))]
        polys.append((s, corners))
        pts += corners
    if not pts:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text x="10" y="50">no base runs</text></svg>\n'
    M = 300
    minx, maxx = min(p[0] for p in pts) - M, max(p[0] for p in pts) + M
    miny, maxy = min(p[1] for p in pts) - M - 220, max(p[1] for p in pts) + M
    W, H = maxx - minx, maxy - miny
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W / scale:.3f}mm" height="{H / scale:.3f}mm" viewBox="{minx:g} {miny:g} {W:g} {H:g}" data-scale="1:{scale}" data-units="mm">',
           '<style>.slab{fill:#e4e4e0;stroke:#000;stroke-width:4}.t{font:42px Helvetica,Arial,sans-serif}.s{font:34px Helvetica,Arial,sans-serif}.dim{stroke:#000;stroke-width:2}</style>',
           f'<rect x="{minx:g}" y="{miny:g}" width="{W:g}" height="{H:g}" fill="#fff"/>',
           f'<text x="{minx + M:g}" y="{miny + 90:g}" class="t" font-weight="bold">Countertop outline — {escape(k.name)}</text>',
           f'<text x="{minx + M:g}" y="{miny + 150:g}" class="s">plan view, real mm; depth includes the {COUNTER_OVERHANG_DEFAULT} mm front overhang; corner joint where slabs overlap. Sink cut-out and seams are the fabricator\'s.</text>']
    total_len = 0
    for s, c in polys:
        out.append(f'<polygon points="{" ".join(f"{x:g},{y:g}" for x, y in c)}" class="slab" data-wall="{s["wall"]}" data-length="{s["length_mm"]}" data-depth="{s["depth_mm"]}"/>')
        cx = sum(x for x, _ in c) / 4
        cy = sum(y for _, y in c) / 4
        x, y, hx, hy = s["frame"]
        rot = -90 if abs(hy) > abs(hx) else 0
        out.append(f'<text x="{cx:g}" y="{cy:g}" class="t" text-anchor="middle" transform="rotate({rot} {cx:g} {cy:g})">wall {s["wall"]} {s["start"]}–{s["end"]}: {s["length_mm"]} × {s["depth_mm"]} mm{" · corner" if s["corner_start"] else ""}</text>')
        total_len += s["length_mm"]
    out.append(f'<text x="{minx + M:g}" y="{maxy - 120:g}" class="s">total run {total_len} mm · slabs {len(polys)} · area ≈ {sum(s["length_mm"] * s["depth_mm"] for s, _ in polys) / 1e6:.2f} m² before cut-outs</text>')
    out.append("</svg>\n")
    return "\n".join(out)


# ---------------------------------------------------------------- rendering

def render_pack(k: Kitchen, pack: PurchasePack) -> str:
    out = [f"# Purchase pack — {k.name}", "", "Every line comes from the layout file. Lines marked derived follow a rule listed under Assumptions.", ""]
    out.append(f"{'qty':>4}  {'id':40} {'article':12} {'name'}")
    for l in pack.lines:
        flags = []
        if not l.verified and l.kind not in ("appliance", "finish"):
            flags.append("unverified")
        if l.article is None and l.kind not in ("appliance", "finish", "filler"):
            flags.append("no article")
        tag = f"  [{', '.join(flags)}]" if flags else ""
        out.append(f"{l.qty:>4}  {l.id:40} {l.article or '-':12} {l.name}{tag}")
        if l.detail or l.rule:
            out.append(f"{'':4}  {'':40} {'':12} {(l.rule + ': ') if l.rule else ''}{l.detail}")
    out += ["", "## Countertop", ""]
    for s in pack.countertop:
        out.append(f"- wall {s['wall']} {s['start']}–{s['end']}: {s['length_mm']} × {s['depth_mm']} mm" + (" (starts in the corner; joint with the previous wall's slab)" if s["corner_start"] else "") + (f" (ends at {', '.join(s['cut_by'])})" if s.get("cut_by") else ""))
    out += ["", "## Assumptions", ""] + [f"- {a}" for a in pack.assumptions]
    out += ["", "## Not in this pack", ""] + [f"- {x}" for x in pack.not_in_scope]
    n_unv = len(pack.unverified)
    n_art = len(pack.missing_articles)
    out += ["", "## Status", "", f"- {len(pack.lines)} lines; {n_unv} unverified against a product page; {n_art} without an article number.",
            "- Not ready to buy until every purchasable line has a verified article number and `mmk reconcile` reports no unexplained differences."]
    return "\n".join(out) + "\n"


def pack_csv(pack: PurchasePack) -> str:
    rows = ["id,kind,qty,article,name,verified,rule,detail"]
    for l in pack.lines:
        def q(s: object) -> str:
            t = str(s if s is not None else "")
            return '"' + t.replace('"', '""') + '"' if any(c in t for c in ',"\n') else t
        rows.append(",".join(q(x) for x in (l.id, l.kind, l.qty, l.article, l.name, l.verified, l.rule, l.detail)))
    return "\n".join(rows) + "\n"
