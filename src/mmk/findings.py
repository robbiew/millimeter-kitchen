"""A finding is the validator's only output type."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    rule: str
    message: str
    wall: str | None = None
    item: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.level == "error"

    def render(self) -> str:
        where = " ".join(x for x in (f"wall {self.wall}" if self.wall else "", f"[{self.item}]" if self.item else "") if x)
        return f"{self.level.upper():7} {self.rule:26} {where + ': ' if where else ''}{self.message}"


def has_errors(findings: list[Finding]) -> bool:
    return any(f.is_error for f in findings)
