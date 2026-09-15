"""The browser UI's server routes every call to the tool surface, so an edit from the page is validator-gated like any other."""

import json
import shutil
import threading
import urllib.request
from pathlib import Path

import pytest

from mmk import serve
from tests.conftest import EXAMPLES


@pytest.fixture
def root(tmp_path):
    """A project root with the fixtures in place, so fixture and variation rules apply as in the repo."""
    ex = tmp_path / "examples"
    ex.mkdir()
    for name in ("room.example.json", "kitchen.fits.json"):
        shutil.copy(EXAMPLES / name, ex / name)
    return tmp_path


def test_layouts_lists_fixtures_and_variations(root):
    r = serve.list_layouts(root)
    paths = {l["path"]: l for l in r["layouts"]}
    assert "examples/kitchen.fits.json" in paths and paths["examples/kitchen.fits.json"]["fixture"] is True
    assert paths["examples/kitchen.fits.json"]["export_stale"] is None      # never exported
    (root / "notes.json").write_text('{"not": "a kitchen"}')                 # ignored: no runs
    (root / "broken.json").write_text("{")                                   # ignored: not JSON
    assert {l["path"] for l in serve.list_layouts(root)["layouts"]} == {"examples/kitchen.fits.json"}


def test_dispatch_reads_and_refuses_fixture_edits(root):
    status, d = serve.dispatch(root, "GET", "/api/describe", {"kitchen": "examples/kitchen.fits.json"})
    assert status == 200 and d["ok"] and d["runs"][0]["items"][1]["label"] == "N-base-15"
    status, r = serve.dispatch(root, "POST", "/api/apply", {}, {"kitchen": "examples/kitchen.fits.json", "ops": [{"op": "remove", "label": "N-base-15"}]})
    assert status == 200 and r["ok"] is False and "start_variation" in r["error"]
    status, r = serve.dispatch(root, "POST", "/api/apply", {}, {"kitchen": "examples/kitchen.fits.json", "ops": [{"op": "remove", "label": "N-base-15"}], "dry_run": True})
    assert status == 200 and r["ok"] is False and any("run_closure" in e for e in r["errors"])   # a dry run still runs the validator


def test_dispatch_variation_then_edit_exports(root):
    status, v = serve.dispatch(root, "POST", "/api/variation", {}, {"kitchen": "examples/kitchen.fits.json", "name": "oak counter"})
    assert status == 200 and v["ok"] and v["path"] == "variations/oak-counter.json"
    status, r = serve.dispatch(root, "POST", "/api/apply", {}, {"kitchen": v["path"], "ops": [{"op": "set_material", "role": "counter", "key": "butcher-block-oak"}]})
    assert status == 200 and r["ok"] and r["written"]
    assert (root / "out" / "oak-counter" / "plan.svg").exists() and (root / "out" / "oak-counter" / "scene.glb").exists()
    assert json.loads((root / v["path"]).read_text())["materials"]["counter"] == "butcher-block-oak"
    assert serve.list_layouts(root)["layouts"][-1] == {"path": v["path"], "name": "Example L kitchen, variation A (fits) — oak counter", "fixture": False, "export_stale": False}


def test_dispatch_catalog_finishes_and_errors(root):
    status, c = serve.dispatch(root, "GET", "/api/catalog", {"kind": "frame", "type": "base", "width_in": "18"})
    assert status == 200 and [i["id"] for i in c["items"]] == ["frame:base:18x24x30"]
    status, f = serve.dispatch(root, "GET", "/api/finishes", {"role": "counter"})
    assert status == 200 and any(x["key"] == "quartz-white" and x["default"] for x in f["finishes"])
    assert serve.dispatch(root, "GET", "/api/catalog", {"width_in": "wide"})[0] == 400
    assert serve.dispatch(root, "GET", "/api/describe", {})[0] == 400
    assert serve.dispatch(root, "POST", "/api/apply", {}, {"kitchen": "x.json", "ops": []})[0] == 400
    assert serve.dispatch(root, "GET", "/api/nothing", {})[0] == 404
    assert serve.dispatch(root, "DELETE", "/api/layouts", {})[0] == 405
    status, d = serve.dispatch(root, "GET", "/api/describe", {"kitchen": "../outside.json"})
    assert status == 200 and d["ok"] is False and "outside" in d["error"]


@pytest.fixture
def server(root):
    srv = serve.make_server(root, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, dict(r.headers), r.read()


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_http_serves_app_viewer_root_and_api(server):
    status, headers, page = _get(server + "/")
    assert status == 200 and b"Millimeter Kitchen" in page and b"/api/apply" in page and headers["Cache-Control"] == "no-store"
    status, _, viewer = _get(server + "/viewer/index.html")
    assert status == 200 and b"GLTFLoader" in viewer                     # the repo's viewer, even though root has no viewer/
    status, _, room = _get(server + "/examples/room.example.json")
    assert status == 200 and json.loads(room)["walls"]
    status, _, lay = _get(server + "/api/layouts")
    assert status == 200 and json.loads(lay)["layouts"][0]["path"] == "examples/kitchen.fits.json"
    status, v = _post(server + "/api/variation", {"kitchen": "examples/kitchen.fits.json", "name": "from the page"})
    assert status == 200 and v["ok"]
    status, r = _post(server + "/api/apply", {"kitchen": v["path"], "ops": [{"op": "remove", "label": "N-filler-left"}]})
    assert status == 200 and r["ok"] is False and any("run_closure" in e or "wall_filler_min" in e for e in r["errors"])
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(urllib.request.Request(server + "/api/apply", data=b"{", headers={"Content-Type": "application/json"}, method="POST"))
    assert exc.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server + "/viewer/../src/mmk/serve.py")
    assert exc.value.code == 404
