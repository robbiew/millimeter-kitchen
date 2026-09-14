"""Minimal glTF 2.0 binary writer and reader for axis-aligned boxes.

Writes one mesh per box with positions, normals and indices, one node per
box named after it, materials by base color. Units are meters as glTF
requires; the scene is authored in millimeters and divided by 1000 here and
nowhere else. The reader exists so tests can prove the bounding box of every
node matches the file's millimeters within 1 mm.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from .scene import Box, Scene
from .textures import texture_png

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


def _box_geometry(b: Box, uv_scale_mm: float | None = None, grain: str = "vertical") -> tuple[list[float], list[float], list[int], list[float]]:
    """Positions, normals, indices and planar UVs. UVs are in the box's frame in units of uv_scale_mm,
    so a texture tile covers a real-world square; `grain` = horizontal swaps the axes so the pattern's
    vertical axis runs along the wall instead of up."""
    mn = [v / MM_PER_M for v in b.min]
    mx = [v / MM_PER_M for v in b.max]
    pos: list[float] = []
    nrm: list[float] = []
    idx: list[int] = []
    uvs: list[float] = []
    k = (1.0 / uv_scale_mm) if uv_scale_mm else 0.0
    for normal, corners in _FACES:
        base = len(pos) // 3
        for sx, sy, sz in corners:
            x, y, z = (b.max[0] if sx else b.min[0]), (b.max[1] if sy else b.min[1]), (b.max[2] if sz else b.min[2])
            pos += [x / MM_PER_M, y / MM_PER_M, z / MM_PER_M]
            nrm += list(map(float, normal))
            if normal[0]:      # side faces: along the wall's depth and up
                a, c = z, y
            elif normal[1]:    # top/bottom: along the wall and into the room
                a, c = x, z
            else:              # front/back: along the wall and up
                a, c = x, y
            u, v = (a * k, -c * k) if grain != "horizontal" else (-c * k, a * k)
            uvs += [u, v]
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nrm, idx, uvs


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
    images: list[dict] = []
    textures: list[dict] = []
    samplers: list[dict] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]

    def add_view(data: bytes, target: int) -> int:
        while len(buf) % 4:
            buf.append(0)
        buffer_views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), "target": target})
        buf.extend(data)
        return len(buffer_views) - 1

    def material(name: str) -> int:
        if name not in mat_index:
            f = scene.materials[name]
            m = {"name": name, "pbrMetallicRoughness": {"baseColorFactor": [round(v, 5) for v in f.linear_rgba], "metallicFactor": f.metallic, "roughnessFactor": f.roughness},
                 "extras": {"finish": f.name, "srgb": [round(v, 4) for v in f.rgba]}}
            if f.alpha < 1:
                m["alphaMode"] = "BLEND"
            if f.texture:
                data = texture_png(f.texture, f.key)
                iv = add_view(data, 0)
                buffer_views[iv].pop("target", None)
                images.append({"bufferView": iv, "mimeType": "image/png", "name": f.key})
                textures.append({"sampler": 0, "source": len(images) - 1})
                m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(textures) - 1, "texCoord": 0}
                m["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, f.alpha]  # the image carries the colour
                m["extras"]["texture_scale_mm"] = f.texture.get("scale_mm")
            materials.append(m)
            mat_index[name] = len(materials) - 1
        return mat_index[name]

    for b in scene.boxes:
        fin = scene.materials[b.material]
        tex = fin.texture or {}
        pos, nrm, idx, uvs = _box_geometry(b, tex.get("scale_mm"), tex.get("grain", "vertical"))
        pv = add_view(struct.pack(f"<{len(pos)}f", *pos), 34962)
        nv = add_view(struct.pack(f"<{len(nrm)}f", *nrm), 34962)
        tv = add_view(struct.pack(f"<{len(uvs)}f", *uvs), 34962)
        iv = add_view(struct.pack(f"<{len(idx)}H", *idx), 34963)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": len(pos) // 3, "type": "VEC3",
                          "min": [v / MM_PER_M for v in b.min], "max": [v / MM_PER_M for v in b.max]})
        accessors.append({"bufferView": nv, "componentType": 5126, "count": len(nrm) // 3, "type": "VEC3"})
        accessors.append({"bufferView": tv, "componentType": 5126, "count": len(uvs) // 2, "type": "VEC2"})
        accessors.append({"bufferView": iv, "componentType": 5123, "count": len(idx), "type": "SCALAR"})
        a = len(accessors)
        meshes.append({"name": b.name, "primitives": [{"attributes": {"POSITION": a - 4, "NORMAL": a - 3, "TEXCOORD_0": a - 2}, "indices": a - 1, "material": material(b.material)}]})
        node = {"name": b.name, "mesh": len(meshes) - 1, "extras": {"kind": b.kind, "size_mm": list(b.size), **{k: v for k, v in b.extras.items() if v is not None}}}
        if any(b.origin):
            node["translation"] = [round(v / MM_PER_M, 6) for v in b.origin]
        if abs(b.yaw) > 1e-9:
            node["rotation"] = [0.0, round(math.sin(b.yaw / 2), 9), 0.0, round(math.cos(b.yaw / 2), 9)]  # quaternion about +Y
        nodes.append(node)

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
        **({"images": images, "textures": textures, "samplers": samplers} if images else {}),
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
    """Return {node name: {"min_mm", "max_mm" (world AABB), "size_mm" (the box's own size), "extras", "material", "color", "yaw_deg"}}."""
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
        lmn = [min(xs), min(ys), min(zs)]
        lmx = [max(xs), max(ys), max(zs)]
        # apply the node's rotation about Y and translation to get a world-space bounding box
        t = node.get("translation", [0.0, 0.0, 0.0])
        qy, qw = (node.get("rotation") or [0, 0, 0, 1])[1], (node.get("rotation") or [0, 0, 0, 1])[3]
        yaw = 2 * math.atan2(qy, qw)
        c, sn = math.cos(yaw), math.sin(yaw)
        pts = [(t[0] + x * c + z * sn, t[1] + y, t[2] - x * sn + z * c) for x in (lmn[0], lmx[0]) for y in (lmn[1], lmx[1]) for z in (lmn[2], lmx[2])]
        mn = [min(p[i] for p in pts) * MM_PER_M for i in range(3)]
        mx = [max(p[i] for p in pts) * MM_PER_M for i in range(3)]
        mat = gltf["materials"][prim["material"]]
        out[node["name"]] = {"min_mm": mn, "max_mm": mx, "size_mm": [(b - a) * MM_PER_M for a, b in zip(lmn, lmx)], "extras": node.get("extras", {}),
                             "material": mat["name"], "color": mat["pbrMetallicRoughness"]["baseColorFactor"],
                             "textured": "baseColorTexture" in mat["pbrMetallicRoughness"],
                             "yaw_deg": math.degrees(yaw)}
    return out
