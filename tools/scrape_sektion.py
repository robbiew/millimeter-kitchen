"""Verify catalog entries against IKEA US product pages.

UNTESTED against ikea.com: this environment could not reach the site. The
parsing strategy is a best guess at the product page's measurement block and
will need adjusting the first time it runs. Use --dump to see what the page
returned around the word "Width" and fix the regexes.

For each catalog item with an article number, fetch the product page, read
Width / Depth / Height in inches, convert to millimeters, compare with the
catalog's `actual`, and (with --write) set `verified: true` and `verified_on`.

Usage:
  python tools/scrape_sektion.py catalog/sektion-us-2026-09.json            # report only
  python tools/scrape_sektion.py catalog/sektion-us-2026-09.json --write    # update verified flags
  python tools/scrape_sektion.py catalog/... --article 802.653.98 --dump    # show raw page text
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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


def search_url(article: str) -> str:
    """IKEA's search API returns structured product data, including itemMeasureReferenceText ("36x24x30 \"")."""
    return f"https://sik.search.blue.cdtapps.com/us/en/search-result-page?q={article.replace('.', '')}&types=PRODUCT&size=5"


def fetch_search(article: str) -> dict | None:
    """The product entry from the search API whose item number matches, or None."""
    import json as _json
    try:
        raw = fetch(search_url(article))
    except Exception:  # noqa: BLE001
        return None
    try:
        data = _json.loads(raw)
    except ValueError:
        return None
    want = article.replace(".", "")
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            item_no = str(node.get("itemNo") or node.get("itemNoGlobal") or node.get("id") or "").replace(".", "")
            if item_no == want and ("itemMeasureReferenceText" in node or "measurementText" in node):
                return node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


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
    args = ap.parse_args(argv)

    path = Path(args.catalog)
    data = json.loads(path.read_text())
    today = date.today().isoformat()
    changed = 0
    for item in data["items"]:
        art = item.get("article")
        if not art or (args.article and art != args.article):
            continue
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
