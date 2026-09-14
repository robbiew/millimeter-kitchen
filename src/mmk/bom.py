"""Bill of materials: every catalog item the layout uses, with counts.

Phase 4 needs this so a finish or front change is visible as a change in
what gets bought. Phase 6 extends it with rails, legs, hinges, panels and
the countertop drawing.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from .finishes import load_finishes
from .model import Kitchen
from .scene import resolve_materials


@dataclass
class BomLine:
    id: str
    kind: str
    name: str
    qty: int
    article: str | None
    verified: bool
    detail: str = ""


def bill_of_materials(k: Kitchen) -> list[BomLine]:
    lines: "OrderedDict[str, BomLine]" = OrderedDict()

    def add(item, qty: int = 1, detail: str = "") -> None:
        if item.id in lines:
            lines[item.id].qty += qty
        else:
            lines[item.id] = BomLine(item.id, item.kind, item.name, qty, item.article, item.verified, detail)

    fillers: list[int] = []
    for run in k.runs:
        for p in run.items:
            if p.kind == "cabinet" and p.catalog_item:
                add(p.catalog_item)
                for fu in p.fronts:
                    add(fu.item, fu.count)
            elif p.kind == "filler":
                fillers.append(p.width)
            elif p.kind == "appliance" and p.appliance:
                key = f"appliance:{p.appliance.ref}"
                if key in lines:
                    lines[key].qty += 1
                else:
                    lines[key] = BomLine(key, "appliance", p.appliance.name, 1, None, True, f"{p.appliance.width}×{p.appliance.depth}×{p.appliance.height} mm, from manufacturer sheet")
    if fillers:
        lines["filler:cut"] = BomLine("filler:cut", "filler", "Filler strips, cut to width", len(fillers), None, False, "widths " + ", ".join(f"{w} mm" for w in fillers))
    mats = resolve_materials(k, load_finishes())
    for role, f in mats.items():
        if role in ("frame", "front", "glass"):
            continue
        lines[f"finish:{role}"] = BomLine(f"finish:{role}", "finish", f.name, 1, None, True, f"{role}: {f.key}")
    return list(lines.values())


def render_bom(k: Kitchen, lines: list[BomLine]) -> str:
    out = [f"Bill of materials — {k.name}", ""]
    out.append(f"{'qty':>4}  {'id':44} {'article':12} {'name'}")
    for l in lines:
        flag = "" if l.verified else "  (unverified)"
        out.append(f"{l.qty:>4}  {l.id:44} {l.article or '-':12} {l.name}{flag}")
        if l.detail:
            out.append(f"{'':4}  {'':44} {'':12} {l.detail}")
    return "\n".join(out)
