from mmk.units import format_inch, inch_to_mm, mm_to_inch, parse_nominal


def test_inch_to_mm_rounds_to_integer():
    assert inch_to_mm(36) == 914
    assert inch_to_mm(24) == 610
    assert inch_to_mm(15) == 381
    assert inch_to_mm(17.875) == 454


def test_roundtrip_inch():
    assert abs(mm_to_inch(inch_to_mm(30)) - 30) < 0.02


def test_format_inch_carpenter_style():
    assert format_inch(914) == '36"'
    assert format_inch(454) == '17 7/8"'
    assert format_inch(3) == '1/8"'


def test_parse_nominal_handles_fractions():
    assert parse_nominal("36x24x30") == (36.0, 24.0, 30.0)
    assert parse_nominal("15x14 3/4x30") == (15.0, 14.75, 30.0)
    assert parse_nominal("18x30") == (18.0, 30.0)
