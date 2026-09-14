"""Render every finish's procedural texture to catalog/textures/<finish>.png.

Deterministic, so the PNGs are committed like the catalog; the exporter
reads them and only generates on the fly when one is missing.

Run:  python tools/build_textures.py            # all finishes with a texture spec
      python tools/build_textures.py --force    # regenerate even if present
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mmk.finishes import load_finishes  # noqa: E402
from mmk.textures import TEXTURE_DIR, texture_png  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    lib = load_finishes()
    TEXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for f in lib.finishes.values():
        if not f.texture:
            continue
        out = TEXTURE_DIR / f"{f.key}.png"
        if out.exists() and not args.force:
            print(f"{out.name}: present")
            continue
        out.write_bytes(texture_png(f.texture, cache=False))
        print(f"{out.name}: {out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
