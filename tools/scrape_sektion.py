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

The search-API parsing was written without access to ikea.com, so the first
run may need a regex adjusted: --dump shows what the site returned.

Usage:
  python tools/scrape_sektion.py catalog/sektion-us-2026-09.json --discover           # report only
  python tools/scrape_sektion.py catalog/sektion-us-2026-09.json --discover --write   # write articles + verify
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
    """Every dict in a search response that looks like a product (has an item number and a measure text)."""
    out: list[dict] = []
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if (node.get("itemNo") or node.get("itemNoGlobal")) and ("itemMeasureReferenceText" in node or "measurementText" in node):
                out.append(node)
            else:
                stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def node_article(node: dict) -> str:
    digits = str(node.get("itemNo") or node.get("itemNoGlobal") or "").replace(".", "")
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:]}" if len(digits) == 8 else digits


def node_text(node: dict) -> str:
    """The words a product is described by: name, type, finish/colour, image alt."""
    parts = []
    for k in ("name", "typeName", "itemType", "mainImageAlt", "colors", "color", "colour"):
        v = node.get(k)
        if isinstance(v, list):
            parts.extend(str(x.get("name", x) if isinstance(x, dict) else x) for x in v)
        elif v:
            parts.append(str(v))
    return " ".join(parts).lower()


def node_measure(node: dict) -> dict[str, float]:
    text = node.get("itemMeasureReferenceText") or node.get("measurementText") or ""
    return parse_measure_text(text)


def discovery_query(item: dict) -> str:
    """What to type into ikea.com's search box for this catalog entry."""
    return item["name"]


def match_item(item: dict, nodes: list[dict], tol_in: float = 0.3) -> tuple[dict | None, list[dict]]:
    """The one search result that is this item, else None plus the near misses.

    A result matches when the series name appears in it, every nominal
    dimension the catalog knows agrees within `tol_in` inches, and for fronts
    the finish words (e.g. "walnut") appear too. Two matches is ambiguity, not a match.
    """
    series = (item.get("series") or "").lower()
    finish_words = [w for w in (item.get("finish") or "").lower().replace("-", " ").split() if w not in ("effect", "finish")]
    want = item.get("nominal_in") or {}
    hits, near = [], []
    for n in nodes:
        text = node_text(n)
        if series and series not in text:
            continue
        got = node_measure(n)
        size_ok = bool(got) and all(k in got and abs(got[k] - v) <= tol_in for k, v in want.items())
        finish_ok = all(w in text for w in finish_words)
        if size_ok and finish_ok:
            hits.append(n)
        elif size_ok or finish_ok:
            near.append(n)
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
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    args = ap.parse_args(argv)

    path = Path(args.catalog)
    data = json.loads(path.read_text())
    today = date.today().isoformat()
    changed = 0

    if args.query:
        nodes = search_products(args.query)
        print(f"# {search_url(args.query, 8)}: {len(nodes)} product(s)")
        for n in nodes:
            keys = ("itemNo", "name", "typeName", "itemMeasureReferenceText", "measurementText", "mainImageAlt")
            print("   " + json.dumps({k: n.get(k) for k in keys if k in n}, ensure_ascii=False))
        return 0

    if args.discover:
        found = ambiguous = missing = 0
        todo = [it for it in data["items"] if not it.get("article")]
        if args.limit:
            todo = todo[: args.limit]
        for item in todo:
            q = discovery_query(item)
            nodes = search_products(q)
            time.sleep(args.delay)
            hit, near = match_item(item, nodes)
            if hit:
                art = node_article(hit)
                print(f"{item['id']}: {art}  {hit.get('name', '')} {hit.get('typeName', '')} {hit.get('itemMeasureReferenceText') or hit.get('measurementText') or ''}")
                found += 1
                if args.write:
                    item["article"] = art
                    changed += 1
            elif near:
                ambiguous += 1
                print(f"{item['id']}: AMBIGUOUS for {q!r}; candidates:")
                for n in near[:6]:
                    print(f"      {node_article(n)}  {n.get('name', '')} {n.get('typeName', '')} {n.get('itemMeasureReferenceText') or n.get('measurementText') or ''}")
            else:
                missing += 1
                print(f"{item['id']}: no result for {q!r}" + ("" if nodes else " (empty response: blocked, or the field names changed; try --query with --dump)"))
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
