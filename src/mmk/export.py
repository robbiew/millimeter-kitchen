"""Everything derived from a kitchen file, regenerated together.

Drawings and the glTF scene are fast, so every successful edit re-exports
them. Blender renders take seconds and are opt-in. Outputs go to
`<out>/<kitchen stem>/` so a fixture and its variations never overwrite
each other, and a manifest records the source file's hash so a stale
export can be detected.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .draw import DEFAULT_SCALE, write_drawings
from .gltf import write_glb
from .model import Kitchen
from .purchase import countertop_svg, derive, pack_csv, render_pack
from .review import write_review
from .scene import build_scene

BLENDER_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "blender_render.py"

# Where Blender's own installers put the executable when it is not on PATH.
BLENDER_CANDIDATES: tuple[str, ...] = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "~/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    "/opt/blender/blender",
    "C:/Program Files/Blender Foundation/Blender/blender.exe",
)


def find_blender(explicit: str | None = None, env: dict[str, str] | None = None) -> str | None:
    """Locate the Blender executable: an explicit path, then the MMK_BLENDER
    environment variable, then PATH, then the usual install locations.
    Returns None when nothing usable exists. An explicit path that does not
    exist is returned as is so the caller can report it."""
    env = os.environ if env is None else env
    if explicit:
        return explicit
    hinted = env.get("MMK_BLENDER")
    if hinted:
        return os.path.expanduser(hinted)
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    for cand in BLENDER_CANDIDATES:
        p = Path(os.path.expanduser(cand))
        if p.exists():
            return str(p)
    # Versioned Windows installs: C:/Program Files/Blender Foundation/Blender 4.2/blender.exe
    for p in sorted(Path("C:/Program Files/Blender Foundation").glob("Blender*/blender.exe"), reverse=True):
        return str(p)
    return None


def output_dir(out_root: str | Path, kitchen_path: str | Path) -> Path:
    return Path(out_root) / Path(kitchen_path).stem


def file_sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_all(k: Kitchen, out_root: str | Path, scale: int = DEFAULT_SCALE, render: bool = False,
               blender: str | None = None, engine: str = "EEVEE") -> dict[str, Any]:
    """Write drawings, scene.glb, cameras.json and a manifest for `k`; optionally render with Blender."""
    out = output_dir(out_root, k.path)
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"out": str(out)}
    result["drawings"] = [str(p) for p in write_drawings(k, out, scale)]
    scene = build_scene(k)
    result["glb"] = str(write_glb(scene, out / "scene.glb"))
    cams = out / "cameras.json"
    cams.write_text(json.dumps([{"name": c.name, "position": list(c.position), "target": list(c.target), "vfov_deg": c.vfov_deg, "aspect": c.aspect} for c in scene.cameras], indent=2) + "\n")
    result["cameras"] = str(cams)
    pack = derive(k)
    (out / "purchase-pack.md").write_text(render_pack(k, pack))
    (out / "purchase-pack.csv").write_text(pack_csv(pack))
    (out / "countertop.svg").write_text(countertop_svg(k, scale))
    result["purchase"] = [str(out / "purchase-pack.md"), str(out / "purchase-pack.csv"), str(out / "countertop.svg")]
    result["renders"] = []
    if render:
        exe = find_blender(blender)
        if not exe or not Path(exe).exists():
            result["render_note"] = "blender not found; pass a blender path or set MMK_BLENDER to render"
        else:
            proc = subprocess.run([exe, "--background", "--python", str(BLENDER_SCRIPT), "--", result["glb"], str(cams), str(out), "--engine", engine], capture_output=True, text=True)
            result["renders"] = sorted(str(p) for p in out.glob("render-*.png"))
            if proc.returncode != 0:
                result["render_error"] = proc.stderr[-2000:]
    manifest = {
        "source": str(k.path),
        "source_sha256": file_sha(k.path),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [Path(p).name for p in result["drawings"]] + ["scene.glb", "cameras.json", "purchase-pack.md", "purchase-pack.csv", "countertop.svg", "index.html"] + [Path(p).name for p in result["renders"]],
        "renders_current": bool(render and result["renders"]),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    result["manifest"] = str(out / "manifest.json")
    result["scale"] = scale
    result["review"] = str(write_review(k, out, pack, result, manifest["source_sha256"]))
    result["index"] = str(out.parent / "index.html")
    return result


def is_stale(out_root: str | Path, kitchen_path: str | Path) -> bool | None:
    """True if the export for this kitchen predates the file's current content; None if never exported."""
    m = output_dir(out_root, kitchen_path) / "manifest.json"
    if not m.exists():
        return None
    return json.loads(m.read_text()).get("source_sha256") != file_sha(kitchen_path)
