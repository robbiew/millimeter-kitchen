# Survey Protocol (Phase 0)

The survey is the only source of wall dimensions. A LiDAR scan (Apple RoomPlan,
Polycam, IKEA Kreativ) may be taken first to rough in the envelope, but every
number in `room.json` comes from a tape or laser measure.

## Tools

- Laser distance meter (Bosch GLM or Leica Disto class). Set it to millimeters.
- 25 ft tape for cross-checks and short distances the laser cannot reach.
- 4 ft level or a plumb line for plumb deviation.
- Painter's tape and a marker to label walls on site.

## Naming

Walk the room clockwise from the entry door. Label walls `A`, `B`, `C`, `D`…
(the example file uses compass names for readability; either works). A wall's
`from` coordinate runs left to right when you face the wall, starting at the
corner on your left.

## Per wall

1. **Length at three heights**: floor, 914 mm (36", countertop), 2134 mm (84",
   top of a 90" high cabinet is 2286 + legs; measure at 2134 as a proxy).
   Record all three under `length`. The planning length is the **smallest**.
2. **Plumb deviation**: hold the level against the wall at the corner; record
   how many mm the wall leans over 1200 mm. Positive means the wall leans into
   the room going up.
3. **Openings**: every window and door. `from` (left jamb from the wall
   start), `width`, `sill` and `head` heights from the finished floor. Include
   trim in the width; cabinets cannot overlap trim.
4. **Services**: sink drain centerline, water supply, gas stub, dedicated
   outlets, switches, vents. `at` is the centerline from the wall start;
   `height` from the floor where relevant.
5. **Obstructions**: soffits, bulkheads, radiators, chases. Record `from`,
   `to`, and the `bottom` height for anything hanging from the ceiling.

## Per corner

Measure the diagonal between the far ends of the two walls meeting at the
corner (from the end of wall A that is not the corner, to the end of wall B
that is not the corner), at countertop height. `mmk survey check` compares this
to the right-angle expectation and reports how far out of square the corner is
in mm at the far end of each wall. The layout then uses the true angle: an
acute corner pushes the next wall's first cabinet out and widens the filler
the first wall needs at the corner; the plan and the 3D scene draw the real
angle.

## Ceiling

Measure floor to ceiling at every corner and at the center. High cabinets are
sized from the **smallest** value.

## Floor

Note the highest point of the floor along each base run. Cabinets are leveled
to the highest point; legs adjust down elsewhere.

## Acceptance

`mmk survey check room.json` exits 0 when:

- every wall has three length readings within 6 mm of each other,
- every corner between adjacent walls has a diagonal,
- every opening and service lies within its wall,
- ceiling readings are present for every corner.

Warnings (non-fatal) flag corners more than 25 mm out of square and ceiling
spreads over 12 mm.
