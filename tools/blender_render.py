"""Render every camera in a Millimeter Kitchen scene.glb from inside Blender.

Run by `mmk render`; can also be run by hand:

    blender --background --python tools/blender_render.py -- out/scene.glb out/cameras.json out/ [--engine EEVEE|CYCLES] [--size 1600x1000] [--samples 64]

Imports the glTF the CLI wrote (Blender's importer converts glTF Y-up to
Blender Z-up), builds one camera per entry in cameras.json, adds a sun and a
soft fill, and writes out/render-<camera>.png. Nothing is modelled here; the
geometry is whatever kitchen.json produced.

Written against Blender 4.x bpy. Not executed in the environment that wrote
it; the first run on a real machine will tell.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector


def yup_to_blender(v):
    """glTF (x, y, z) Y-up → Blender (x, -z, y) Z-up. Same mapping the importer applies."""
    x, y, z = v
    return Vector((x, -z, y))


def look_at(obj, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def world_bounds(objs):
    """Axis-aligned bounds of mesh objects in world space, as (min Vector, max Vector)."""
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def swap_in_models(scene, mapping: dict) -> None:
    """Replace each mapped box with the IKEA model for its article.

    The model is imported once per article and instanced per box. It is
    rotated like the box and moved so its bounding box sits on the box's
    bounding box (same floor, same back wall, same left edge); it is NEVER
    scaled, so a model that disagrees with the catalog shows the disagreement
    instead of hiding it. The box itself is hidden from the render.
    """
    imported: dict[str, list] = {}
    for name, m in mapping.items():
        box = scene.objects.get(name)
        if box is None:
            print(f"models: no object {name!r} in the scene; skipped")
            continue
        art = m["article"]
        if art not in imported:
            before = set(scene.objects)
            try:
                bpy.ops.import_scene.gltf(filepath=m["glb"])
            except Exception as e:  # a broken download is a warning, not a failed render
                print(f"models: {art}: import failed: {e}")
                imported[art] = []
                continue
            new = [o for o in scene.objects if o not in before]
            for o in new:
                o.hide_render = True
                o.hide_viewport = True
            imported[art] = new
        src = imported[art]
        if not src:
            continue
        # duplicate the template objects, group them under an empty carrying the box's rotation
        root = bpy.data.objects.new(f"{name}/ikea", None)
        scene.collection.objects.link(root)
        copies = []
        for o in src:
            c = o.copy()
            if o.data:
                c.data = o.data
            c.hide_render = False
            c.hide_viewport = False
            scene.collection.objects.link(c)
            copies.append(c)
        for c in copies:
            if c.parent in src:
                c.parent = copies[src.index(c.parent)]
            else:
                c.parent = root
        root.rotation_euler = box.matrix_world.to_euler()
        bpy.context.view_layer.update()
        blo, bhi = world_bounds([box])
        mlo, mhi = world_bounds(copies)
        rotated = ""
        # IKEA's wall-frame meshes are authored with a different up axis: the model's height lands on the
        # box's depth. If swapping height and depth fits the box much better, stand the model up.
        bx = [(b - a) for a, b in zip(blo, bhi)]
        mx = [(b - a) for a, b in zip(mlo, mhi)]
        local_box = box.matrix_world.to_quaternion().inverted() @ Vector(bx)      # box size in the box's own frame
        local_model = root.matrix_world.to_quaternion().inverted() @ Vector(mx)   # model size in that same frame
        lb, lm = [abs(v) for v in local_box], [abs(v) for v in local_model]
        as_is = abs(lm[1] - lb[1]) + abs(lm[2] - lb[2])
        swapped = abs(lm[2] - lb[1]) + abs(lm[1] - lb[2])
        if swapped + 0.01 < as_is:
            root.rotation_euler = (box.matrix_world.to_quaternion() @ Quaternion((1, 0, 0), math.radians(90))).to_euler()
            bpy.context.view_layer.update()
            mlo, mhi = world_bounds(copies)
            rotated = "; stood up (mesh was on its back)"
        root.location = root.location + (blo - mlo)
        bpy.context.view_layer.update()
        box.hide_render = True
        box.hide_viewport = True
        size_box = [(b - a) * 1000 for a, b in zip(blo, bhi)]
        size_model = [(b - a) * 1000 for a, b in zip(mlo, mhi)]
        dev = max(abs(a - b) for a, b in zip(size_box, size_model))
        note = "" if dev <= 3 else f"  (differs from the box by up to {dev:.0f} mm; not scaled)"
        print(f"models: {name} <- {art} {'x'.join(f'{v:.0f}' for v in size_model)}{note}{rotated}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("cameras")
    ap.add_argument("out")
    ap.add_argument("--engine", default="EEVEE", choices=["EEVEE", "CYCLES"])
    ap.add_argument("--size", default="1600x1000")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--models", help="ikea-models.json from `mmk render --ikea-models`: swap boxes for IKEA's own meshes")
    args = ap.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.glb).resolve()))
    scene = bpy.context.scene

    # the importer creates camera objects from glTF cameras; we rebuild ours to aim them
    for o in [o for o in scene.objects if o.type == "CAMERA"]:
        bpy.data.objects.remove(o, do_unlink=True)

    if args.models:
        swap_in_models(scene, json.loads(Path(args.models).read_text()))

    cams = json.loads(Path(args.cameras).read_text())
    w, h = (int(x) for x in args.size.lower().split("x"))
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    engine = {"EEVEE": "BLENDER_EEVEE_NEXT", "CYCLES": "CYCLES"}[args.engine]
    try:
        scene.render.engine = engine
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE" if args.engine == "EEVEE" else "CYCLES"
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = True
    elif hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = args.samples

    world = bpy.data.worlds.new("World")
    scene.world = world
    if bpy.app.version < (5, 0, 0):
        world.use_nodes = True  # default from 5.0 on; the property is slated for removal in 6.0
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.9, 0.9, 0.9, 1)
        bg.inputs[1].default_value = 0.6

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(-20), math.radians(35))
    scene.collection.objects.link(sun)
    fill_data = bpy.data.lights.new("Fill", "AREA")
    fill_data.energy = 400
    fill_data.size = 3
    fill = bpy.data.objects.new("Fill", fill_data)
    scene.collection.objects.link(fill)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for c in cams:
        cam_data = bpy.data.cameras.new(c["name"])
        cam_data.sensor_fit = "VERTICAL"
        cam_data.sensor_height = 24.0
        cam_data.lens = (cam_data.sensor_height / 2) / math.tan(math.radians(c["vfov_deg"]) / 2)
        cam_data.clip_start, cam_data.clip_end = 0.05, 100
        cam = bpy.data.objects.new(c["name"], cam_data)
        cam.location = yup_to_blender([v / 1000 for v in c["position"]])
        scene.collection.objects.link(cam)
        look_at(cam, yup_to_blender([v / 1000 for v in c["target"]]))
        fill.location = cam.location + Vector((0, 0, 0.8))
        scene.camera = cam
        scene.render.filepath = str(out / f"render-{c['name']}.png")
        bpy.ops.render.render(write_still=True)
        written.append(scene.render.filepath)
    print("\n".join(written))
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sys.exit(main(argv))
