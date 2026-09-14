"""Procedural textures for renders, generated in pure Python and embedded in the glTF.

A texture tile represents `scale_mm` of surface on each side, so grain, tile
and grout read at real size. Everything is deterministic: the same finish
gives the same bytes every export. Kinds:

  wood   grain along the image's vertical axis (see finishes' `grain`)
  plank  wood with plank seams (floors, butcher block)
  tile   rectangular tiles with grout in a running bond or stacked
  stone  quartz-like veining over a base colour

Colors are sRGB 0..1 and are written to the PNG as-is; glTF treats base
color textures as sRGB, so no linearisation here (unlike baseColorFactor).
"""

from __future__ import annotations

import math
import struct
import zlib
from functools import lru_cache
from pathlib import Path

TEXTURE_DIR = Path(__file__).resolve().parents[2] / "catalog" / "textures"

Color = tuple[float, float, float]


# ---------------------------------------------------------------- helpers

def _clamp(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _mix(a: Color, b: Color, t: float) -> Color:
    t = _clamp(t)
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _hash(x: int, y: int, seed: int) -> float:
    """Deterministic pseudo-random in [0, 1) for a lattice point."""
    n = (x * 374761393 + y * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFF) / 0x1000000


def _noise(x: float, y: float, period: int, seed: int, period_y: int | None = None) -> float:
    """Periodic value noise with smoothstep. The lattice wraps every `period`
    cells in x and `period_y` (default: the same) cells in y, so a texture can
    be sampled with many cells across the grain and few along it and still tile."""
    py = period if period_y is None else period_y
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x - xi, y - yi
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    x0, x1 = xi % period, (xi + 1) % period
    y0, y1 = yi % py, (yi + 1) % py
    a = _hash(x0, y0, seed) + (_hash(x1, y0, seed) - _hash(x0, y0, seed)) * sx
    b = _hash(x0, y1, seed) + (_hash(x1, y1, seed) - _hash(x0, y1, seed)) * sx
    return a + (b - a) * sy


def _fbm(x: float, y: float, period: int, seed: int, octaves: int = 3, period_y: int | None = None) -> float:
    v, amp, freq, total = 0.0, 1.0, 1.0, 0.0
    py = period if period_y is None else period_y
    for _ in range(octaves):
        v += amp * _noise(x * freq, y * freq, int(period * freq), seed, int(py * freq))
        total += amp
        amp *= 0.5
        freq *= 2
    return v / total


def png(width: int, height: int, rgb: bytes) -> bytes:
    """Encode 8-bit RGB rows as a PNG."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _to_bytes(pixels: list[Color]) -> bytes:
    out = bytearray(len(pixels) * 3)
    i = 0
    for r, g, b in pixels:
        out[i] = int(_clamp(r) * 255 + 0.5)
        out[i + 1] = int(_clamp(g) * 255 + 0.5)
        out[i + 2] = int(_clamp(b) * 255 + 0.5)
        i += 3
    return bytes(out)


# ---------------------------------------------------------------- kinds

def wood(size: int, base: Color, dark: Color, light: Color, seed: int = 1, rings: float = 14.0, planks: int = 0, plank_gap: float = 0.006, figure: float = 0.08) -> list[Color]:
    """Straight-grained wood. Grain runs along V (image vertical): the growth
    rings are stripes across U that wander slowly along V (`figure` is how much,
    in ring widths), and the pore texture is sampled with many lattice cells
    across the grain and few along it so it streaks instead of swirling.
    With `planks`, the image is that many boards across, each with its own
    grain offset and a dark seam between them."""
    px: list[Color] = []
    across, along = 48, 3        # lattice cells across vs along the grain for the pore streaks
    for y in range(size):
        v = y / size
        for x in range(size):
            u = x / size
            uu, vv = u, v
            if planks:
                board = math.floor(u * planks)
                uu = u + _hash(board, 1, seed)          # each board is a different slice of the log
                vv = v + _hash(board, 2, seed)
            # slow wander of the ring lines, a few cells across and along, gives the cathedral figure;
            # a second, slower field varies the ring spacing so the stripes are not evenly spaced
            drift = _fbm(uu * 4, vv * 2, 4, seed, 3, period_y=2) - 0.5
            spacing = _fbm(uu * 2, vv * 1, 2, seed + 3, 2, period_y=1) - 0.5
            phase = (uu + figure * drift) * rings + 1.5 * spacing
            band = 0.5 + 0.5 * math.sin(phase * math.tau)
            band = band * band * band                     # thin latewood lines, wide earlywood between
            streak = _fbm(uu * across, vv * along, across, seed + 7, 3, period_y=along) - 0.5
            t = _clamp(0.35 * band + 0.8 * streak + 0.5)
            c = _mix(_mix(dark, base, t), light, max(0.0, streak) * 0.45)
            if planks:
                pu = (u * planks) % 1.0
                if pu < plank_gap or pu > 1 - plank_gap:
                    c = _mix(c, dark, 0.7)
            px.append(c)
    return px


def tile(size: int, tile_w: float, tile_h: float, grout_w: float, base: Color, grout: Color, seed: int = 3, bond: str = "running", variation: float = 0.05) -> list[Color]:
    """Tiles in image units (0..1 = scale_mm). Running bond offsets every other row by half a tile."""
    px: list[Color] = []
    for y in range(size):
        v = y / size
        row = math.floor(v / tile_h)
        for x in range(size):
            u = x / size
            off = 0.5 * tile_w if (bond == "running" and row % 2) else 0.0
            col = math.floor((u + off) / tile_w)
            gu = ((u + off) % tile_w) < grout_w or ((u + off) % tile_w) > tile_w - grout_w
            gv = (v % tile_h) < grout_w or (v % tile_h) > tile_h - grout_w
            if gu or gv:
                px.append(grout)
            else:
                shade = (_hash(col, row, seed) - 0.5) * 2 * variation
                gloss = 0.03 * math.sin(((u + off) % tile_w) / tile_w * math.pi)
                px.append((base[0] + shade + gloss, base[1] + shade + gloss, base[2] + shade + gloss))
    return px


def stone(size: int, base: Color, vein: Color, seed: int = 5, strength: float = 0.5) -> list[Color]:
    px: list[Color] = []
    period = 4
    for y in range(size):
        v = y / size
        for x in range(size):
            u = x / size
            n = _fbm(u * period, v * period, period, seed, 4)
            ridge = 1.0 - abs(2 * n - 1)          # thin bright ridges = veins
            veins = max(0.0, ridge - 0.75) / 0.25
            speck = (_fbm(u * period * 8, v * period * 8, period * 8, seed + 11, 2) - 0.5) * 0.06
            c = _mix(base, vein, veins * strength)
            px.append((c[0] + speck, c[1] + speck, c[2] + speck))
    return px


# ---------------------------------------------------------------- registry

def _rgb(hex_: str) -> Color:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


@lru_cache(maxsize=None)
def render_texture(spec_key: str) -> bytes:
    """PNG bytes for a texture spec serialised as JSON (cached per process)."""
    import json

    spec = json.loads(spec_key)
    kind = spec["kind"]
    size = int(spec.get("size", 384))
    if kind == "wood":
        px = wood(size, _rgb(spec["base"]), _rgb(spec["dark"]), _rgb(spec["light"]), spec.get("seed", 1), spec.get("rings", 14.0), figure=spec.get("figure", 0.08))
    elif kind == "plank":
        px = wood(size, _rgb(spec["base"]), _rgb(spec["dark"]), _rgb(spec["light"]), spec.get("seed", 2), spec.get("rings", 10.0), planks=int(spec.get("planks", 6)), figure=spec.get("figure", 0.08))
    elif kind == "tile":
        s = spec["scale_mm"]
        px = tile(size, spec["tile_w_mm"] / s, spec["tile_h_mm"] / s, spec.get("grout_mm", 3) / s, _rgb(spec["base"]), _rgb(spec["grout"]), spec.get("seed", 3), spec.get("bond", "running"), spec.get("variation", 0.05))
    elif kind == "stone":
        px = stone(size, _rgb(spec["base"]), _rgb(spec["vein"]), spec.get("seed", 5), spec.get("strength", 0.5))
    else:
        raise ValueError(f"unknown texture kind {kind}")
    return png(size, size, _to_bytes(px))


def texture_png(spec: dict, key: str | None = None, cache: bool = True) -> bytes:
    """PNG bytes for a finish's texture spec: the committed file under catalog/textures/ when present, else generated."""
    import json

    if cache and key:
        path = TEXTURE_DIR / f"{key}.png"
        if path.exists():
            return path.read_bytes()
    return render_texture(json.dumps(spec, sort_keys=True))
