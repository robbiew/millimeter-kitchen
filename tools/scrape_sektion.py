#!/usr/bin/env python3
"""Find article numbers for, and verify, catalog entries against ikea.com (US).

Two passes, both read-only unless --write is given:

1. --discover: for every item WITHOUT an article number, ask IKEA's search
   API for the product by name and nominal size ("SEKTION base cabinet frame
   36x24x30", "VOXTORP door 15x30 walnut effect") and keep the one result
   whose series, size and finish all match. Ambiguous or missing results are
   reported and skipped, never guessed.
2. Verify: for every item WITH an article number (including the ones just
   found), read Width / Depth / Height from the product page (search API as
   a fallback), compare with the catalog's `actual` within 2 mm, and with
   --write set `verified: true`, `verified_on` and `source`.

Text search surfaces frame-plus-front combinations far more readily than
bare frames, so there is also --sweep: bare SEKTION frames cluster in a few
article families (02.653.xx to 02.655.xx) and the leading digit is a Luhn
check, so every number in a family can be looked up directly. Sweep results
are cached under the user's cache dir and used by --discover.

Usage:
  python tools/scrape_sektion.py catalog/sektion-us-2026-09.json --discover           # report only
  python tools/scrape_sektion.py catalog/sektion-us-2026-09.json --discover --write   # write articles + verify
  python tools/scrape_sektion.py catalog/... --sweep 02653-02655                      # every bare frame, by number
  python tools/scrape_sektion.py catalog/... --discover --limit 5                     # trial run
  python tools/scrape_sektion.py catalog/... --article 802.653.98 --dump              # show raw page text
  python tools/scrape_sektion.py catalog/... --query "VOXTORP door 15x30" --dump      # show search results

Be polite: one request per item, 0.5 s apart; the whole catalog takes a few minutes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mmk.units import inch_to_mm  # noqa: E402

UA = "Mozilla/5.0 (compatible; millimeter-kitchen catalog verifier; personal use)"
TOLERANCE_MM = 2


def product_url(article: str) -> str:
    return f"https://www.ikea.com/us/en/p/-{article.replace('.', '')}/"


def search_url(query: str, size: int = 5) -> str:
    """IKEA's search API returns structured product data, including itemMeasureReferenceText ("36x24x30 \"")."""
    return f"https://sik.search.blue.cdtapps.com/us/en/search-result-page?q={urllib.parse.quote(query.replace('.', '') if query.replace('.', '').isdigit() else query)}&types=PRODUCT&size={size}"


def product_nodes(data) -> list[dict]:
    """Every dict in a search response that looks like a product (has an item number and a measure text),
    plus each product's variants (gprDescription.variants: the other sizes and colours of the same product),
    which inherit the parent's name and type when they carry none of their own."""
    out: list[dict] = []
    seen: set[str] = set()
    stack = [data]

    def add(node: dict) -> None:
        no = str(node.get("itemNo") or node.get("itemNoGlobal") or "")
        if no and no not in seen:
            seen.add(no)
            out.append(node)

    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if (node.get("itemNo") or node.get("itemNoGlobal")) and ("itemMeasureReferenceText" in node or "measurementText" in node):
                add(node)
                for v in (node.get("gprDescription") or {}).get("variants") or []:
                    if isinstance(v, dict):
                        add({"name": node.get("name"), "typeName": node.get("typeName"), **v})
            else:
                stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def luhn_check(body: str) -> str:
    """IKEA's leading digit is a Luhn check over the other seven (holds for every article seen so far)."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def sweep_articles(spec: str) -> list[str]:
    """'02653-02655,05167' -> every 8-digit article whose middle five digits fall in those ranges."""
    out = []
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        hi = hi or lo
        for fam in range(int(lo), int(hi) + 1):
            for nn in range(100):
                body = f"{fam:05d}{nn:02d}"
                out.append(luhn_check(body) + body)
    return out


def sweep_cache_path() -> Path:
    import os
    root = Path(os.environ.get("MMK_IKEA_CACHE") or "~/.cache/millimeter-kitchen").expanduser()
    return root / "ikea-sweep.json"


def node_article(node: dict) -> str:
    digits = str(node.get("itemNo") or node.get("itemNoGlobal") or "").replace(".", "")
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}" if len(digits) == 8 else digits


def _ascii(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def node_text(node: dict) -> str:
    """The words a product is described by: name, type, colour fields, product URL."""
    parts = []
    for k in ("name", "typeName", "validDesignText", "colors", "color", "colour", "pipUrl", "url"):
        v = node.get(k)
        if isinstance(v, list):
            parts.extend(str(x.get("name", x) if isinstance(x, dict) else x) for x in v)
        elif v:
            parts.append(str(v))
    return _ascii(" ".join(parts)).replace("-", " ")


def node_measure(node: dict) -> dict[str, float]:
    text = node.get("itemMeasureReferenceText") or node.get("measurementText") or ""
    return parse_measure_text(text)


def node_sizes(node: dict) -> list[float]:
    """The numbers in the measure text, in order ("15x14 3/4x30 \"" -> [15, 14.75, 30])."""
    return list(node_measure(node).values())


# What ikea.com calls the bare product for each catalog family. IKEA US lists
# SEKTION mostly as combinations ("SEKTION / MAXIMERA Base cabinet with 3
# drawers"); the frame alone is name "SEKTION", typeName "Base cabinet" (or
# "... cabinet frame"). A typeName made only of these words is a bare frame.
FRAME_WORDS = {"base", "wall", "high", "top", "corner", "cabinet", "frame"}
FRAME_NEEDS = {"base": {"base"}, "sink_base": {"base"}, "wall": {"wall"}, "wall_fridge": {"wall"}, "high": {"high"},
               "base_corner": {"corner", "base"}, "wall_corner": {"corner", "wall"}}
FRONT_TYPES = {"door": lambda t: t == "door", "drawer": lambda t: t == "drawer front",
               "corner_door": lambda t: "door" in t and "corner" in t}
STOP = {"a", "of", "and", "the", "with", "pack", "set", "in", "mm"}
# When a family has no finish of its own, the colour the catalog assumes: SEKTION frames come in white and brown.
PREFER = {"frame": "white"}


def describe(n: dict) -> str:
    """One line for a search record: article, name, type, size, design text."""
    size = n.get("itemMeasureReferenceText") or n.get("measurementText") or ""
    design = n.get("validDesignText") or ""
    return f"{node_article(n)}  {n.get('name', '')} {n.get('typeName', '')} {size}" + (f"  [{design}]" if design else "")


def family(item: dict) -> tuple:
    return (item.get("series"), item["kind"], item.get("type"), item.get("finish"))


def family_query(item: dict) -> str:
    """One search that should list every size of this family: 'SEKTION base cabinet', 'VOXTORP door walnut effect'."""
    series = item.get("series") or ""
    kind, type_ = item["kind"], item.get("type")
    if kind == "frame":
        words = {"base": "base cabinet", "sink_base": "base cabinet", "wall": "wall cabinet", "wall_fridge": "wall cabinet",
                 "high": "high cabinet", "base_corner": "corner base cabinet", "wall_corner": "corner wall cabinet"}[type_]
        return f"{series} {words}"
    if kind in ("front", "drawer_front"):
        what = {"door": "door", "drawer": "drawer front", "corner_door": "door corner base cabinet"}[type_]
        return f"{series} {what}"
    return discovery_query(item)


def discovery_query(item: dict) -> str:
    """What to type into ikea.com's search box for exactly this catalog entry."""
    return item["name"]


def _name_words(item: dict) -> set[str]:
    """Descriptive words of a catalog name, minus the series, sizes and filler: 'MAXIMERA drawer, low, 15x24' -> {drawer, low}."""
    text = re.sub(r"\([^)]*\)", " ", _ascii(item["name"])).replace(",", " ")
    series = _ascii(item.get("series") or "")
    out = set()
    for w in text.split():
        if w == series or w in STOP or any(ch.isdigit() for ch in w):
            continue
        out.add(w)
    return out


def match_item(item: dict, nodes: list[dict], tol_in: float = 0.3) -> tuple[dict | None, list[dict]]:
    """The one search result that is this item, else None plus the near misses.

    A result matches when its product name is exactly the series, its type is
    the bare product for the family (a frame, a door, a drawer front, ...),
    every nominal dimension agrees within `tol_in` inches, and for fronts the
    finish words appear somewhere in its record. Two matches is ambiguity,
    not a match.
    """
    series = _ascii(item.get("series") or "")
    kind, type_ = item["kind"], item.get("type")
    finish_words = [w for w in _ascii(item.get("finish") or "").replace("-", " ").split() if w not in ("effect", "finish")]
    want = [v for k, v in (item.get("nominal_in") or {}).items() if k in ("w", "d", "h")]
    hits, near = [], []
    for n in nodes:
        name = _ascii(str(n.get("name") or "")).strip()
        if name != series:
            continue                      # "SEKTION / MAXIMERA ..." is a combination, not the frame
        tname = _ascii(str(n.get("typeName") or "")).replace("-", " ").strip()
        twords = set(tname.replace("/", " ").split())
        design = _ascii(str(n.get("validDesignText") or ""))
        if kind == "frame":
            # a bare frame's design text is just its colour ("white"); "white/Aspudden matte white" is a
            # frame-plus-front combination even when its type reads "Wall cabinet"
            type_ok = "cabinet" in twords and twords <= FRAME_WORDS and FRAME_NEEDS[type_] <= twords and "/" not in design
        elif kind in ("front", "drawer_front"):
            type_ok = FRONT_TYPES[type_](tname)
        else:
            type_ok = _name_words(item) <= set(node_text(n).replace(",", " ").split())
        got = node_sizes(n)
        size_ok = len(got) == len(want) and all(abs(a - b) <= tol_in for a, b in zip(got, want))
        text = node_text(n)
        finish_ok = all(w in text for w in finish_words)
        if type_ok and size_ok and finish_ok:
            hits.append(n)
        elif type_ok and (size_ok or finish_ok):
            near.append(n)        # the right kind of product in another size or finish; combinations never qualify
    if len(hits) > 1 and not finish_words and kind in PREFER:
        preferred = [n for n in hits if PREFER[kind] in node_text(n)]
        if len(preferred) == 1:
            return preferred[0], [n for n in hits if n is not preferred[0]] + near
    if len(hits) == 1:
        return hits[0], near
    return None, hits + near


def fetch_search(article: str) -> dict | None:
    """The product entry from the search API whose item number matches, or None."""
    try:
        data = json.loads(fetch(search_url(article)))
    except Exception:  # noqa: BLE001
        return None
    want = article.replace(".", "")
    for n in product_nodes(data):
        if node_article(n).replace(".", "") == want:
            return n
    return None


def search_products(query: str, size: int = 8) -> list[dict]:
    """Products the search API returns for a free-text query (empty on any failure)."""
    try:
        return product_nodes(json.loads(fetch(search_url(query, size))))
    except Exception:  # noqa: BLE001
        return []


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


# Anchors, most specific first. IKEA's product page ("PIP") renders the
# measurements list with pip-product-dimensions__* classes and also embeds
# product JSON with a measurementText like "36x24x30 \"".
DUMP_ANCHORS = ("itemMeasureReferenceText", "measurementText", "pipf-product-dimensions", "product-dimensions", "measurement-label", "typeName")
_LABEL_VALUE = re.compile(r'<span class="[^"]*measurement[^"]*label[^"]*">\s*([^<]{1,40}?)\s*</span>\s*([^<]{1,40}?)\s*<', re.I)

_NUM = r"(?P<num>\d+(?:\s\d+/\d+)?(?:\.\d+)?)"
# <dt ...>Width:</dt> <dd ...>36 "</dd>   (tags stripped first, so it reads: Width:  36 ")
_LIST_INCH = re.compile(r"(?P<label>Width|Depth|Height)\s*:?\s+" + _NUM + r"\s*(?:\"|&quot;|”|in\b)", re.I)
_LIST_CM = re.compile(r"(?P<label>Width|Depth|Height)\s*:?\s+" + _NUM + r"\s*cm\b", re.I)
_MEASUREMENT_TEXT = re.compile(r'"(?:measurementText|itemMeasureReferenceText)"\s*:\s*"(?P<text>[^"]+)"')


def _num(text: str) -> float:
    text = text.strip()
    if " " in text:
        whole, frac = text.split(" ", 1)
        return float(Fraction(whole) + Fraction(frac))
    return float(Fraction(text))


def parse_measure_text(text: str) -> dict[str, float]:
    """"36x24x30 \"" -> {w, d, h}; "18x30 \"" -> {w, h}."""
    parts = [re.sub(r"[^0-9 /.]", "", x).strip() for x in text.lower().split("x")]
    keys = ("w", "d", "h") if len(parts) == 3 else ("w", "h")
    out: dict[str, float] = {}
    for k, v in zip(keys, parts):
        try:
            out[k] = _num(v)
        except (ValueError, ZeroDivisionError):
            pass
    return out


def parse_measurements(html: str) -> dict[str, float]:
    """Return {w|d|h: inches} from the product page, trying the dimensions list first.

    Only the region around the dimensions block is searched so the site's
    translation strings (which also contain 'Width') cannot match.
    """
    region = html
    i = html.find("pip-product-dimensions")
    if i >= 0:
        region = html[i: i + 6000]
    text = re.sub(r"<[^>]+>", " ", region)
    found: dict[str, float] = {}
    for m in _LIST_INCH.finditer(text):
        key = m.group("label")[0].lower()
        found.setdefault(key, _num(m.group("num")))
    if len(found) < 2:
        for m in _LIST_CM.finditer(text):
            key = m.group("label")[0].lower()
            found.setdefault(key, _num(m.group("num")) / 2.54)
    if len(found) < 2:
        m = _MEASUREMENT_TEXT.search(html)
        if m:
            for k, v in parse_measure_text(m.group("text")).items():
                found.setdefault(k, v)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalog")
    ap.add_argument("--article", help="only this article number")
    ap.add_argument("--write", action="store_true", help="update verified flags in place")
    ap.add_argument("--dump", action="store_true", help="print page text around 'Width' and exit")
    ap.add_argument("--discover", action="store_true", help="find article numbers for items that have none (search API)")
    ap.add_argument("--query", help="with --dump: show what the search API returns for this text and exit")
    ap.add_argument("--limit", type=int, help="stop after this many items (trial run)")
    ap.add_argument("--size", type=int, default=24, help="with --query: how many results to ask for")
    ap.add_argument("--filter", help="with --query: only print records whose type contains this text (e.g. Door)")
    ap.add_argument("--sweep", metavar="RANGES", help="look up every article number in these families, e.g. 02653-02655,05167 "
                    "(the middle five digits; the check digit is computed). Records are saved for --discover to use.")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    args = ap.parse_args(argv)

    path = Path(args.catalog)
    data = json.loads(path.read_text())
    today = date.today().isoformat()
    changed = 0

    sweep_path = sweep_cache_path()
    swept: dict[str, dict] = json.loads(sweep_path.read_text()) if sweep_path.exists() else {}

    if args.sweep:
        arts = sweep_articles(args.sweep)
        print(f"# sweeping {len(arts)} article numbers; records go to {sweep_path}")
        hits = 0
        for i, art in enumerate(arts, 1):
            if art in swept:
                continue
            n = fetch_search(art)
            time.sleep(args.delay)
            if n:
                swept[art] = n
                hits += 1
                print(f"   {describe(n)}")
            if i % 25 == 0:
                sweep_path.parent.mkdir(parents=True, exist_ok=True)
                sweep_path.write_text(json.dumps(swept))
        sweep_path.parent.mkdir(parents=True, exist_ok=True)
        sweep_path.write_text(json.dumps(swept))
        print(f"# {hits} new record(s); {len(swept)} in the sweep cache")
        if not args.discover:
            return 0

    if args.query:
        nodes = search_products(args.query, size=args.size)
        print(f"# {search_url(args.query, args.size)}: {len(nodes)} product(s) incl. variants")
        if args.filter:
            nodes = [n for n in nodes if args.filter.lower() in str(n.get("typeName") or "").lower()]
            print(f"# {len(nodes)} with {args.filter!r} in the type")
        for n in nodes:
            print("   " + describe(n))
        if nodes and not args.filter:
            print("\n# every field of the first record (to find where the colour/finish lives):")
            print(json.dumps(nodes[0], indent=1, ensure_ascii=False)[:4000])
        return 0

    if args.discover:
        found = ambiguous = missing = 0
        todo = [it for it in data["items"] if not it.get("article")]
        if args.limit:
            todo = todo[: args.limit]
        bulk: dict[tuple, list[dict]] = {}
        for item in todo:
            fam = family(item)
            if fam not in bulk:
                bulk[fam] = list(swept.values()) if swept else []            # everything a sweep found, then one request per family
                bulk[fam] += search_products(family_query(item), size=100)
                time.sleep(args.delay)
            hit, near = match_item(item, bulk[fam])
            q = family_query(item)
            if not hit:                                                     # not in the family listing: ask for it by name
                q = discovery_query(item)
                nodes = search_products(q)
                time.sleep(args.delay)
                hit, near2 = match_item(item, nodes)
                near = near2 or near
            if hit:
                art = node_article(hit)
                print(f"{item['id']}: {describe(hit)}")
                found += 1
                if args.write:
                    item["article"] = art
                    changed += 1
            elif near:
                ambiguous += 1
                print(f"{item['id']}: AMBIGUOUS for {q!r}; candidates:")
                for n in near[:6]:
                    print(f"      {describe(n)}")
            else:
                missing += 1
                print(f"{item['id']}: no result for {q!r}" + ("" if bulk[fam] else " (empty response: blocked, or the field names changed; try --query with --dump)"))
        print(f"discover: {found} found, {ambiguous} ambiguous, {missing} missing of {len(todo)}")
        if args.write and changed:
            path.write_text(json.dumps(data, indent=2) + "\n")
            print(f"wrote {changed} article numbers to {path}; verifying them next")
            changed = 0

    for item in data["items"]:
        art = item.get("article")
        if not art or (args.article and art != args.article):
            continue
        if item.get("verified") and not args.article and not args.dump:
            continue   # already checked against the product page
        time.sleep(args.delay)
        url = product_url(art)
        try:
            html = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"{item['id']} {art}: fetch failed: {exc}")
            continue
        nominal = (item.get("nominal") or "").replace(" ", "")
        if args.dump:
            print(f"# {url}  ({len(html)} bytes)")
            anchors = DUMP_ANCHORS + ((nominal,) if nominal else ())
            for anchor in anchors:
                hits = [m.start() for m in re.finditer(re.escape(anchor), html)][:3]
                print(f"\n## anchor {anchor!r}: {len(hits)} hit(s) shown of {html.count(anchor)}")
                for i in hits:
                    print("   …" + html[max(0, i - 200): i + 400].replace("\n", " ") + "…")
            pairs = _LABEL_VALUE.findall(html)
            print(f"\n## measurement label/value pairs on the page ({len(pairs)}):")
            for label, value in pairs[:40]:
                print(f"   {label.strip():30} {value.strip()}")
            node = fetch_search(art)
            print(f"\n## search API {search_url(art)}")
            if node:
                keys = ("itemNo", "name", "typeName", "itemMeasureReferenceText", "measurementText", "mainImageAlt")
                print("   " + json.dumps({k: node.get(k) for k in keys if k in node}, ensure_ascii=False))
            else:
                print("   no matching product in the response (blocked, or the field names changed)")
            print("\n## parsed from page:", parse_measurements(html))
            return 0
        got = parse_measurements(html)
        source = url
        if len(got) < 2:
            node = fetch_search(art)
            text = (node or {}).get("itemMeasureReferenceText") or (node or {}).get("measurementText")
            if text:
                got = parse_measure_text(text)
                source = search_url(art)
        if not got:
            print(f"{item['id']} {art}: no measurements found; run with --dump and fix the regex")
            continue
        mm = {k: inch_to_mm(v) for k, v in got.items()}  # w/d/h
        want = item["actual"]
        diffs = {k: (want.get(k), mm.get(k)) for k in ("w", "d", "h") if k in want and k in mm and abs(want[k] - mm[k]) > TOLERANCE_MM}
        if diffs:
            print(f"{item['id']} {art}: MISMATCH {diffs} (catalog, page)")
            if args.write:
                item["actual"].update({k: v for k, v in mm.items() if k in want})
        else:
            print(f"{item['id']} {art}: ok {mm}")
        if args.write:
            item["verified"] = True
            item["verified_on"] = today
            item["source"] = source
            changed += 1
    if args.write and changed:
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"updated {changed} entries in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
