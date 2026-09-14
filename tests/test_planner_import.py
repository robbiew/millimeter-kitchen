"""Article numbers flow from the planner's item list into the catalog only when the match is unambiguous."""

import json
import shutil

import pytest

from mmk.cli import main
from mmk.planner_import import frame_type, guess_kind, import_list, parse_size
from tests.conftest import CATALOG

SAMPLE = '''Article number,Product,Quantity,Price
802.653.98,"SEKTION base cabinet frame, white, 36x24x30 """,1,$105.00
302.653.91,"SEKTION base cabinet frame, white, 15x14 ¾x30 """,1,$60.00
190.000.01,"SEKTION wall cabinet frame, white, 30x15x30 """,2,$70.00
190.000.02,"ENKÖPING door, brown walnut effect, 15x30 """,10,$40.00
190.000.03,"ENKÖPING drawer front, brown walnut effect, 18x10 """,1,$25.00
190.000.04,"MAXIMERA drawer, medium, white, 18x24 """,1,$50.00
190.000.05,"FÖRBÄTTRA cover panel, brown walnut effect, 25x30 """,1,$30.00
190.000.06,"FÖRBÄTTRA toekick, brown walnut effect, 87x4 ½ """,3,$20.00
190.000.07,"SEKTION suspension rail, galvanized, 84 """,6,$15.00
190.000.08,"SEKTION leg, 4 pack",7,$10.00
190.000.09,"UTRUSTA hinge w built-in damper for kitchen, 2 pack",17,$8.00
190.000.10,"NYTTIG filler piece for range, 4 pack",1,$9.00
190.000.11,"BODBYN door, off-white, 15x30 """,2,$45.00
'''


@pytest.fixture
def cat(tmp_path):
    dst = tmp_path / "catalog.json"
    shutil.copy(CATALOG, dst)
    return dst


@pytest.fixture
def csv_file(tmp_path):
    f = tmp_path / "items.csv"
    f.write_text(SAMPLE, encoding="utf-8")
    return f


def test_parsing_helpers():
    assert parse_size('SEKTION base cabinet frame, white, 36x24x30 "') == (36, 24, 30)
    assert parse_size("SEKTION base cabinet frame, white, 15x14 ¾x30 \"") == (15, 14.75, 30)
    assert parse_size("FÖRBÄTTRA toe kick, white, 87x4 ½ \"") == (87, 4.5)
    assert parse_size("SEKTION leg, 4 pack") is None
    assert guess_kind("ENKÖPING door, brown walnut effect, 15x30") == "front"
    assert guess_kind("VOXTORP drawer front, walnut effect, 18x10") == "drawer_front"
    assert guess_kind("MAXIMERA drawer, medium, white, 18x24") == "drawer"
    assert guess_kind("UTRUSTA hinge w built-in damper, 2 pack") == "hinge"
    assert guess_kind("SEKTION base cabinet frame, white") == "frame" and frame_type("SEKTION base cabinet frame") == "base"
    assert frame_type("SEKTION wall cabinet frame for fridge") == "wall_fridge"


def test_report_only_does_not_write(cat, csv_file):
    before = cat.read_bytes()
    rep = import_list(cat, csv_file)
    assert rep.written == 0 and cat.read_bytes() == before
    by = {r.article: r for r in rep.rows}
    assert by["802.653.98"].status == "matched" and set(by["802.653.98"].matches) == {"frame:base:36x24x30", "frame:sink_base:36x24x30"}
    assert by["302.653.91"].matches == ["frame:base:15x15x30"]
    assert by["190.000.01"].matches == ["frame:wall:30x15x30"]
    assert by["190.000.02"].matches == ["front:enkoping-walnut:door:15x30"]
    assert by["190.000.03"].matches == ["front:enkoping-walnut:drawer:18x10"]
    assert by["190.000.04"].matches == ["drawer:maximera:18x24:medium"]
    assert by["190.000.05"].matches == ["cover_panel:forbattra:enkoping-walnut:25x30"]
    assert by["190.000.06"].matches == ["toe_kick:forbattra:enkoping-walnut:87"]
    assert by["190.000.07"].matches == ["rail:sektion:84"]
    assert by["190.000.08"].matches == ["legs:sektion:4pack"]
    assert by["190.000.09"].matches == ["hinge:utrusta:2pack"]
    assert by["190.000.11"].matches == ["front:bodbyn-off-white:door:15x30"]
    assert by["190.000.10"].status == "unmatched"          # NYTTIG filler: not in the catalog, honestly reported


def test_write_marks_matched_entries_verified(cat, csv_file):
    rep = import_list(cat, csv_file, write=True)
    assert rep.written == 13  # 12 matched rows, one of them covering two frame entries
    data = json.loads(cat.read_text())
    items = {i["id"]: i for i in data["items"]}
    assert items["frame:base:36x24x30"]["article"] == "802.653.98" and items["frame:base:36x24x30"]["verified"]
    assert items["frame:sink_base:36x24x30"]["article"] == "802.653.98"
    assert items["front:enkoping-walnut:door:15x30"]["article"] == "190.000.02"
    assert items["front:enkoping-walnut:door:18x30"]["article"] is None      # not in the list, untouched
    assert items["rail:sektion:84"]["source"].startswith("ikea-planner-item-list:")


def test_conflicting_article_is_refused(cat, csv_file):
    data = json.loads(cat.read_text())
    for i in data["items"]:
        if i["id"] == "frame:wall:30x15x30":
            i["article"] = "999.999.99"
    cat.write_text(json.dumps(data))
    rep = import_list(cat, csv_file, write=True)
    by = {r.article: r for r in rep.rows}
    assert by["190.000.01"].status == "conflict"
    items = {i["id"]: i for i in json.loads(cat.read_text())["items"]}
    assert items["frame:wall:30x15x30"]["article"] == "999.999.99"


def test_cli_catalog_import(cat, csv_file, capsys):
    rc = main(["catalog", "import", str(csv_file), "--catalog", str(cat)])
    out = capsys.readouterr().out
    assert rc == 1 and "UNMATCHED" in out and "NYTTIG" in out and "MATCHED" in out
