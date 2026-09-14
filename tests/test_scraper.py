"""The catalog scraper's matching logic, against canned search responses (ikea.com itself is not reachable in tests)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scrape_sektion", ROOT / "tools" / "scrape_sektion.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def node(no, name, type_, measure, design=""):
    return {"itemNo": no, "name": name, "typeName": type_, "itemMeasureReferenceText": measure, "validDesignText": design,
            "mainImageAlt": "Sleek modern kitchen cabinet."}   # the alt text is AI-written and never names the finish


DOOR = {"id": "front:voxtorp-walnut:door:15x30", "kind": "front", "type": "door", "series": "VOXTORP", "finish": "walnut effect",
        "name": "VOXTORP door 15x30 walnut effect", "nominal_in": {"w": 15, "h": 30}}
FRAME = {"id": "frame:base:36x24x30", "kind": "frame", "type": "base", "series": "SEKTION", "finish": None,
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
    walnut = node("80425713", "VOXTORP", "Door", '15x30 "', "VOXTORP door, walnut effect, 15x30")
    white = node("60321231", "VOXTORP", "Door", '15x30 "', "VOXTORP door, high-gloss white, 15x30")
    other_size = node("70425714", "VOXTORP", "Door", '15x40 "', "VOXTORP door, walnut effect, 15x40")
    bodbyn = node("90425715", "BODBYN", "Door", '15x30 "', "BODBYN door, off-white, 15x30")
    corner = node("20425716", "VOXTORP", "2-p door f corner base cabinet set", '15x30 "', "VOXTORP walnut effect")
    hit, near = sc.match_item(DOOR, [white, other_size, bodbyn, walnut, corner])
    assert hit is walnut
    assert white in near and other_size in near and corner not in near and bodbyn not in near


def test_finish_can_come_from_the_product_url():
    n = node("80425713", "VOXTORP", "Door", '15x30 "', "Sleek modern kitchen door.")
    n["pipUrl"] = "https://www.ikea.com/us/en/p/voxtorp-door-walnut-effect-80425713/"
    hit, _ = sc.match_item(DOOR, [n])
    assert hit is n


def test_two_matches_is_ambiguous_not_a_guess():
    a = node("80425713", "VOXTORP", "Door", '15x30 "', "VOXTORP door, walnut effect")
    b = node("80425799", "VOXTORP", "Door", '15x30 "', "VOXTORP door walnut effect, 2-pack")
    hit, near = sc.match_item(DOOR, [a, b])
    assert hit is None and set(map(id, near)) == {id(a), id(b)}


def test_bare_frame_beats_combinations():
    # the shapes ikea.com actually returned for "SEKTION base cabinet frame 30x24x30"
    combos = [node("79624095", "SEKTION / MAXIMERA", "Base cab f cktp/4 fronts/3 drawers", '30x24x30 "'),
              node("50298649", "SEKTION", "Base cabinet for oven", '30x24x30 "'),
              node("49307008", "SEKTION", "Base cabinet with 3 drawers", '30x24x30 "'),
              node("59506535", "SEKTION", "Base cabinet with drawer/2 doors", '30x24x30 "')]
    bare = node("30265386", "SEKTION", "Base cabinet", '30x24x30 "')
    frame30 = dict(FRAME, id="frame:base:30x24x30", nominal_in={"w": 30, "d": 24, "h": 30})
    hit, near = sc.match_item(frame30, combos + [bare])
    assert hit is bare
    assert all(c not in near for c in combos)   # combinations are not near misses either
    shallow = node("30265391", "SEKTION", "Base cabinet", '30x14 3/4x30 "')
    assert sc.match_item(frame30, combos + [shallow])[0] is None


def test_white_frame_is_preferred_over_brown():
    white = node("49623945", "SEKTION", "Wall cabinet", '12x15x30 "', "white")
    brown = node("49506319", "SEKTION", "Wall cabinet", '12x15x30 "', "brown")
    wall = dict(FRAME, id="frame:wall:12x15x30", type="wall", nominal_in={"w": 12, "d": 14.75, "h": 30})
    hit, near = sc.match_item(wall, [brown, white])
    assert hit is white and brown in near
    other_white = node("09472444", "SEKTION", "Wall cabinet", '12x15x30 "', "white")
    assert sc.match_item(wall, [brown, white, other_white])[0] is None   # two whites is still ambiguous


def test_frame_families_and_generic_items():
    wall = dict(FRAME, id="frame:wall:30x15x30", type="wall", nominal_in={"w": 30, "d": 15, "h": 30})
    assert sc.match_item(wall, [node("1", "SEKTION", "Wall cabinet frame", '30x15x30 "')])[0]
    assert sc.match_item(wall, [node("1", "SEKTION", "Base cabinet", '30x15x30 "')])[0] is None
    corner = dict(FRAME, id="frame:base_corner:38x38x30", type="base_corner", nominal_in={"w": 38, "d": 38, "h": 30})
    assert sc.match_item(corner, [node("2", "SEKTION", "Corner base cabinet frame", '38x38x30 "')])[0]
    drawer = {"id": "drawer:maximera:low:15x24", "kind": "drawer", "type": None, "series": "MAXIMERA", "finish": None,
              "name": "MAXIMERA drawer, low, 15x24", "nominal_in": {"w": 15, "d": 24}}
    low = node("3", "MAXIMERA", "Drawer, low", '15x24 "')
    high = node("4", "MAXIMERA", "Drawer, high", '15x24 "')
    assert sc.match_item(drawer, [high, low])[0] is low
    panel = {"id": "cover_panel:25x30", "kind": "cover_panel", "type": None, "series": "FORBATTRA", "finish": None,
             "name": "FÖRBÄTTRA cover panel 25x30 (base)", "nominal_in": {"w": 25, "h": 30}}
    assert sc.match_item(panel, [node("5", "FÖRBÄTTRA", "Cover panel", '25x30 "', "white")])[0]   # "(base)" is our note, not IKEA's


def test_variants_are_candidates_and_inherit_name_and_type():
    parent = node("50601749", "VOXTORP", "Door", '24x50 "', "walnut effect")
    parent["gprDescription"] = {"numberOfVariants": 2, "variants": [
        {"itemNo": "80425713", "itemMeasureReferenceText": '15x30 "', "validDesignText": "walnut effect"},
        {"itemNo": "60321231", "itemMeasureReferenceText": '15x30 "', "validDesignText": "high-gloss white"}]}
    nodes = sc.product_nodes({"items": [parent]})
    assert [sc.node_article(n) for n in nodes] == ["506.017.49", "804.257.13", "603.212.31"]
    hit, _ = sc.match_item(DOOR, nodes)
    assert hit is not None and sc.node_article(hit) == "804.257.13"


def test_bare_frame_needs_a_plain_colour_design_text():
    wall = dict(FRAME, id="frame:wall:15x15x30", type="wall", nominal_in={"w": 15, "d": 14.75, "h": 30})
    combo = node("69624171", "SEKTION", "Wall cabinet", '15x15x30 "', "white/Aspudden matte white")   # frame + door
    bare = node("00265458", "SEKTION", "Wall cabinet", '15x14 3/4x30 "', "white")
    assert sc.match_item(wall, [combo])[0] is None and combo not in sc.match_item(wall, [combo])[1]
    assert sc.match_item(wall, [combo, bare])[0] is bare


def test_luhn_check_digit_matches_every_article_seen():
    seen = "80265398 30265391 30265386 90265388 20265396 10265392 00265397 30265414 80265464 00265458 50265451 " \
           "20265462 90265468 10265504 30265503 80265505 70505940 20516738 40516756 00516758 90516754".split()
    assert all(sc.luhn_check(a[1:]) == a[0] for a in seen)
    arts = sc.sweep_articles("02653-02654,05167")
    assert len(arts) == 300 and "80265398" in arts and "20516738" in arts and all(len(a) == 8 for a in arts)


def test_family_queries():
    assert sc.family_query(FRAME) == "SEKTION base cabinet"
    assert sc.family_query(DOOR) == "VOXTORP door"


def test_discover_writes_articles_then_verifies(tmp_path, monkeypatch, capsys):
    cat = {"items": [dict(DOOR, article=None, nominal="15x30", actual={"w": 378, "h": 759}, verified=False),
                     dict(FRAME, article=None, nominal="36x24x30", actual={"w": 914, "d": 610, "h": 762}, verified=False)]}
    p = tmp_path / "cat.json"
    p.write_text(json.dumps(cat))
    responses = {
        "VOXTORP%20door": {"items": [node("80425713", "VOXTORP", "Door", '15x30 "', "VOXTORP door, walnut effect"),
                                              node("80425720", "VOXTORP", "Door", '18x30 "', "VOXTORP door, walnut effect")]},
        "SEKTION%20base%20cabinet": {"items": [node("30265386", "SEKTION", "Base cabinet", '30x24x30 "'),
                                               node("80265398", "SEKTION", "Base cabinet frame", '36x24x30 "'),
                                               node("49307008", "SEKTION", "Base cabinet with 3 drawers", '36x24x30 "')]},
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
