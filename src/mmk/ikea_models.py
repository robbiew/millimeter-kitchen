"""IKEA's own 3D models, for render detail and a dimension cross-check.

ikea.com serves a glTF model for many articles through its "Rotera" service,
the same one behind the site's "View in 3D" button. This module fetches
those models into a cache OUTSIDE the repository, reads their bounding box,
and maps them onto scene nodes so `tools/blender_render.py` can swap a box
for the real mesh.

Rules that keep this honest:

- The models are IKEA's copyright. They are cached under the user's cache
  directory (or MMK_IKEA_CACHE), never under the repo, and never committed.
- They are pictures only. A model's bounding box is compared to the catalog
  as a check that REPORTS a mismatch; nothing here writes a dimension.
- The scene stays the authority on placement: a model is aligned to the box
  it replaces and is never scaled to fit.

Endpoints (from https://github.com/shish/blender-ikea-browser, which found
that the site's own client id is required):

    GET https://web-api.ikea.com/{cc}/{lang}/rotera/data/exists/{article}/
    GET https://web-api.ikea.com/{cc}/{lang}/rotera/data/model/{article}/  -> {"modelUrl": ...}
"""

from __future__ import annotations

import json
import math
import os
import platform
import struct
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .catalog import Catalog, Item
from .scene import Scene

CLIENT_ID = "4863e7d2-1428-4324-890b-ae5dede24fc6"   # ikea.com's public web client id
USER_AGENT = "millimeter-kitchen (https://github.com/robbiew/millimeter-kitchen)"
MM_PER_M = 1000.0

Fetcher = Callable[[str, dict[str, str]], bytes]


def default_cache_dir(env: dict[str, str] | None = None, system: str | None = None) -> Path:
    """MMK_IKEA_CACHE, else the platform cache directory. Never inside the repo."""
    env = os.environ if env is None else env
    if env.get("MMK_IKEA_CACHE"):
        return Path(os.path.expanduser(env["MMK_IKEA_CACHE"]))
    system = system or platform.system()
    if system == "Darwin":
        base = Path("~/Library/Caches").expanduser()
    elif system == "Windows":
        base = Path(env.get("LOCALAPPDATA", "~/AppData/Local")).expanduser()
    else:
        base = Path(env.get("XDG_CACHE_HOME", "~/.cache")).expanduser()
    return base / "millimeter-kitchen" / "ikea-models"


def normalize_article(article: str) -> str:
    """'802.653.98' -> '80265398'. Raises ValueError for anything but 8 digits."""
    digits = "".join(ch for ch in article if ch.isdigit())
    if len(digits) != 8:
        raise ValueError(f"not an IKEA article number: {article!r}")
    return digits


def format_article(digits: str) -> str:
    d = normalize_article(digits)
    return f"{d[:3]}.{d[3:6]}.{d[6:]}"


def _urllib_fetch(url: str, headers: dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


class ModelClient:
    """Fetches and caches Rotera models. `fetch` is injectable for tests."""

    def __init__(self, country: str = "us", language: str = "en", cache: Path | None = None, fetch: Fetcher | None = None):
        self.country, self.language = country, language
        self.cache = Path(cache) if cache else default_cache_dir()
        self._fetch = fetch or _urllib_fetch

    def _api(self, path: str) -> dict:
        url = f"https://web-api.ikea.com/{self.country}/{self.language}/rotera/data/{path}"
        return json.loads(self._fetch(url, {"X-Client-Id": CLIENT_ID, "User-Agent": USER_AGENT, "Accept": "application/json"}))

    def paths(self, article: str) -> tuple[Path, Path]:
        d = self.cache / normalize_article(article)
        return d / "model.glb", d / "model.json"

    def cached(self, article: str) -> Path | None:
        glb, _ = self.paths(article)
        return glb if glb.exists() else None

    def exists(self, article: str) -> bool:
        if self.cached(article):
            return True
        return bool(self._api(f"exists/{normalize_article(article)}/").get("exists"))

    def info(self, article: str) -> dict:
        return self._api(f"model/{normalize_article(article)}/")

    def fetch_model(self, article: str, refresh: bool = False) -> Path | None:
        """Download the model into the cache (once). None when IKEA has no model for the article."""
        glb, meta = self.paths(article)
        if glb.exists() and not refresh:
            return glb
        if not self.exists(article):
            return None
        data = self.info(article)
        url = data.get("modelUrl")
        if not url:
            return None
        glb.parent.mkdir(parents=True, exist_ok=True)
        glb.write_bytes(self._fetch(url, {"User-Agent": USER_AGENT}))
        meta.write_text(json.dumps({"article": format_article(article), "country": self.country, "language": self.language, "source": url, "rotera": data}, indent=2) + "\n")
        return glb


# ------------------------------------------------------------- bounding box

def _mat_mul(a: list[float], b: list[float]) -> list[float]:
    """Column-major 4x4 product a*b, as glTF stores matrices."""
    out = [0.0] * 16
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return out


def _node_matrix(node: dict) -> list[float]:
    if "matrix" in node:
        return list(node["matrix"])
    t = node.get("translation", [0.0, 0.0, 0.0])
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    sx, sy, sz = node.get("scale", [1.0, 1.0, 1.0])
    # rotation matrix from the unit quaternion, column-major, then scale columns and set translation
    r = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0.0,
         2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0.0,
         2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0.0,
         t[0], t[1], t[2], 1.0]
    for c, s in enumerate((sx, sy, sz)):
        for i in range(3):
            r[c * 4 + i] *= s
    return r


def _apply(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def read_gltf_json(path: str | Path) -> dict:
    data = Path(path).read_bytes()
    if data[:4] == b"glTF":
        jlen = struct.unpack_from("<I", data, 12)[0]
        return json.loads(data[20:20 + jlen])
    return json.loads(data)


def glb_bounds(path: str | Path) -> tuple[list[float], list[float]]:
    """World-space AABB of every mesh in the file's default scene, in millimeters.
    Uses the POSITION accessors' min/max (required by the spec) transformed
    through the node hierarchy, so no vertex data is decoded."""
    g = read_gltf_json(path)
    nodes = g.get("nodes", [])
    scene = g["scenes"][g.get("scene", 0)] if g.get("scenes") else {"nodes": list(range(len(nodes)))}
    lo = [math.inf] * 3
    hi = [-math.inf] * 3

    def visit(idx: int, parent: list[float]) -> None:
        node = nodes[idx]
        m = _mat_mul(parent, _node_matrix(node))
        if "mesh" in node:
            for prim in g["meshes"][node["mesh"]]["primitives"]:
                acc = g["accessors"][prim["attributes"]["POSITION"]]
                if "min" not in acc or "max" not in acc:
                    continue
                for x in (acc["min"][0], acc["max"][0]):
                    for y in (acc["min"][1], acc["max"][1]):
                        for z in (acc["min"][2], acc["max"][2]):
                            p = _apply(m, (x, y, z))
                            for i in range(3):
                                lo[i] = min(lo[i], p[i])
                                hi[i] = max(hi[i], p[i])
        for ch in node.get("children", []):
            visit(ch, m)

    identity = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    for root in scene.get("nodes", []):
        visit(root, identity)
    if lo[0] is math.inf:
        raise ValueError(f"{path}: no positioned meshes")
    return [v * MM_PER_M for v in lo], [v * MM_PER_M for v in hi]


def glb_size(path: str | Path) -> tuple[float, float, float]:
    lo, hi = glb_bounds(path)
    return (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


# ----------------------------------------------------------------- checking

@dataclass(frozen=True)
class ModelCheck:
    item_id: str
    article: str
    model: Path | None
    model_size: tuple[float, float, float] | None   # (w, h, d) mm, glTF Y up
    catalog_size: tuple[int | None, int | None, int | None]
    deltas: tuple[float | None, float | None, float | None]
    tolerance: float

    @property
    def ok(self) -> bool:
        return self.model is not None and all(d is None or abs(d) <= self.tolerance for d in self.deltas)

    def describe(self) -> str:
        if self.model is None:
            return f"{self.item_id} ({self.article}): no IKEA model"
        w, h, d = (round(v) for v in self.model_size)
        cw, ch, cd = self.catalog_size
        dev = ", ".join(f"{n}{'+' if x > 0 else ''}{x:.0f}" for n, x in zip("whd", self.deltas) if x is not None and abs(x) > self.tolerance)
        return f"{self.item_id} ({self.article}): model {w}x{h}x{d} vs catalog {cw}x{ch}x{cd}" + (f"  MISMATCH {dev}" if dev else "  ok")


def check_item(item: Item, client: ModelClient, tolerance: float = 3.0, fetch: bool = False) -> ModelCheck:
    """Compare the model's bounding box with the catalog. Reads only; the catalog is never changed."""
    art = item.article or ""
    glb = client.fetch_model(art) if fetch else client.cached(art)
    if not glb:
        return ModelCheck(item.id, art, None, None, (item.w, item.h, item.d), (None, None, None), tolerance)
    size = glb_size(glb)
    cat = (item.w, item.h, item.d)
    # IKEA's wall-frame meshes are authored with a different up axis (height along depth); measure them stood up
    if cat[1] is not None and cat[2] is not None:
        as_is = abs(size[1] - cat[1]) + abs(size[2] - cat[2])
        swapped = abs(size[2] - cat[1]) + abs(size[1] - cat[2])
        if swapped + 0.5 < as_is:
            size = (size[0], size[2], size[1])
    deltas = tuple(None if c is None else s - c for s, c in zip(size, cat))
    return ModelCheck(item.id, art, glb, size, cat, deltas, tolerance)  # type: ignore[arg-type]


# ---------------------------------------------------------------- scene map

def scene_articles(scene: Scene, catalog: Catalog) -> dict[str, str]:
    """{node name: article} for every box that stands for a catalog item with an article number."""
    out: dict[str, str] = {}
    for b in scene.boxes:
        item_id = b.extras.get("front") if b.kind == "front" else b.extras.get("id")
        if not item_id:
            continue
        item = catalog.get(item_id)
        if item and item.article:
            out[b.name] = item.article
    return out


def model_map(scene: Scene, catalog: Catalog, client: ModelClient, fetch: bool = False) -> dict[str, dict]:
    """{node name: {"article", "glb", "size_mm"}} for nodes whose article has a (cached) model.
    Written next to scene.glb as ikea-models.json for the Blender script."""
    out: dict[str, dict] = {}
    by_article: dict[str, Path | None] = {}
    for name, art in scene_articles(scene, catalog).items():
        if art not in by_article:
            try:
                by_article[art] = client.fetch_model(art) if fetch else client.cached(art)
            except Exception as e:  # network trouble is a warning, never a failed export
                print(f"ikea model {art}: {e}", file=sys.stderr)
                by_article[art] = None
        glb = by_article[art]
        if glb:
            out[name] = {"article": art, "glb": str(glb), "size_mm": [round(v, 1) for v in glb_size(glb)]}
    return out
