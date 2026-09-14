"""Procedural textures: deterministic PNGs, embedded in the glTF with real-scale UVs."""

import json
import struct
import zlib

import pytest

from mmk.finishes import load_finishes
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.scene import build_scene
from mmk.textures import TEXTURE_DIR, png, render_texture, texture_png
from tests.conftest import EXAMPLES


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def test_png_encoder_roundtrip():
    data = png(2, 1, bytes([255, 0, 0, 0, 0, 255]))
    assert _png_size(data) == (2, 1)
    idat = data[data.index(b"IDAT") + 4:]
    raw = zlib.decompress(idat[: struct.unpack(">I", data[data.index(b"IDAT") - 4: data.index(b"IDAT")])[0]])
    assert raw == b"\x00" + bytes([255, 0, 0, 0, 0, 255])


def test_textures_are_deterministic_and_committed():
    lib = load_finishes()
    textured = [f for f in lib.finishes.values() if f.texture]
    assert {f.key for f in textured} >= {"voxtorp-walnut", "oak-natural", "quartz-white", "tile-white-subway"}
    for f in textured:
        path = TEXTURE_DIR / f"{f.key}.png"
        assert path.exists(), f"run tools/build_textures.py ({f.key})"
        assert _png_size(path.read_bytes())[0] >= 256
    spec = json.dumps({"kind": "tile", "scale_mm": 456, "tile_w_mm": 152, "tile_h_mm": 76, "grout_mm": 3, "base": "#F3F3F0", "grout": "#C9C9C4", "size": 64}, sort_keys=True)
    assert render_texture(spec) == render_texture(spec)


def test_subway_tile_has_grout_at_real_size():
    spec = {"kind": "tile", "scale_mm": 456, "tile_w_mm": 152, "tile_h_mm": 76, "grout_mm": 3, "base": "#F3F3F0", "grout": "#000000", "size": 456, "variation": 0}
    data = render_texture(json.dumps(spec, sort_keys=True))
    idat_len = struct.unpack(">I", data[data.index(b"IDAT") - 4: data.index(b"IDAT")])[0]
    raw = zlib.decompress(data[data.index(b"IDAT") + 4: data.index(b"IDAT") + 4 + idat_len])
    row = lambda y: raw[y * (456 * 3 + 1) + 1: (y + 1) * (456 * 3 + 1)]
    # row 0 is a horizontal grout line (black); row 40 is mid-tile and mostly white with grout every 152 px
    assert row(0)[:3] == b"\x00\x00\x00"
    mid = row(40)
    assert mid[100 * 3] > 200 and mid[152 * 3 + 3] == 0     # inside tile 1, then the vertical grout at 152 mm


def test_glb_embeds_textures_with_uvs(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    path = write_glb(build_scene(k), tmp_path / "s.glb")
    data = path.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + jlen])
    assert gltf["images"] and gltf["textures"] and gltf["samplers"][0]["wrapS"] == 10497
    names = {i["name"] for i in gltf["images"]}
    assert {"voxtorp-walnut", "oak-natural", "quartz-white", "tile-white-subway"} <= names
    mats = {m["name"]: m for m in gltf["materials"]}
    assert "baseColorTexture" in mats["voxtorp-walnut"]["pbrMetallicRoughness"]
    assert mats["voxtorp-walnut"]["pbrMetallicRoughness"]["baseColorFactor"][:3] == [1.0, 1.0, 1.0]
    assert "baseColorTexture" not in mats["sektion-white"]["pbrMetallicRoughness"]   # flat finishes stay flat
    prim = gltf["meshes"][0]["primitives"][0]
    assert "TEXCOORD_0" in prim["attributes"]
    boxes = read_glb_boxes(path)
    assert boxes["N-base-30/door1"]["textured"] and not boxes["N-base-30"]["textured"]
    assert [round(v) for v in boxes["N-base-30/door1"]["size_mm"]][1] == 756   # 762 mm door minus 3 mm reveal top and bottom; geometry untouched by UVs


def test_texture_png_prefers_the_committed_file():
    lib = load_finishes()
    f = lib["voxtorp-walnut"]
    assert texture_png(f.texture, f.key) == (TEXTURE_DIR / "voxtorp-walnut.png").read_bytes()
