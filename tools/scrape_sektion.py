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


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


_INCH = re.compile(r'(?P<label>Width|Depth|Height)\s*:?\s*(?P<num>\d+(?:\s\d+/\d+)?(?:\.\d+)?)\s*(?:"|&quot;|in\b)', re.I)


def parse_inches(html: str) -> dict[str, float]:
    """Find the first Width/Depth/Height in inches in the page text."""
    text = re.sub(r"<[^>]+>", " ", html)
    found: dict[str, float] = {}
    for m in _INCH.finditer(text):
        label = m.group("label").lower()
        if label in found:
            continue
        num = m.group("num").strip()
        if " " in num:
            whole, frac = num.split(" ", 1)
            value = float(Fraction(whole) + Fraction(frac))
        else:
            value = float(Fraction(num))
        found[label] = value
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
        if args.dump:
            i = html.find("Width")
            print(html[max(0, i - 400): i + 600])
            return 0
        got = parse_inches(html)
        if not got:
            print(f"{item['id']} {art}: no measurements found; run with --dump and fix the regex")
            continue
        mm = {k[0]: inch_to_mm(v) for k, v in got.items()}  # w/d/h
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
            item["source"] = url
            changed += 1
    if args.write and changed:
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"updated {changed} entries in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
