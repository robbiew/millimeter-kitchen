"""IKEA's own models: fetched into a cache outside the repo, measured, mapped onto scene nodes, never written back."""
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from mmk import ikea_models as im
from mmk.export import write_model_map
from mmk.gltf import read_glb_boxes, write_glb
from mmk.model import load_kitchen
from mmk.scene import build_scene
from tests.conftest import EXAMPLES


def test_article_normalization():
    assert im.normalize_article("802.653.98") == "80265398"
    assert im.normalize_article("80265398") == "80265398"
    assert im.format_article("80265398") == "802.653.98"
    with pytest.raises(ValueError):
        im.normalize_article("frame:base:30x24x30")


def test_cache_dir_is_outside_the_repo(tmp_path):
    assert im.default_cache_dir(env={"MMK_IKEA_CACHE": str(tmp_path / "m")}) == tmp_path / "m"
    mac = im.default_cache_dir(env={}, system="Darwin")
    assert mac.parts[-3:] == ("Caches", "millimeter-kitchen", "ikea-models") and "Library" in mac.parts
    lin = im.default_cache_dir(env={"XDG_CACHE_HOME": "/xdg"}, system="Linux")
    assert lin == Path("/xdg/millimeter-kitchen/ikea-models")
    repo = Path(__file__).resolve().parents[1]
    assert not str(im.default_cache_dir(env={})).startswith(str(repo))


class FakeIkea:
    """Answers the three requests the client makes and counts them."""

    def __init__(self, models: dict[str, bytes]):
        self.models = models
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict) -> bytes:
        self.calls.append(url)
        if "web-api.ikea.com" in url:
            assert headers["X-Client-Id"] == im.CLIENT_ID
            art = url.rstrip("/").rsplit("/", 1)[1]
            if "/exists/" in url:
                return json.dumps({"exists": art in self.models}).encode()
            if "/model/" in url:
                return json.dumps({"modelUrl": f"https://cdn.example/{art}.glb", "itemNo": art}).encode()
        art = url.rsplit("/", 1)[1].removesuffix(".glb")
        return self.models[art]


def test_client_fetches_once_and_caches(tmp_path):
    fake = FakeIkea({"80265398": b"glb-bytes"})
    c = im.ModelClient(cache=tmp_path, fetch=fake)
    p = c.fetch_model("802.653.98")
    assert p == tmp_path / "80265398" / "model.glb" and p.read_bytes() == b"glb-bytes"
    meta = json.loads((tmp_path / "80265398" / "model.json").read_text())
    assert meta["article"] == "802.653.98" and meta["source"].endswith("80265398.glb")
    n = len(fake.calls)
    assert c.fetch_model("802.653.98") == p and len(fake.calls) == n     # cached: no request
    assert c.cached("802.653.98") == p and c.exists("802.653.98")
    assert c.fetch_model("999.999.99") is None                             # IKEA has no model
    assert c.cached("999.999.99") is None


def test_glb_bounds_match_the_scene_boxes(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    glb = write_glb(build_scene(k), tmp_path / "s.glb")
    lo, hi = im.glb_bounds(glb)
    boxes = read_glb_boxes(glb).values()
    for i in range(3):
        assert abs(lo[i] - min(b["min_mm"][i] for b in boxes)) < 0.5
        assert abs(hi[i] - max(b["max_mm"][i] for b in boxes)) < 0.5


def test_glb_bounds_follow_the_node_hierarchy(tmp_path):
    # a 1 m cube under a parent scaled 0.5 and moved 2 m along X: bounds 2..2.5 m in X
    g = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
         "nodes": [{"translation": [2, 0, 0], "scale": [0.5, 0.5, 0.5], "children": [1]}, {"mesh": 0}],
         "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
         "accessors": [{"type": "VEC3", "componentType": 5126, "count": 8, "min": [0, 0, 0], "max": [1, 1, 1]}]}
    p = tmp_path / "h.gltf"
    p.write_text(json.dumps(g))
    lo, hi = im.glb_bounds(p)
    assert [round(v) for v in lo] == [2000, 0, 0] and [round(v) for v in hi] == [2500, 500, 500]
    assert [round(v) for v in im.glb_size(p)] == [500, 500, 500]


def _cache_with_model(tmp_path, article: str, w: float, h: float, d: float) -> Path:
    """A fake 'IKEA model': one box of the given size written with our own glTF writer."""
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    s = build_scene(k)
    b = next(x for x in s.boxes if x.name == "N-base-30")
    one = replace(s, boxes=(replace(b, min=(0.0, 0.0, 0.0), max=(w, h, d), origin=(0.0, 0.0, 0.0), yaw=0.0),))
    cache = tmp_path / "cache"
    d_ = cache / im.normalize_article(article)
    d_.mkdir(parents=True)
    write_glb(one, d_ / "model.glb")
    return cache


def test_check_item_reports_but_never_writes(tmp_path):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    item = replace(k.catalog["frame:base:30x24x30"], article="802.653.98")
    cache = _cache_with_model(tmp_path, "802.653.98", item.w, item.h, item.d)
    c = im.check_item(item, im.ModelClient(cache=cache))
    assert c.ok and c.describe().endswith("ok")
    off = replace(item, w=item.w + 10)
    c2 = im.check_item(off, im.ModelClient(cache=cache))
    assert not c2.ok and "MISMATCH w-10" in c2.describe()
    none = im.check_item(replace(item, article="999.999.99"), im.ModelClient(cache=cache))
    assert none.model is None and "no IKEA model" in none.describe()
    assert k.catalog["frame:base:30x24x30"].w == item.w   # the catalog is untouched


def test_model_map_covers_every_node_for_a_cached_article(tmp_path, monkeypatch):
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    cat = copy.deepcopy(k.catalog)
    frame = cat["frame:base:30x24x30"]
    cat._items[frame.id] = replace(frame, article="802.653.98")
    scene = build_scene(k)
    arts = im.scene_articles(scene, cat)
    assert arts and all(v == "802.653.98" for v in arts.values())
    assert all(scene_box.extras.get("id") == frame.id for scene_box in scene.boxes if scene_box.name in arts)
    empty = im.ModelClient(cache=tmp_path / "none")
    assert im.model_map(scene, cat, empty) == {}                    # nothing cached, nothing mapped, no network
    cache = _cache_with_model(tmp_path, "802.653.98", frame.w, frame.h, frame.d)
    m = im.model_map(scene, cat, im.ModelClient(cache=cache))
    assert set(m) == set(arts)
    first = m[next(iter(arts))]
    assert first["article"] == "802.653.98" and first["glb"].endswith("model.glb")
    assert [round(v) for v in first["size_mm"]] == [frame.w, frame.h, frame.d]


def test_export_writes_model_map_only_when_something_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("MMK_IKEA_CACHE", str(tmp_path / "empty"))
    k = load_kitchen(EXAMPLES / "kitchen.fits.json")
    assert write_model_map(build_scene(k), k, tmp_path) is None
    assert not (tmp_path / "ikea-models.json").exists()


def test_cli_check_without_cache(tmp_path, capsys):
    from mmk.cli import main
    rc = main(["ikea-models", "check", "802.653.98", "--cache", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1 and "no IKEA model" in out
    rc = main(["ikea-models", "check", "111.111.11", "--cache", str(tmp_path)])
    assert rc == 0 and "not in the catalog" in capsys.readouterr().out
