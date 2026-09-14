from mmk.room import check_room, room_from_dict
from mmk.units import inch_to_mm


def errors(findings):
    return {f.rule for f in findings if f.is_error}


def warnings(findings):
    return {f.rule for f in findings if not f.is_error}


def test_example_room_passes(room_data):
    room = room_from_dict(room_data)
    findings = check_room(room)
    assert errors(findings) == set()
    assert room.walls["N"].planning_length == 3655  # the tightest of three readings
    assert room.min_ceiling == 2436


def test_length_spread_over_6mm_is_an_error(room_copy):
    room_copy["walls"][0]["length"]["high"] = 3640
    assert "wall_length_spread" in errors(check_room(room_from_dict(room_copy)))


def test_missing_corner_diagonal_is_an_error(room_copy):
    room_copy["corners"] = []
    assert "corner_missing_diagonal" in errors(check_room(room_from_dict(room_copy)))


def test_out_of_square_corner_warns(room_copy):
    room_copy["corners"][0]["diagonal"] = 4620  # ~1.6 degrees open
    f = check_room(room_from_dict(room_copy))
    assert "corner_out_of_square" in warnings(f)
    w = next(x for x in f if x.rule == "corner_out_of_square")
    assert w.extra["out_of_square_mm"] > 25


def test_square_corner_does_not_warn(room_copy):
    f = check_room(room_from_dict(room_copy))
    assert "corner_out_of_square" not in warnings(f)


def test_opening_outside_wall(room_copy):
    room_copy["walls"][0]["openings"][0]["from"] = 3000
    assert "opening_outside_wall" in errors(check_room(room_from_dict(room_copy)))


def test_ceiling_spread_warns(room_copy):
    room_copy["ceiling"]["SW"] = 2460
    assert "ceiling_spread" in warnings(check_room(room_from_dict(room_copy)))


def test_inch_reference_points():
    # the protocol's three heights, so nobody re-derives them
    assert inch_to_mm(36) == 914 and inch_to_mm(84) == 2134
