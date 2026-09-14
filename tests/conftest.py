import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
BAD = EXAMPLES / "bad"
CATALOG = ROOT / "catalog" / "sektion-us-2026-09.json"


@pytest.fixture(scope="session")
def room_data():
    return json.loads((EXAMPLES / "room.example.json").read_text())


@pytest.fixture
def room_copy(room_data):
    return copy.deepcopy(room_data)
