from mmk.catalog import load_catalog
from tests.conftest import CATALOG


def test_known_articles_present():
    cat = load_catalog(CATALOG)
    assert cat["frame:base:36x24x30"].article == "802.653.98"
    assert cat["frame:base:36x24x30"].w == 914
    assert cat["frame:base:15x15x30"].d == 375


def test_fronts_are_an_eighth_under_nominal():
    cat = load_catalog(CATALOG)
    door = cat["front:voxtorp-walnut:door:18x30"]
    assert door.brand == "IKEA"
    assert (door.w, door.h) == (454, 759)


def test_every_front_is_ikea():
    cat = load_catalog(CATALOG)
    assert all(it.brand == "IKEA" for it in cat.items() if it.is_front)


def test_seed_is_unverified():
    cat = load_catalog(CATALOG)
    assert not any(it.verified for it in cat.items())


def test_list_filters():
    cat = load_catalog(CATALOG)
    assert {it.type for it in cat.items(kind="frame")} == {"base", "sink_base", "wall", "wall_fridge", "high"}
    assert all(it.type == "wall" for it in cat.items(kind="frame", type="wall"))
