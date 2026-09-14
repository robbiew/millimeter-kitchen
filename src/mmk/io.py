"""Loading and schema-validating the three file kinds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = PACKAGE_ROOT / "schema"
CATALOG_DIR = PACKAGE_ROOT / "catalog"


class FileError(Exception):
    """A file failed to load or did not match its schema."""


@dataclass(frozen=True)
class Loaded:
    path: Path
    data: dict[str, Any]


def _schema(name: str) -> dict[str, Any]:
    with (SCHEMA_DIR / f"{name}.schema.json").open() as fh:
        return json.load(fh)


def load_json(path: str | Path) -> Loaded:
    p = Path(path)
    try:
        with p.open() as fh:
            return Loaded(p.resolve(), json.load(fh))
    except FileNotFoundError as exc:
        raise FileError(f"{p}: not found") from exc
    except json.JSONDecodeError as exc:
        raise FileError(f"{p}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc


def validate_schema(loaded: Loaded, schema_name: str) -> None:
    """Raise FileError with the first schema violation, formatted with its JSON path."""
    validator = jsonschema.Draft202012Validator(_schema(schema_name))
    errors = sorted(validator.iter_errors(loaded.data), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        where = "/".join(str(x) for x in err.absolute_path) or "(root)"
        raise FileError(f"{loaded.path.name}: schema violation at {where}: {err.message}")


def load_validated(path: str | Path, schema_name: str) -> Loaded:
    loaded = load_json(path)
    validate_schema(loaded, schema_name)
    return loaded


def resolve_catalog_path(ref: str, relative_to: Path) -> Path:
    """A kitchen's `catalog` is a catalog id (found in catalog/) or a path relative to the kitchen file."""
    candidate = relative_to.parent / ref
    if candidate.exists():
        return candidate
    by_id = CATALOG_DIR / f"{ref}.json"
    if by_id.exists():
        return by_id
    raise FileError(f"catalog '{ref}' not found next to {relative_to.name} or in {CATALOG_DIR}")
