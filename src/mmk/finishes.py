"""Phase 4: the finish library. A finish is a name, a color and PBR factors; never a dimension."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .io import CATALOG_DIR

FINISHES_PATH = CATALOG_DIR / "finishes.json"
ROLES = ("frame", "front", "counter", "backsplash", "floor", "wall", "appliance", "toe_kick", "glass")


@dataclass(frozen=True)
class Finish:
    key: str
    role: str
    name: str
    color: tuple[float, float, float]  # sRGB 0..1 as authored; use linear_rgba for glTF
    roughness: float
    metallic: float
    alpha: float = 1.0
    brand: str | None = None

    @property
    def rgba(self) -> tuple[float, float, float, float]:
        """sRGB color with alpha, as authored in finishes.json."""
        return (*self.color, self.alpha)

    @property
    def linear_rgba(self) -> tuple[float, float, float, float]:
        """glTF baseColorFactor is linear; a hex color from a product photo is sRGB."""
        return (*(srgb_to_linear(c) for c in self.color), self.alpha)


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


class FinishLibrary:
    def __init__(self, data: dict):
        self.id = data["id"]
        self.finishes: dict[str, Finish] = {}
        for key, f in data["finishes"].items():
            self.finishes[key] = Finish(key, f["role"], f["name"], _hex_to_rgb(f["color"]), float(f["roughness"]), float(f["metallic"]), float(f.get("alpha", 1.0)), f.get("brand"))
        self.defaults: dict[str, str] = dict(data["defaults"])
        for role in ROLES:
            if role not in self.defaults:
                raise ValueError(f"finishes.json has no default for role '{role}'")
            if self.defaults[role] not in self.finishes:
                raise ValueError(f"default finish '{self.defaults[role]}' for role '{role}' is not in the library")

    def __contains__(self, key: str) -> bool:
        return key in self.finishes

    def __getitem__(self, key: str) -> Finish:
        try:
            return self.finishes[key]
        except KeyError as exc:
            raise KeyError(f"no finish '{key}' in {self.id}") from exc

    def for_role(self, role: str) -> list[Finish]:
        return [f for f in self.finishes.values() if f.role == role]


def load_finishes(path: str | Path = FINISHES_PATH) -> FinishLibrary:
    with Path(path).open() as fh:
        return FinishLibrary(json.load(fh))
