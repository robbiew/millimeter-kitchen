"""Phase 1: the product catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .io import load_validated


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    type: str | None
    brand: str
    series: str | None
    finish: str | None
    name: str
    article: str | None
    nominal: str | None
    nominal_in: dict[str, float]
    w: int
    d: int | None
    h: int | None
    verified: bool
    stock_mm: int | None = None
    pack: int | None = None

    @property
    def is_front(self) -> bool:
        return self.kind in ("front", "drawer_front")


class Catalog:
    def __init__(self, id: str, items: dict[str, Item]):
        self.id = id
        self._items = items

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def get(self, item_id: str) -> Item | None:
        return self._items.get(item_id)

    def __getitem__(self, item_id: str) -> Item:
        try:
            return self._items[item_id]
        except KeyError as exc:
            raise KeyError(f"catalog {self.id} has no item '{item_id}'") from exc

    def items(self, kind: str | None = None, type: str | None = None) -> list[Item]:
        return [
            it for it in self._items.values()
            if (kind is None or it.kind == kind) and (type is None or it.type == type)
        ]


def catalog_from_dict(data: dict) -> Catalog:
    items: dict[str, Item] = {}
    for raw in data["items"]:
        actual = raw["actual"]
        items[raw["id"]] = Item(
            id=raw["id"],
            kind=raw["kind"],
            type=raw.get("type"),
            brand=raw["brand"],
            series=raw.get("series"),
            finish=raw.get("finish"),
            name=raw["name"],
            article=raw.get("article"),
            nominal=raw.get("nominal"),
            nominal_in=dict(raw.get("nominal_in", {})),
            w=actual["w"],
            d=actual.get("d"),
            h=actual.get("h"),
            verified=bool(raw["verified"]),
            stock_mm=raw.get("stock_mm"),
            pack=raw.get("pack"),
        )
    return Catalog(data["id"], items)


def load_catalog(path: str | Path) -> Catalog:
    return catalog_from_dict(load_validated(path, "catalog").data)
