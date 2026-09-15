import pytest

from mmk.io import FileError, load_validated
from tests.conftest import BAD, CATALOG, EXAMPLES, WARN


def test_room_example_validates():
    load_validated(EXAMPLES / "room.example.json", "room")


def test_catalog_validates():
    load_validated(CATALOG, "catalog")


@pytest.mark.parametrize("path", [EXAMPLES / "kitchen.fits.json", *sorted(BAD.glob("*.json")), *sorted(WARN.glob("*.json"))], ids=lambda p: p.stem)
def test_kitchen_files_validate(path):
    load_validated(path, "kitchen")


def test_schema_violation_names_the_path(tmp_path):
    bad = tmp_path / "room.json"
    bad.write_text('{"units":"mm","name":"x","walls":[{"id":"A","length":{"floor":100,"counter":100}}],"corners":[],"ceiling":{"a":2400}}')
    with pytest.raises(FileError) as exc:
        load_validated(bad, "room")
    assert "walls/0/length" in str(exc.value)
