"""Phase 6: derived hardware follows stated rules, the countertop outline matches the runs,
and reconciliation against an IKEA item list reports every kind of difference."""

import json

import pytest

from mmk.cli import main
from mmk.export import export_all
from mmk.model import load_kitchen
from mmk.purchase import countertop_svg, derive, exposed_sides, render_pack
from mmk.reconcile import norm_article, read_ikea_list, reconcile
from tests.conftest import EXAMPLES


@pytest.fixture(scope="module")
def kitchen():
    return load_kitchen(EXAMPLES / "kitchen.fits.json")


@pytest.fixture(scope="module")
def pack(kitchen):
    return derive(kitchen)


def by_id(pack):
    return {l.id: l for l in pack.lines}


def test_rail_per_wall_and_level(pack):
    # N base 3655 -> 2, N wall 1219+1522=2741 -> 2, E base 2131 -> 1, E wall 2131 -> 1
    l = by_id(pack)["rail:sektion:88"]
    assert l.qty == 6 and l.derived and l.rule == "rail"
    assert "wall N base" in l.detail and "wall E wall" in l.detail


def test_legs_and_hinges(pack):
    b = by_id(pack)
    assert b["legs:sektion:4pack"].qty == 7          # 5 base on N, 2 on E
    assert b["hinge:utrusta:2pack"].qty == 17        # 10 + 4 + 2 + 1 doors, none taller than 40"


def test_one_drawer_per_drawer_front(pack):
    b = by_id(pack)
    assert b["drawer:maximera:18x24:medium"].qty == 1 and b["drawer:maximera:18x24:high"].qty == 1
    assert b["drawer:maximera:15x24:low"].qty == 1 and b["drawer:maximera:21x24:high"].qty == 1
    assert sum(l.qty for l in pack.lines if l.kind == "drawer") == 7


def test_exposed_sides_and_cover_panels(kitchen, pack):
    sides = {(r.wall, r.level, side, item.label) for r, side, item in exposed_sides(kitchen)}
    assert ("N", "wall", "end", "N-wall-30") in sides          # at the window
    assert ("N", "wall", "start", "N-wall-36") in sides        # other side of the window
    assert ("E", "wall", "start", "E-wall-21") in sides        # starts past the corner cabinet depth
    assert not any(level == "base" for _, level, _, _ in sides)  # base runs end at walls or in the corner
    b = by_id(pack)
    # 3 exposed wall sides + 1 panel of wall filler stock; base filler stock 1
    assert b["cover_panel:forbattra:13x30"].qty == 4
    assert b["cover_panel:forbattra:25x30"].qty == 1


def test_toe_kick_from_base_run_length(pack):
    assert by_id(pack)["toe_kick:forbattra:87"].qty == 3      # (3655 + 2131) / 2210 -> 3


def test_pack_flags_and_text(kitchen, pack):
    assert pack.missing_articles and all(l.article is None for l in pack.missing_articles)
    text = render_pack(kitchen, pack)
    assert "## Assumptions" in text and "## Not in this pack" in text and "Not ready to buy" in text
    assert "[unverified, no article]" in text


def test_countertop_slabs_and_svg(kitchen, pack):
    slabs = [(s["wall"], s["start"], s["end"], s["depth_mm"], s["corner_start"]) for s in pack.countertop]
    # the north slab runs over the dishwasher; the east run is cut by the range into two slabs
    assert slabs == [("N", 0, 3655, 648, False), ("E", 610, 1143, 648, True), ("E", 1905, 2741, 648, False)]
    e_first = [s for s in pack.countertop if s["wall"] == "E"][0]
    assert e_first["cut_by"] == ["E-range"]
    svg = countertop_svg(kitchen)
    assert 'data-wall="N" data-length="3655" data-depth="648"' in svg
    assert 'data-wall="E" data-length="533"' in svg and 'data-wall="E" data-length="836"' in svg
    assert "corner" in svg and "m²" in svg


def test_export_includes_the_pack(kitchen, tmp_path):
    ex = export_all(kitchen, tmp_path)
    for name in ("purchase-pack.md", "purchase-pack.csv", "countertop.svg"):
        assert (tmp_path / "kitchen.fits" / name).exists()
    csv_text = (tmp_path / "kitchen.fits" / "purchase-pack.csv").read_text()
    assert csv_text.startswith("id,kind,qty,article,name,verified,rule,detail") and "rail:sektion:88" in csv_text


# ---- reconciliation

def _pack_with_articles(kitchen):
    """Give every catalog line a fake article number so the reconciliation can be exercised."""
    pack = derive(kitchen)
    for i, l in enumerate(pack.lines):
        if l.kind not in ("appliance", "finish", "filler") and l.article is None:
            l.article = f"{100 + i:03d}.000.{i % 100:02d}"
    return pack


def test_norm_article():
    assert norm_article("80265398") == "802.653.98"
    assert norm_article("802.653.98") == "802.653.98"
    assert norm_article(" 802-653-98 ") == "802.653.98"


def test_read_ikea_list_loose_headers(tmp_path):
    f = tmp_path / "items.csv"
    f.write_text("Product name;Article number;Quantity\nSEKTION base cabinet frame;802.653.98;2\nVOXTORP door;10200000;4\nSEKTION base cabinet frame;80265398;1\n")
    items = read_ikea_list(f)
    assert items["802.653.98"] == {"qty": 3, "name": "SEKTION base cabinet frame"}
    assert items["102.000.00"]["qty"] == 4


def test_reconcile_reports_every_difference(kitchen, tmp_path):
    pack = _pack_with_articles(kitchen)
    lines = {l.article: l for l in pack.lines if l.article}
    arts = list(lines)
    rows = ["article,qty,name"]
    for a in arts[:-2]:                       # drop two -> only_in_pack
        q = lines[a].qty + (1 if a == arts[0] else 0)  # bump one -> qty_differs
        rows.append(f"{a},{q},{lines[a].name}")
    rows.append("999.999.99,1,Something IKEA added")   # -> only_in_ikea
    f = tmp_path / "ikea.csv"
    f.write_text("\n".join(rows) + "\n")
    rep = reconcile(pack, read_ikea_list(f))
    assert len(rep.qty_differs) == 1 and rep.qty_differs[0]["article"] == arts[0]
    assert {r["article"] for r in rep.only_in_pack} == set(arts[-2:])
    assert rep.only_in_ikea[0]["article"] == "999.999.99"
    assert rep.unreconcilable == []                    # every purchasable line had an article
    assert not rep.clean and rep.open_differences == 4
    # explain them all -> clean
    expl = {arts[0]: "IKEA adds a spare hinge pack", arts[-2]: "buying elsewhere", arts[-1]: "buying elsewhere", "999.999.99": "planner adds a mounting kit"}
    rep2 = reconcile(pack, read_ikea_list(f), expl)
    assert rep2.clean and len(rep2.explained) == 4
    assert "CLEAN" in rep2.render()


def test_reconcile_flags_lines_without_articles(kitchen, tmp_path):
    f = tmp_path / "ikea.csv"
    f.write_text("article,qty\n")
    rep = reconcile(derive(kitchen), read_ikea_list(f))
    assert rep.unreconcilable and not rep.clean


def test_cli_purchase_and_reconcile(tmp_path, capsys):
    assert main(["purchase", str(EXAMPLES / "kitchen.fits.json"), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "countertop.svg").exists()
    (tmp_path / "ikea.csv").write_text("article,qty\n")
    assert main(["reconcile", str(EXAMPLES / "kitchen.fits.json"), str(tmp_path / "ikea.csv")]) == 1
    assert "NO ARTICLE NUMBER" in capsys.readouterr().out
