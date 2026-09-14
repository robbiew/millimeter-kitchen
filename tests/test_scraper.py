"""The catalog scraper's matching logic, against canned search responses (ikea.com itself is not reachable in tests)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scrape_sektion", ROOT / "tools" / "scrape_sektion.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def node(no, name, type_, measure, alt=""):
    return {"itemNo": no, "name": name, "typeName": type_, "itemMeasureReferenceText": measure, "mainImageAlt": alt}


DOOR = {"id": "front:voxtorp-walnut:door:15x30", "kind": "front", "series": "VOXTORP", "finish": "walnut effect",
        "name": "VOXTORP door 15x30 walnut effect", "nominal_in": {"w": 15, "h": 30}}
FRAME = {"id": "frame:base:36x24x30", "kind": "frame", "series": "SEKTION", "finish": None,
         "name": "SEKTION base cabinet frame 36x24x30", "nominal_in": {"w": 36, "d": 24, "h": 30}}


def test_search_url_quotes_text_and_strips_article_dots():
    assert "q=80265398&" in sc.search_url("802.653.98")
    assert "q=VOXTORP%20door%2015x30" in sc.search_url("VOXTORP door 15x30")


def test_product_nodes_walks_any_response_shape():
    data = {"searchResultPage": {"products": {"main": {"items": [
        {"product": node("30265391", "SEKTION", "base cabinet frame", '15x14 3/4x30 "')},
        {"product": {"itemNo": "11111111", "name": "no measure, not a product"}}]}}}}
    nodes = sc.product_nodes(data)
    assert [sc.node_article(n) for n in nodes] == ["302.653.91"]
    assert sc.node_measure(nodes[0]) == {"w": 15, "d": 14.75, "h": 30}


def test_match_needs_series_size_and_finish():
    walnut = node("80425713", "VOXTORP", "door", '15x30 "', "VOXTORP door, walnut effect, 15x30")
    white = node("60321231", "VOXTORP", "door", '15x30 "', "VOXTORP door, high-gloss white, 15x30")
    other_size = node("70425714", "VOXTORP", "door", '15x40 "', "VOXTORP door, walnut effect, 15x40")
    bodbyn = node("90425715", "BODBYN", "door", '15x30 "', "BODBYN door, off-white, 15x30")
    hit, near = sc.match_item(DOOR, [white, other_size, bodbyn, walnut])
    assert hit is walnut
    assert white in near and other_size in near and bodbyn not in near   # wrong series is not even a near miss


def test_two_matches_is_ambiguous_not_a_guess():
    a = node("80425713", "VOXTORP", "door", '15x30 "', "VOXTORP door, walnut effect")
    b = node("80425799", "VOXTORP", "door", '15x30 "', "VOXTORP door walnut effect, 2-pack")
    hit, near = sc.match_item(DOOR, [a, b])
    assert hit is None and set(map(id, near)) == {id(a), id(b)}


def test_frame_matches_on_three_dimensions():
    ok = node("80265398", "SEKTION", "base cabinet frame", '36x24x30 "', "SEKTION base cabinet frame, white")
    shallow = node("30265391", "SEKTION", "base cabinet frame", '36x14 3/4x30 "')
    hit, near = sc.match_item(FRAME, [shallow, ok])
    assert hit is ok and shallow in near


def test_discover_writes_articles_then_verifies(tmp_path, monkeypatch, capsys):
    cat = {"items": [dict(DOOR, article=None, nominal="15x30", actual={"w": 378, "h": 759}, verified=False),
                     dict(FRAME, article=None, nominal="36x24x30", actual={"w": 914, "d": 610, "h": 762}, verified=False)]}
    p = tmp_path / "cat.json"
    p.write_text(json.dumps(cat))
    responses = {
        "VOXTORP%20door%2015x30": {"items": [node("80425713", "VOXTORP", "door", '15x30 "', "VOXTORP door, walnut effect")]},
        "SEKTION%20base%20cabinet%20frame%2036x24x30": {"items": [node("80265398", "SEKTION", "base cabinet frame", '36x24x30 "')]},
    }

    def fake_fetch(url):
        if "search-result-page" in url:
            q = url.split("q=")[1].split("&")[0]
            if q.isdigit():   # the verify pass looks the article up by number
                return json.dumps({"items": [n for r in responses.values() for n in r["items"] if n["itemNo"] == q]})
            for key, resp in responses.items():
                if q.startswith(key):
                    return json.dumps(resp)
            return json.dumps({"items": []})
        return "<html>no dimensions block here</html>"   # product page: force the search-API fallback

    monkeypatch.setattr(sc, "fetch", fake_fetch)
    rc = sc.main([str(p), "--discover", "--write", "--delay", "0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "front:voxtorp-walnut:door:15x30: 804.257.13" in out and "discover: 2 found, 0 ambiguous, 0 missing of 2" in out
    items = {i["id"]: i for i in json.loads(p.read_text())["items"]}
    assert items["front:voxtorp-walnut:door:15x30"]["article"] == "804.257.13"
    assert items["frame:base:36x24x30"]["article"] == "802.653.98"
    assert items["frame:base:36x24x30"]["verified"] is True     # verified by the search-API measure text
    assert "802.653.98: ok" in out
