"""Phase 6: reconcile the purchase pack against the IKEA Kitchen Planner's item list.

The planner exports an item list (PDF; transcribe or export to CSV). Any
CSV or TSV with an article-number column and a quantity column works; the
header names are matched loosely. Lines match on article number, so a
purchase line without one cannot be reconciled and is reported as such.
Differences can be explained in a JSON file {article: reason} and then
count as explained rather than open.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .purchase import PurchasePack

ARTICLE_RE = re.compile(r"^\d{3}\.?\d{3}\.?\d{2}$")


def norm_article(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return f"{d[0:3]}.{d[3:6]}.{d[6:8]}" if len(d) == 8 else (s or "").strip()


@dataclass
class ReconcileReport:
    matched: list[dict] = field(default_factory=list)
    qty_differs: list[dict] = field(default_factory=list)
    only_in_ikea: list[dict] = field(default_factory=list)
    only_in_pack: list[dict] = field(default_factory=list)
    unreconcilable: list[dict] = field(default_factory=list)  # pack lines with no article number
    explained: list[dict] = field(default_factory=list)

    @property
    def open_differences(self) -> int:
        return len(self.qty_differs) + len(self.only_in_ikea) + len(self.only_in_pack)

    @property
    def clean(self) -> bool:
        return self.open_differences == 0 and not self.unreconcilable

    def render(self) -> str:
        out = [f"matched {len(self.matched)} · qty differs {len(self.qty_differs)} · only in IKEA list {len(self.only_in_ikea)} · only in pack {len(self.only_in_pack)} · explained {len(self.explained)} · unreconcilable {len(self.unreconcilable)}", ""]
        for title, rows in (("QUANTITY DIFFERS", self.qty_differs), ("ONLY IN IKEA LIST", self.only_in_ikea), ("ONLY IN PACK", self.only_in_pack)):
            if rows:
                out.append(title)
                out += [f"  {r['article']:12} pack {r.get('pack_qty', '-'):>3}  ikea {r.get('ikea_qty', '-'):>3}  {r.get('name', '')}" for r in rows]
                out.append("")
        if self.explained:
            out.append("EXPLAINED")
            out += [f"  {r['article']:12} {r['reason']}" for r in self.explained]
            out.append("")
        if self.unreconcilable:
            out.append("NO ARTICLE NUMBER (cannot reconcile; verify the catalog entry)")
            out += [f"  {r['id']:40} qty {r['qty']}" for r in self.unreconcilable]
            out.append("")
        out.append("CLEAN: zero unexplained differences" if self.clean else f"OPEN: {self.open_differences} unexplained difference(s), {len(self.unreconcilable)} line(s) without article numbers")
        return "\n".join(out) + "\n"


def read_ikea_list(path: str | Path) -> dict[str, dict]:
    """{article: {qty, name}} from a CSV/TSV item list with loosely named columns."""
    text = Path(path).read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t") if text.strip() else csv.excel
    rows = list(csv.reader(text.splitlines(), dialect))
    if not rows:
        return {}
    header = [h.strip().lower() for h in rows[0]]

    def col(*names: str) -> int | None:
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None

    ia = col("article", "art. no", "art no", "product number", "item number", "number")
    iq = col("qty", "quantity", "count", "pcs")
    iname = col("name", "product", "description", "item")
    if ia is None or iq is None:
        raise ValueError(f"could not find article and quantity columns in header {rows[0]}")
    out: dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) <= max(ia, iq) or not r[ia].strip():
            continue
        art = norm_article(r[ia])
        try:
            qty = int(float(r[iq].replace(",", ".")))
        except ValueError:
            continue
        name = r[iname].strip() if iname is not None and len(r) > iname else ""
        if art in out:
            out[art]["qty"] += qty
        else:
            out[art] = {"qty": qty, "name": name}
    return out


def reconcile(pack: PurchasePack, ikea: dict[str, dict], explanations: dict[str, str] | None = None) -> ReconcileReport:
    explanations = {norm_article(k): v for k, v in (explanations or {}).items()}
    rep = ReconcileReport()
    ours: dict[str, dict] = {}
    for l in pack.lines:
        if l.kind in ("appliance", "finish", "filler"):
            continue
        if not l.article:
            rep.unreconcilable.append({"id": l.id, "qty": l.qty, "name": l.name})
            continue
        art = norm_article(l.article)
        ours.setdefault(art, {"qty": 0, "name": l.name, "ids": []})
        ours[art]["qty"] += l.qty
        ours[art]["ids"].append(l.id)

    def settle(row: dict, bucket: list[dict]) -> None:
        reason = explanations.get(row["article"])
        if reason:
            rep.explained.append({**row, "reason": reason})
        else:
            bucket.append(row)

    for art, o in ours.items():
        if art in ikea:
            row = {"article": art, "pack_qty": o["qty"], "ikea_qty": ikea[art]["qty"], "name": o["name"]}
            if o["qty"] == ikea[art]["qty"]:
                rep.matched.append(row)
            else:
                settle(row, rep.qty_differs)
        else:
            settle({"article": art, "pack_qty": o["qty"], "name": o["name"]}, rep.only_in_pack)
    for art, i in ikea.items():
        if art not in ours:
            settle({"article": art, "ikea_qty": i["qty"], "name": i["name"]}, rep.only_in_ikea)
    return rep
