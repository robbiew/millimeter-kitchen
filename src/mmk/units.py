"""The only place inches and millimeters meet.

Internally everything is integer millimeters. Inches exist as nominal labels
("36x24x30" printed on the IKEA box) and in CLI output when asked.
"""

from __future__ import annotations

from fractions import Fraction

MM_PER_INCH = Fraction(254, 10)


def inch_to_mm(inches: float | Fraction) -> int:
    """Convert inches to the nearest integer millimeter."""
    return int(round(Fraction(inches) * MM_PER_INCH))


def mm_to_inch(mm: int) -> float:
    """Convert millimeters to decimal inches."""
    return float(Fraction(mm) / MM_PER_INCH)


def format_inch(mm: int, denominator: int = 16) -> str:
    """Format millimeters as a carpenter's inch string, e.g. 17 7/8\"."""
    total = Fraction(mm) / MM_PER_INCH
    sixteenths = round(total * denominator)  # snap to the nearest 1/denominator, never 1/10
    whole, rem = divmod(sixteenths, denominator)
    frac = Fraction(rem, denominator)
    if frac == 0:
        return f'{whole}"'
    if whole == 0:
        return f'{frac.numerator}/{frac.denominator}"'
    return f'{whole} {frac.numerator}/{frac.denominator}"'


def parse_nominal(label: str) -> tuple[float, ...]:
    """Parse a nominal label like "36x24x30" or "18x30" into inch numbers.

    Accepts fractions written as "14 3/4" or "14.75" inside a segment.
    """
    parts = []
    for seg in label.lower().split("x"):
        seg = seg.strip()
        if " " in seg:
            whole, frac = seg.split(" ", 1)
            value = Fraction(whole) + Fraction(frac)
        else:
            value = Fraction(seg)
        parts.append(float(value))
    return tuple(parts)
