"""Minimal glTF 2.0 binary writer and reader for axis-aligned boxes.

Writes one mesh per box with positions, normals and indices, one node per
box named after it, materials by base color. Units are meters as glTF
requires; the scene is authored in millimeters and divided by 1000 here and
nowhere else. The reader exists so tests can prove the bounding box of every
node matches the file's millimeters within 1 mm.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from .scene import Box, Scene

MM_PER_M = 1000.0

# faces as (normal, 4 corner selectors over (x0|x1, y0|y1, z0|z1))
_FACES = [
    ((1, 0, 0), [(1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1)]),
    ((-1, 0, 0), [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)]),
    ((0, 1, 0), [(0, 1, 1), (1, 1, 1), (1, 1, 0), (0, 1, 0)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, 0, -1), [(1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0)]),
]


def _box_geometry(b: Box) -> tuple[list[float], list[float], list[int]]:
    mn = [v / MM_PER_M for v in b.min]
    mx = [v / MM_PER_M for v in b.max]
    pos: list[float] = []
    nrm: list[float] = []
    idx: list[int] = []
    for normal, corners in _FACES:
        base = len(pos) // 3
        for sx, sy, sz in corners:
            pos += [mx[0] if sx else mn[0], mx[1] if sy else mn[1], mx[2] if sz else mn[2]]
            nrm += list(map(float, normal))
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nrm, idx


def _pad4(b: bytes, fill: bytes = b"\x00") -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(scene: Scene, path: str | Path) -> Path:
    buf = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []
    materials: list[dict] = []
    mat_index: dict[str, int] = {}

    def add_view(data: bytes, target: int) -> int:
        while len(buf) % 4:
            buf.append(0)
        buffer_views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), "target": target})
        buf.extend(data)
        return len(buffer_views) - 1

    def material(name: str) -> int:
        if name not in mat_index:
            f = scene.materials[name]
            m = {"name": name, "pbrMetallicRoughness": {"baseColorFactor": [round(v, 4) for v in f.rgba], "metallicFactor": f.metallic, "roughnessFactor": f.roughness},
                 "extras": {"finish": f.name}}
            if f.alpha < 1:
                m["alphaMode"] = "BLEND"
            materials.append(m)
            mat_index[name] = len(materials) - 1
        return mat_index[name]

    for b in scene.boxes:
        pos, nrm, idx = _box_geometry(b)
        pv = add_view(struct.pack(f"<{len(pos)}f", *pos), 34962)
        nv = add_view(struct.pack(f"<{len(nrm)}f", *nrm), 34962)
        iv = add_view(struct.pack(f"<{len(idx)}H", *idx), 34963)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": len(pos) // 3, "type": "VEC3",
                          "min": [v / MM_PER_M for v in b.min], "max": [v / MM_PER_M for v in b.max]})
        accessors.append({"bufferView": nv, "componentType": 5126, "count": len(nrm) // 3, "type": "VEC3"})
        accessors.append({"bufferView": iv, "componentType": 5123, "count": len(idx), "type": "SCALAR"})
        a = len(accessors)
        meshes.append({"name": b.name, "primitives": [{"attributes": {"POSITION": a - 3, "NORMAL": a - 2}, "indices": a - 1, "material": material(b.material)}]})
        nodes.append({"name": b.name, "mesh": len(meshes) - 1, "extras": {"kind": b.kind, "size_mm": list(b.size), **{k: v for k, v in b.extras.items() if v is not None}}})

    cameras = []
    for c in scene.cameras:
        cameras.append({"name": c.name, "type": "perspective", "perspective": {"yfov": c.vfov_deg * 3.141592653589793 / 180, "aspectRatio": c.aspect, "znear": 0.05, "zfar": 100}})
        nodes.append({"name": f"camera:{c.name}", "camera": len(cameras) - 1,
                      "translation": [v / MM_PER_M for v in c.position],
                      "extras": {"target_m": [v / MM_PER_M for v in c.target]}})

    gltf = {
        "asset": {"version": "2.0", "generator": "millimeter-kitchen"},
        "scene": 0,
        "scenes": [{"name": scene.name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "cameras": cameras,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(buf)}],
    }
    json_bytes = _pad4(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    bin_bytes = _pad4(bytes(buf))
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", len(bin_bytes), 0x004E4942))
        fh.write(bin_bytes)
    return out


def read_glb_boxes(path: str | Path) -> dict[str, dict]:
    """Return {node name: {"min_mm", "max_mm", "size_mm", "extras", "material", "color"}} from position accessors."""
    data = Path(path).read_bytes()
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and version == 2 and length == len(data)
    jlen, jtype = struct.unpack_from("<II", data, 12)
    assert jtype == 0x4E4F534A
    gltf = json.loads(data[20:20 + jlen])
    blen, btype = struct.unpack_from("<II", data, 20 + jlen)
    assert btype == 0x004E4942
    bin_start = 20 + jlen + 8
    out = {}
    for node in gltf["nodes"]:
        if "mesh" not in node:
            continue
        prim = gltf["meshes"][node["mesh"]]["primitives"][0]
        acc = gltf["accessors"][prim["attributes"]["POSITION"]]
        bv = gltf["bufferViews"][acc["bufferView"]]
        off = bin_start + bv["byteOffset"]
        floats = struct.unpack_from(f"<{acc['count'] * 3}f", data, off)
        xs, ys, zs = floats[0::3], floats[1::3], floats[2::3]
        mn = [min(xs) * MM_PER_M, min(ys) * MM_PER_M, min(zs) * MM_PER_M]
        mx = [max(xs) * MM_PER_M, max(ys) * MM_PER_M, max(zs) * MM_PER_M]
        mat = gltf["materials"][prim["material"]]
        out[node["name"]] = {"min_mm": mn, "max_mm": mx, "size_mm": [b - a for a, b in zip(mn, mx)], "extras": node.get("extras", {}),
                             "material": mat["name"], "color": mat["pbrMetallicRoughness"]["baseColorFactor"]}
    return out
