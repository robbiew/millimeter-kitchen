"""Pull article numbers from an IKEA Kitchen Planner item list into the catalog.

The planner's item list is the one place every article number for a real
layout appears together. Each row carries a product name that IKEA writes
as "<SERIES> <type>, <finish>, <size> \"" and a quantity. This module
matches rows to catalog entries by kind, series, finish and nominal size,
and reports every row as matched, ambiguous or unmatched. With write=True
it records the article on the matched entries and marks them verified,
because a planner row ties an article number to a nominal size, which is
what buying needs.

Nothing here guesses: an ambiguous row sets nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from pathlib import Path

from .reconcile import norm_article, read_ikea_list

FRACTION_GLYPHS = {"½": " 1/2", "¼": " 1/4", "¾": " 3/4", "⅛": " 1/8", "⅜": " 3/8", "⅝": " 5/8", "⅞": " 7/8"}
_SIZE = re.compile(r"(?<![\d/])(\d+(?: \d+/\d+)?)\s*x\s*(\d+(?: \d+/\d+)?)(?:\s*x\s*(\d+(?: \d+/\d+)?))?\s*(?:\"|&quot;|”|in\b)?", re.I)

KIND_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # (kind, all of these words must appear, none of these may)
    ("drawer_front", ("drawer front",), ()),
    ("front", ("door",), ("hinge", "damper", "drawer")),
    ("drawer", ("drawer",), ("front",)),
    ("cover_panel", ("cover panel",), ()),
    ("toe_kick", ("toe kick", "toekick", "plinth"), ()),
    ("rail", ("suspension rail", "rail"), ()),
    ("legs", ("leg",), ("legs of",)),
    ("hinge", ("hinge",), ()),
    ("frame", ("cabinet frame", "cabinet"), ("door", "front", "panel", "leg", "rail", "hinge", "drawer")),
]


def _norm(text: str) -> str:
    for g, f in FRACTION_GLYPHS.items():
        text = text.replace(g, f)
    return re.sub(r"\s+", " ", text.replace("&quot;", '"')).strip().lower()


def _num(s: str) -> float:
    s = s.strip()
    if " " in s:
        w, f = s.split(" ", 1)
        return float(Fraction(w) + Fraction(f))
    return float(Fraction(s))


def parse_size(text: str) -> tuple[float, ...] | None:
    m = _SIZE.search(_norm(text))
    if not m:
        return None
    return tuple(_num(g) for g in m.groups() if g)


def guess_kind(text: str) -> str | None:
    t = _norm(text)
    for kind, needs, forbids in KIND_RULES:
        if any(n in t for n in needs) and not any(f in t for f in forbids):
            return kind
    return None


def frame_type(text: str) -> str | None:
    t = _norm(text)
    if "high cabinet" in t:
        return "high"
    if "wall cabinet" in t:
        return "wall_fridge" if ("fridge" in t or "refrigerator" in t) else "wall"
    if "base cabinet" in t:
        return "base"
    return None


@dataclass
class RowResult:
    article: str
    name: str
    qty: int
    kind: str | None
    size: tuple[float, ...] | None
    matches: list[str] = field(default_factory=list)
    status: str = "unmatched"  # matched | ambiguous | unmatched | conflict
    note: str = ""


@dataclass
class ImportReport:
    rows: list[RowResult]
    written: int = 0

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.status] = out.get(r.status, 0) + 1
        return out

    def render(self) -> str:
        c = self.counts()
        out = [f"rows {len(self.rows)}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) + (f" · wrote {self.written} catalog entries" if self.written else "")]
        for status in ("matched", "ambiguous", "conflict", "unmatched"):
            rows = [r for r in self.rows if r.status == status]
            if not rows:
                continue
            out.append(f"\n{status.upper()}")
            for r in rows:
                ids = ", ".join(r.matches) if r.matches else "-"
                out.append(f"  {r.article:12} {r.name[:56]:56} → {ids}" + (f"  ({r.note})" if r.note else ""))
        return "\n".join(out) + "\n"


def _same(a: tuple, b: tuple, tol: float = 0.3) -> bool:
    """Nominal sizes agree: a planner row says 30x15x30 where the catalog says 30x14 3/4x30."""
    return len(a) == len(b) and all(x is not None and y is not None and abs(x - y) <= tol for x, y in zip(a, b))


def _candidates(items: list[dict], row_text: str, kind: str, size: tuple[float, ...] | None) -> list[dict]:
    t = _norm(row_text)
    out = []
    for it in items:
        if it["kind"] != kind:
            continue
        ni = it.get("nominal_in", {})
        if kind == "frame":
            ft = frame_type(row_text)
            allowed = {"base", "sink_base"} if ft == "base" else ({ft} if ft else set())
            if it.get("type") not in allowed:
                continue
            if size is None or len(size) != 3 or not _same((ni.get("w"), ni.get("d"), ni.get("h")), size):
                continue
        elif kind in ("front", "drawer_front"):
            series = (it.get("series") or "").lower()
            finish_words = [w for w in re.split(r"[\s,/-]+", (it.get("finish") or "").lower()) if w and w not in ("effect",)]
            if series and series not in t:
                continue
            if finish_words and not all(w in t for w in finish_words):
                continue
            if size is None or len(size) != 2 or not _same((ni.get("w"), ni.get("h")), size):
                continue
        elif kind == "drawer":
            height_word = next((w for w in ("low", "medium", "high") if re.search(rf"\b{w}\b", t)), None)
            if height_word and not it["id"].endswith(":" + height_word):
                continue
            if size is None or len(size) < 2 or not _same((ni.get("w"), ni.get("d")), size[:2]):
                continue
        elif kind == "cover_panel":
            if size is None or len(size) != 2 or not _same((ni.get("w"), ni.get("h")), size):
                continue
        elif kind in ("toe_kick", "rail"):
            if size is not None and ni.get("w") is not None and not _same((ni.get("w"),), (size[0],)):
                continue
        out.append(it)
    return out


def import_list(catalog_path: str | Path, list_path: str | Path, write: bool = False, source_label: str | None = None) -> ImportReport:
    cat_path = Path(catalog_path)
    data = json.loads(cat_path.read_text())
    items = data["items"]
    ikea = read_ikea_list(list_path)
    rows: list[RowResult] = []
    to_write: dict[str, str] = {}  # item id -> article

    for art, info in ikea.items():
        name = info.get("name", "")
        kind = guess_kind(name)
        size = parse_size(name)
        r = RowResult(norm_article(art), name, info["qty"], kind, size)
        if kind is None:
            r.note = "could not tell what kind of product this is"
            rows.append(r)
            continue
        cands = _candidates(items, name, kind, size)
        r.matches = [c["id"] for c in cands]
        if not cands:
            r.note = "no catalog entry with this kind and size"
        elif kind == "frame" and {c.get("type") for c in cands} <= {"base", "sink_base"} and len({(c["nominal"]) for c in cands}) == 1:
            r.status = "matched"
            r.note = "same frame serves base and sink base" if len(cands) > 1 else ""
        elif len(cands) == 1:
            r.status = "matched"
        else:
            r.status = "ambiguous"
            r.note = "more than one catalog entry fits; narrow the catalog or the row"
        if r.status == "matched":
            for c in cands:
                existing = c.get("article")
                if existing and norm_article(existing) != r.article:
                    r.status = "conflict"
                    r.note = f"catalog already has {existing} for {c['id']}"
                    break
            else:
                for c in cands:
                    to_write[c["id"]] = r.article
        rows.append(r)

    written = 0
    if write and to_write:
        today = date.today().isoformat()
        label = source_label or f"ikea-planner-item-list:{Path(list_path).name}"
        for it in items:
            if it["id"] in to_write:
                it["article"] = to_write[it["id"]]
                it["verified"] = True
                it["verified_on"] = today
                it["source"] = label
                written += 1
        cat_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return ImportReport(rows, written)
