"""The review page and index are written by every export and carry what they need to self-check."""

import json
from html.parser import HTMLParser

from mmk.cli import main
from mmk.export import export_all, file_sha
from mmk.model import load_kitchen
from tests.conftest import EXAMPLES


class _Check(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.imgs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "img":
            self.imgs.append(dict(attrs).get("src"))


def test_review_page_and_index(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    ex = export_all(k, tmp_path)
    page = tmp_path / "kitchen.fits" / "index.html"
    assert page.exists() and ex["review"] == str(page)
    text = page.read_text()
    c = _Check()
    c.feed(text)
    assert {"elevation-N.svg", "elevation-E.svg", "plan.svg", "countertop.svg"} <= set(c.imgs)
    for section in ("Validation", "Drawings", "Renders", "3D", "Runs", "Purchase pack", "Assumptions", "Materials"):
        assert section in text, section
    assert "N-sink-36" in text and "rail:sektion:88" in text and "scene.glb" in text
    assert file_sha(k.path) in text                       # the hash the page checks against
    assert "../../" in text or "examples/kitchen.fits.json" in text  # relative source path for the fetch
    assert "No Blender renders" in text
    index = tmp_path / "index.html"
    assert index.exists() and "kitchen.fits/index.html" in index.read_text()
    manifest = json.loads((tmp_path / "kitchen.fits" / "manifest.json").read_text())
    assert "index.html" in manifest["files"]


def test_index_lists_every_export(tmp_path):
    import shutil
    shutil.copy(EXAMPLES / "room.example.json", tmp_path / "room.example.json")
    for name in ("a", "b"):
        src = json.loads((EXAMPLES / "kitchen.fits.json").read_text())
        src["name"] = f"variant {name}"
        (tmp_path / f"{name}.json").write_text(json.dumps(src))
        export_all(load_kitchen(tmp_path / f"{name}.json"), tmp_path / "out")
    idx = (tmp_path / "out" / "index.html").read_text()
    assert "a/index.html" in idx and "b/index.html" in idx


def test_cli_export(tmp_path, capsys):
    assert main(["export", str(EXAMPLES / "kitchen.fits.json"), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "review page" in out and (tmp_path / "kitchen.fits" / "index.html").exists()
