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
from mathutils import Vector


def yup_to_blender(v):
    """glTF (x, y, z) Y-up → Blender (x, -z, y) Z-up. Same mapping the importer applies."""
    x, y, z = v
    return Vector((x, -z, y))


def look_at(obj, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("cameras")
    ap.add_argument("out")
    ap.add_argument("--engine", default="EEVEE", choices=["EEVEE", "CYCLES"])
    ap.add_argument("--size", default="1600x1000")
    ap.add_argument("--samples", type=int, default=64)
    args = ap.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.glb).resolve()))
    scene = bpy.context.scene

    # the importer creates camera objects from glTF cameras; we rebuild ours to aim them
    for o in [o for o in scene.objects if o.type == "CAMERA"]:
        bpy.data.objects.remove(o, do_unlink=True)

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
