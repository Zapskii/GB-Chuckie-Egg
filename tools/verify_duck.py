#!/usr/bin/env python3
"""Assert the mother duck: caged and harmless on levels 1-8, loose from 9.

The Z80 draws MotherDuckX/Y through the same `DrawSpriteNum` as Harry, so its y
is the TOP of its 16x16 box, and `MoveMotherDuck` (Chuckie.asm:3364) chases him
on both axes -- but while the level counter is below eight the whole update is
thrown away and the duck is re-planted at $9808, the cage (Chuckie.asm:3462-3475,
`CP $08` on a 0-based counter, so the plant ends at level 9). Its overlap test
(:2545) is lethal on every level, and it is a window centred on the duck:

    duck_x - 8 <= player_x <= duck_x + 7
    duck_y - 9 <= player_y <= duck_y + 9

Two of these sections read the screen and the level rather than the transform,
which is the only way to see the bug class this port keeps meeting: a check that
recomputes `OAM_ROW_BASE - y - SCY` agrees with whatever that constant says, so
it cannot see the constant move. Section 2 puts the duck's own pixels on the
cage's own cells; section 4 pins the plant by watching it not move.

The plant's own boundary is the pair of ROMs: section 4 covers it on 8 (caged,
one level later than the port used to think) and section 6 chases on 9.

    python3 tools/verify_duck.py build/l1.gb
    python3 tools/verify_duck.py build/l8.gb
    python3 tools/verify_duck.py build/l9.gb
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbdata  # noqa: E402
import harness  # noqa: E402

ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"
ASM = "reference/paulie/Chuckie.asm"

LEVEL_WIDTH, LEVEL_HEIGHT = 32, 21
HUD_ROWS = 1
SCREEN0, VRAM = 0x9800, 0x8000

# DrawLevel puts buffer row 0 at map row 21; verify_hud.py derives the same
# number from the same two constants. Section 2 checks the map against it.
MAP_ROW0 = LEVEL_HEIGHT - 1 + HUD_ROWS

HEN_MAX = 5
HEN_NONE = 0xFF

# The OAM chain in src/main.asm: four for Harry, HEN_MAX*4 for the hens, FOUR
# for the lifts (two platforms of two 8x8 halves each), then the duck's four.
# The lift count is the load-bearing part: at +2 the duck's top half shared
# entries with the second platform, and level 3 is in the make rule to keep that
# from coming back unnoticed.
DUCK_OAM = 4 + HEN_MAX * 4 + 4
OAM_ROW_BASE = 191          # src/main.asm: an OAM row is a screen line + 16
OAM_COL_OFFSET = 8          # src/main.asm: an OAM column is a screen column + 8
DUCK_OBP1 = 0x10            # attribute bit 4: OBP1, the bird palette
DUCK_XFLIP = 0x20           # attribute bit 5: mirror the tile horizontally
DUCK_FRAME_TILES = 4

# The Z80's window (Chuckie.asm:2545): the duck's centre, not the hen's offset.
DUCK_REACH_X, DUCK_REACH_Y = 8, 9

# MoveMotherDuck's own bounds (:3439): a step that would leave the level is
# refused and reflected, so the duck never reaches these values.
DUCK_X_MAX, DUCK_Y_MIN, DUCK_Y_MAX = 0xEE, 0x14, 0xA6
DUCK_SPEED = 0x0C           # updates every 12 gameplay ticks
DUCK_CAGE_X, DUCK_CAGE_Y = 8, 0x98

# The cage is the level's non-blank cells in the top-left corner, 4 wide. The
# plant is at (8, $98) while the counter is below `DUCK_FREE_FROM` -- so the cage
# has to be where the level data says it is for that to be a cage and not open
# air.
CAGE_ROWS, CAGE_COLS = range(15, 21), range(0, 5)
# The plant's own gate, mirrored from main.asm's DEF: the Z80's `CP $08` on a
# 0-based counter, so 8 is level 9 -- not the eighth level. Section 4 runs on 8
# (the last caged one) and section 6 on 9, which is the boundary itself.
DUCK_FREE_FROM = 8

# Harry's spawn, as src/main.asm sets it. He is only parked and read here, never
# driven -- and park()'s default is the value that matters, this is level 8's.
HARRY_START_X, HARRY_START_Y = 100, 23
# Parked out of the duck's way, but still up where the camera clamps to 0/0:
# park him any lower and the cage scrolls off the screen, over the top and the
# duck disappears at x <= 72 (SCX = clamp(x-72, 0, 96)).
PARK_X, PARK_Y = 56, 120

CAGED_FRAMES = 120          # ten duck updates
ROAM_FRAMES = 400           # ~33 updates at DUCK_SPEED


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wDuckX", "wDuckY", "wDuckVelX", "wDuckVelY", "wDuckFace", "wDuckFrame",
        "wDuckTick", "wPlayerX", "wPlayerY", "wPlayerInAir", "wPlayerDead",
        "wDeathTimer", "wHens", "wCurrentLevel"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

wPlayerX, wPlayerY = sym["wPlayerX"], sym["wPlayerY"]
wPlayerInAir = sym["wPlayerInAir"]
wHens = sym["wHens"]

# The duck's art, as the source has it: two 16x16 1bpp frames, the second a
# mirror of the first (gbdata asserts that). Ink is a set bit.
duck_src = gbdata.duck_frames(ASM)
want_tiles = [t for sp in duck_src for t in gbdata.sprite_tiles(sp)]
gfx, _, levels, _, _, _ = gbdata.build(ASM)

pb = harness.boot(ROM)

# The hens are benched for the whole check, before anything is measured. Two
# reasons, both of which cost a debugging round: a hen's sprite is OBP1 and
# therefore the SAME shade as the duck's, so one wandering into the cage would
# show up inside section 2's ink mask; and a hen killing Harry starts a death
# whose reload re-plants the duck and resets its tick -- which silently undid
# section 5's first poke and made section 4 vacuous. Only the duck may kill him
# here, and only where section 5 asks it to.
for s in range(HEN_MAX):
    pb.memory[wHens + s * 4] = HEN_NONE

failed = []
fail = failed.append


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def oam(i):
    a = 0xFE00 + i * 4
    return tuple(pb.memory[a:a + 4])


def duck_oam():
    return [oam(DUCK_OAM + i) for i in range(4)]


def duck():
    return reg("wDuckX"), reg("wDuckY")


def park(x=PARK_X, y=PARK_Y):
    """Harry out of the picture, but where the camera sits at 0/0."""
    pb.memory[wPlayerInAir] = 0
    pb.memory[wPlayerX] = x
    pb.memory[wPlayerY] = y


def parked_tick(n=1, x=PARK_X, y=PARK_Y):
    # Re-poked every frame: gravity would walk him down out of the camera's
    # clamped band within a few of them.
    for _ in range(n):
        park(x, y)
        pb.tick(1, True)


def put_duck(x, y):
    pb.memory[sym["wDuckX"]] = x
    pb.memory[sym["wDuckY"]] = y


# The duck is left where it spawns and the tick is held high, so nothing in
# sections 1 and 2 depends on when the chase would have started.
setreg("wDuckTick", 0xFF)

# --- 1. The duck's four OAM entries -------------------------------------------
# The tiles are found in VRAM by their pixels rather than trusted from the base:
# 6c-3 shipped 54 tiles missing with the map happily naming them, because a map
# index is the right number whether or not the tile arrived.
vram = bytes(pb.memory[VRAM:VRAM + 256 * 16])
bases = [t for t in range(257 - len(want_tiles))
         if all(vram[(t + i) * 16:(t + i + 1) * 16] == want_tiles[i]
                for i in range(len(want_tiles)))]
# Where the art landed is read OUT of VRAM, and DUCK_TILE_BASE is not written
# down here. It is SCORE_TILE_BASE + SCORE_TILE_COUNT in src/main.asm, so it
# moves whenever a run before it grows -- which the high-score screen's did, by
# two glyphs, when its legend gained a d-pad. A number frozen in the check
# reports that as a duck bug. What is worth asserting is the pair below: the art
# is ONE contiguous copy of the source frames, and the OAM names that copy --
# which still catches a frame copied short, a shared tile, and a draw base that
# disagrees with the copy's.
if not bases:
    raise SystemExit("FAIL: the duck's %d tiles are nowhere in VRAM -- the art "
                     "was not copied in" % len(want_tiles))
if len(bases) > 1:
    fail("the duck's %d tiles appear %d times in VRAM (%s), expected the one "
         "copy Start makes" % (len(want_tiles), len(bases), bases))
DUCK_TILE_BASE = bases[0]
print("duck art: %d tiles at VRAM %d..%d" % (len(want_tiles), DUCK_TILE_BASE,
                                             DUCK_TILE_BASE + len(want_tiles) - 1))

q = duck_oam()
# The pose picks the tiles, the facing picks the flip. The port emits the two
# right-facing poses and mirrors them on the way out -- the source's left-facing
# poses are exactly that mirror, which gbdata.duck_frames asserts at build time.
# So the entries are the pose's four consecutive tiles either way: in TL TR BL
# BR order facing right, and with each half's columns swapped facing left, which
# is what mirroring a 16x16 does to the halves.
pose = reg("wDuckFrame")
e = DUCK_TILE_BASE + pose * DUCK_FRAME_TILES
face = 0 if reg("wPlayerX") >= reg("wDuckX") else 1
print("duck OAM: %s (pose %d, face %d)" % (q, pose, face))
want_attr = DUCK_OBP1 | (DUCK_XFLIP if face else 0)
want_tiles = [e, e + 1, e + 2, e + 3] if not face else [e + 1, e, e + 3, e + 2]
if [x[3] for x in q] != [want_attr] * 4:
    fail("the duck's attributes are %s, expected all $%02X (OBP1%s)"
         % ([x[3] for x in q], want_attr,
            " | X-flip, for the left facing" if face else ", the bird palette"))
if [x[2] for x in q] != want_tiles:
    fail("the duck's tiles are %s, expected %s: pose %d%s"
         % ([x[2] for x in q], want_tiles, pose,
            ", halves swapped for the flip" if face else ""))
if not (q[1][1] == q[0][1] + 8 and q[2][0] == q[0][0] + 8
        and q[3][1] == q[2][1] + 8 and q[3][0] == q[1][0] + 8):
    fail("the duck's quadrants are not TL/TR/BL/BR: %s" % q)

# It faces Harry, and the facing is the flip: none when he is to its right, the
# flip plus the column swap when he is to its left. `NC` on `player_x - duck_x`
# is the source's own comparison.
if reg("wDuckFace") != face:
    fail("wDuckFace is %d, the drawn flip says %d" % (reg("wDuckFace"), face))

# The other way round, on the same level: he is poked left of the duck and the
# duck must turn -- a facing that is always one way passes everything above.
#
# It takes one duck update to turn it, which is the contract now: the facing is
# decided in UpdateDuck along with the pose and the movement, so wDuckTick = 1
# is what asks the question. Poking Harry and ticking a plain frame only reached
# it while the facing was read on the draw -- and reading it there is what put
# the turn on the frame clock instead of the duck's (section 3b).
#
# Eight px to its left, not one: an update moves the duck, by at most
# DUCK_VEL_MAX a step, and from the ninth level nothing re-plants it -- so a duck
# asked to turn from one px away can step past him and rightly face the other
# way. Eight is more than one step, and below the ninth level the plant puts it
# at the cage whatever the step did, so both are deterministic.
park(reg("wDuckX") - 8)
setreg("wDuckTick", 1)
tick(1)
q = duck_oam()
# The pose toggled with the update, so the tile base has to be read again.
e = DUCK_TILE_BASE + reg("wDuckFrame") * DUCK_FRAME_TILES
print("Harry poked to x=%d -> duck tiles %s attrs %s"
      % (reg("wPlayerX"), [x[2] for x in q], [x[3] for x in q]))
if [x[3] for x in q] != [DUCK_OBP1 | DUCK_XFLIP] * 4:
    fail("with Harry to its left the duck's attributes are %s, expected $%02X "
         "(OBP1 | X-flip)" % ([x[3] for x in q], DUCK_OBP1 | DUCK_XFLIP))
if [x[2] for x in q] != [e + 1, e, e + 3, e + 2]:
    fail("with Harry to its left the duck drew tiles %s, expected the pose's "
         "halves swapped, %s" % ([x[2] for x in q], [e + 1, e, e + 3, e + 2]))
if reg("wDuckFace") != 1:
    fail("with Harry to its left wDuckFace is %d, expected 1" % reg("wDuckFace"))

# --- 2. The duck's pixels, on the cage's own cells, both facings -------------
# The property the player sees, and the one section 1 cannot check: it compares
# OAM against the transform, so it agrees with the transform whatever it says.
# The camera is put at 0/0 by parking Harry, and the duck is then read TWICE --
# once drawn, and once moved to a y whose 16 px box is entirely above the screen,
# which is the cage alone and therefore the duck's own background. Over the box
# the OAM names, pixel for pixel:
#   * every pixel the source art inks is the duck's one ink shade, and
#   * every pixel the art leaves blank is still exactly what was behind it --
#     the sprite's colour 0 is transparent, so the cage has to show through.
# Both are read off frames this ROM drew, so there is no palette constant to
# recompute: a wrong base, anchor, quadrant or camera moves the box and the
# pixels stop matching. (A wrong PLANT is self-consistent here and is section 4's
# job -- it names the exact cell.)
#
# Run for both facings, because the left one is not drawn from art of its own:
# it is the pose mirrored, by OAM's flip bit, and this is the only place that
# checks the flip actually produces the bird the source's frame 10 is. Harry
# sits to the duck's right for the first pass and to its left for the second --
# both x values still clamp the camera to 0, which is asserted just below.
FACE_PARK_X = (PARK_X, DUCK_CAGE_X - 1)

parked_tick(3)
scy, scx = pb.memory[0xFF42], pb.memory[0xFF43]
if (scy, scx) != (0, 0):
    fail("parking Harry at (%d,%d) left the camera at SCY %d SCX %d, so the "
         "cage is not on screen to look at" % (PARK_X, PARK_Y, scy, scx))

level = levels[reg("wCurrentLevel") & 7]
cells = sorted((r, c) for r in CAGE_ROWS for c in CAGE_COLS if level[r * 32 + c])
if not cells:
    raise SystemExit("FAIL: no cage in the level's top-left corner -- the level "
                     "data is not what this check thinks it is")
rows = [r for r, _ in cells]
cols = [c for _, c in cells]
# Buffer row r is map row MAP_ROW0-r, so the highest level row is the highest on
# screen. Checked against the map itself, not just derived: if the mapping or
# the level data moved, the cage's cells would not hold the cage's own tiles.
badmap = [(r, c) for r, c in cells
          if pb.memory[SCREEN0 + (MAP_ROW0 - r) * 32 + c] != level[r * 32 + c]]
if badmap:
    fail("the cage's cells %s do not hold the level's own tiles in the map at "
         "map row %d -- the level-to-map mapping is not what section 2 assumes"
         % (badmap[:4], MAP_ROW0))
cage = ((MAP_ROW0 - max(rows)) * 8 - scy,
        (MAP_ROW0 - min(rows)) * 8 + 8 - scy,                # screen rows
        min(cols) * 8 - scx, (max(cols) + 1) * 8 - scx)      # screen cols
print("cage cells rows %d..%d cols %d..%d -> screen rows %d..%d cols %d..%d"
      % (min(rows), max(rows), min(cols), max(cols), cage[0], cage[1] - 1,
         cage[2], cage[3] - 1))

for face in (0, 1):
    px = FACE_PARK_X[face]
    # Ask for the facing first, with one forced update, then hold the tick high
    # again so the pose is settled before any pixel is read -- the facing is
    # only decided on the duck's own update now (section 3b), so a plain poke
    # does not turn it. The update moves the duck, so what it ended up beside is
    # read back rather than assumed: the pixels are this section's subject, the
    # turn itself is section 1's.
    park(px)
    setreg("wDuckTick", 1)
    tick(1)
    setreg("wDuckTick", 0xFF)
    want = 0 if px >= reg("wDuckX") else 1
    if reg("wDuckFace") != want:
        fail("Harry parked at x=%d (duck at %d) left it facing %d, expected %d"
             % (px, reg("wDuckX"), reg("wDuckFace"), want))
    # The rest of the body reads the bird the ROM says it drew -- the same
    # comparison, but on the value the update actually settled on.
    face = want
    # The cage alone. y = 191 gives an OAM row of 191-191 = 0, i.e. lines
    # -16..-1; the tick is held high, so nothing re-plants it while it is up
    # there. Captured an iteration, because Harry's own sprite sits somewhere
    # different for the second facing and the blank half compares against this.
    put_duck(DUCK_CAGE_X, 191)
    parked_tick(2, px)
    bg = pb.screen.ndarray[:, :, 0].copy()
    put_duck(DUCK_CAGE_X, DUCK_CAGE_Y)
    parked_tick(2, px)
    q = duck_oam()
    if reg("wDuckFace") != face:
        fail("parking Harry at x=%d left the duck facing %d, expected %d"
             % (px, reg("wDuckFace"), face))

    top = q[0][0] - 16
    left = q[0][1] - OAM_COL_OFFSET
    box = (top, top + 16, left, left + 16)
    print("face %d: duck box: screen rows %d..%d cols %d..%d"
          % (face, top, top + 15, left, left + 15))

    frame = pb.screen.ndarray[:, :, 0]
    sprite = duck_src[reg("wDuckFrame")]
    if face:
        # What is on screen is the emitted pose mirrored, because that is what
        # the X-flip draws. gbdata asserted the source's own left-facing pose is
        # the same mirror, so this compares the port's flipped output against
        # the art the Z80 would have drawn.
        sprite = gbdata.mirror_sprite(sprite)
    ink = {(box[0] + r, box[2] + c) for r in range(16) for c in range(16)
           if sprite[r * 2 + c // 8] >> (7 - c % 8) & 1}
    if len(ink) < 40:
        fail("the source frame has only %d ink pixels -- that is not a bird"
             % len(ink))
    shades = {int(frame[y][x]) for y, x in ink}
    print("  duck ink: %d px drawn as %s" % (len(ink), sorted(shades) or "nothing"))
    if len(shades) != 1:
        fail("facing %d: the duck's ink is %d shades on screen (%s), expected "
             "exactly one -- its art is not being drawn where its OAM box says"
             % (face, len(shades), sorted(shades)))
    else:
        shade = shades.pop()
        # The ink is opaque: whatever was behind it is gone. Only reported,
        # since a cage pixel that already wears the duck's shade cannot be told
        # apart.
        same = sum(1 for y, x in ink if int(bg[y][x]) == shade)
        if same:
            print("  (%d of them sit on cage pixels of the same shade)" % same)
    # The art's blank pixels are the sprite's colour 0, which is transparent:
    # the cage must be exactly as it was. This is the half that catches a duck
    # drawn a quadrant over, or with the wrong tile's art.
    blank = [(y, x) for y in range(box[0], box[1]) for x in range(box[2], box[3])
             if (y, x) not in ink]
    over = [(y, x) for y, x in blank if int(frame[y][x]) != int(bg[y][x])]
    if over:
        fail("facing %d: the duck paints over %d of the %d pixels its art "
             "leaves blank (e.g. %s): colour 0 is transparent and the cage "
             "should show there" % (face, len(over), len(blank), over[:4]))
    if not all(cage[0] <= y < cage[1] and cage[2] <= x < cage[3] for y, x in ink):
        ys = [y for y, _ in ink]
        xs = [x for _, x in ink]
        fail("facing %d: the duck is drawn at rows %d..%d cols %d..%d, outside "
             "the cage at rows %d..%d cols %d..%d"
             % (face, min(ys), max(ys), min(xs), max(xs), cage[0], cage[1] - 1,
                cage[2], cage[3] - 1))

# --- 3. The wing flap --------------------------------------------------------
# The Z80 toggles MotherDuckFrame in the DRAW path (Chuckie.asm:3481), so the
# caged duck flaps on every level -- which is what makes the flap checkable
# here, holding the duck still. Both the duck and Harry are re-poked every
# frame: a loose duck's chase would otherwise walk into him and start a death
# whose reload resets the pose and the tick under the count.
#
# The facing is settled before the count starts, with one forced update and
# Harry already parked where the loop holds him. It is settled on the duck's own
# clock now (section 3b), so section 2's turn would otherwise still be in force
# for the first DUCK_SPEED frames -- and the art carries the facing as well as
# the pose, so those frames would record a pose drawn two ways.
park()
put_duck(DUCK_CAGE_X, DUCK_CAGE_Y)
setreg("wDuckTick", 1)
tick(1)
setreg("wDuckTick", DUCK_SPEED)
poses, drawn = [], {}
for _ in range(CAGED_FRAMES):
    put_duck(DUCK_CAGE_X, DUCK_CAGE_Y)
    park()
    tick(1)
    p = reg("wDuckFrame")
    poses.append(p)
    drawn.setdefault(p, set()).add(tuple(x[2] for x in duck_oam()))
toggles = sum(1 for a, b in zip(poses, poses[1:]) if a != b)
want_updates = CAGED_FRAMES // DUCK_SPEED
print("flap: %d frames, pose toggled %d times (want ~%d), drew %s"
      % (CAGED_FRAMES, toggles, want_updates,
         {p: sorted(v) for p, v in sorted(drawn.items())}))
if set(poses) != {0, 1}:
    fail("the duck's pose took the values %s over %d frames, expected both 0 "
         "and 1 -- it is not flapping" % (sorted(set(poses)), CAGED_FRAMES))
if not want_updates - 2 <= toggles <= want_updates + 2:
    fail("the pose toggled %d times in %d frames, expected about %d -- one an "
         "update, DUCK_SPEED is %d" % (toggles, CAGED_FRAMES, want_updates,
                                       DUCK_SPEED))
for p, tiles in drawn.items():
    if len(tiles) != 1:
        fail("pose %d was drawn with more than one set of tiles (%s) -- the "
             "pose is not what picks the art" % (p, sorted(tiles)))
if len({next(iter(v)) for v in drawn.values()}) != 2:
    fail("both poses draw the same tiles (%s) -- there is no flap"
         % sorted(next(iter(v)) for v in drawn.values()))

# --- 3b. The whole bird steps on the duck's beat, and only then --------------
# "A wing beat and not a jitter", as far as a check can hold it. The facing used
# to be read off Harry on every DRAWN frame while the duck's x is frozen for
# DUCK_SPEED of them: walking Harry past a stationary duck turned it on a frame
# that was not one of its steps, so the bird moved twice per beat -- once for
# the wing and once for the turn. Everything about it is decided in UpdateDuck
# now, so the four tiles AND the flip bit change together, and only on a frame
# the duck itself updated.
#
# Harry is walked to the duck's other side and left there: that is the input the
# old drawing answered on the very next frame, and the one this must now hold
# for a whole period.
setreg("wDuckTick", DUCK_SPEED)
put_duck(DUCK_CAGE_X, DUCK_CAGE_Y)
park(PARK_X)                     # parked to its right, so it starts facing 0
parked_tick(1)


def bird():
    """The drawn bird: pose and facing, position left out."""
    return tuple(x[2:] for x in duck_oam())


before = bird()
setreg("wDuckTick", DUCK_SPEED)
changed = []
for _ in range(DUCK_SPEED + 2):
    put_duck(DUCK_CAGE_X, DUCK_CAGE_Y)
    park(DUCK_CAGE_X - 8)        # the other side of it, and stays
    tick(1)
    changed.append(bird() != before)
first = (changed.index(True) + 1) if any(changed) else None
print("beat: bird changed on frame %s of %d (DUCK_SPEED is %d)"
      % (first, DUCK_SPEED, DUCK_SPEED))
if first is None:
    fail("the drawn bird did not change once in %d frames -- it is not flapping"
         % (DUCK_SPEED + 2))
elif first != DUCK_SPEED:
    fail("the drawn bird changed on frame %d of a %d-frame beat -- something "
         "steps the duck on a frame that is not one of its own"
         % (first, DUCK_SPEED))
# Put Harry back where the sections before left him: section 5 measures the
# death window from wherever he is standing, and x=0 leaves no room for the
# window's left-hand cases.
park()

# --- 4. Caged: below the ninth level it does not move -------------------------
# The plant runs at the END of every update, after the chase and the bounds, so
# the duck's velocities churn while it sits still in the cage (Chuckie.asm:3475).
# The tick is set to a real DUCK_SPEED, so this is ten updates that had to be
# thrown away -- holding the tick high would have made it pass for the wrong
# reason, and section 6's roam is the same window on the level that keeps them.
#
# Level 8 is the interesting one: the port used to free her here, one level
# early, and the gate above is what says she is still caged.
level_index = reg("wCurrentLevel")
setreg("wDuckTick", DUCK_SPEED)
if level_index < DUCK_FREE_FROM:
    lives = reg("wLives")
    seen = set()
    for _ in range(CAGED_FRAMES):
        tick(1)
        seen.add(duck())
    print("level %d, %d frames: duck at %s" % (level_index + 1, CAGED_FRAMES,
                                               sorted(seen)))
    if seen != {(DUCK_CAGE_X, DUCK_CAGE_Y)}:
        fail("caged below level %d but moved: %s over %d frames"
             % (DUCK_FREE_FROM + 1, sorted(seen), CAGED_FRAMES))
    if reg("wLives") != lives:
        fail("a death reloaded the level inside the caged window (lives %d -> "
             "%d), so a duck that sat still afterwards proves nothing"
             % (lives, reg("wLives")))
else:
    print("level %d is the roaming one -- section 6" % (level_index + 1))

# --- 5. The death window, to the pixel ----------------------------------------
# Chuckie.asm:2545, walked over both edges on both axes. In the duck's own terms
# (duck - player) the window is x -7..+8 and y -9..+9: the x window is the Z80's
# `duck_x-8 <= player_x <= duck_x+7`, which is asymmetric, the y window is not.
# A one-off in any of the four reaches fails here.
setreg("wDuckTick", 0xFF)
px, py = reg("wPlayerX"), reg("wPlayerY")
CASES = [(0, 0, 1),
         (-(DUCK_REACH_X - 1), 0, 1), (-DUCK_REACH_X, 0, 0),   # player = duck+7 / duck+8
         (DUCK_REACH_X, 0, 1), (DUCK_REACH_X + 1, 0, 0),       # player = duck-8 / duck-9
         (0, -DUCK_REACH_Y, 1), (0, -DUCK_REACH_Y - 1, 0),
         (0, DUCK_REACH_Y, 1), (0, DUCK_REACH_Y + 1, 0)]
print("death window: player (%d,%d), the Z80's %d/%d reach"
      % (px, py, DUCK_REACH_X, DUCK_REACH_Y))
for dx, dy, want in CASES:
    put_duck(px + dx, py + dy)
    setreg("wPlayerDead", 0)
    setreg("wDeathTimer", 0)
    tick(1)
    got = reg("wPlayerDead")
    print("  duck %+3d,%+3d from him -> dead %d (want %d)" % (dx, dy, got, want))
    if got != want:
        fail("the duck at (%+d,%+d) from Harry set PlayerDead=%d, expected %d: "
             "the window is not the Z80's %d/%d reach"
             % (dx, dy, got, want, DUCK_REACH_X, DUCK_REACH_Y))
    if want and reg("wDeathTimer") != 90:
        fail("the duck's kill set DeathTimer=%d, expected the 90-frame freeze"
             % reg("wDeathTimer"))
setreg("wPlayerDead", 0)
setreg("wDeathTimer", 0)

# --- 6. The ninth level: it leaves the cage, inside the level -----------------
# The chase, watched: it must move, at the Z80's own rate, and never leave the
# bounds MoveMotherDuck reflects at. The rate is the thing not to rescale, so
# count the updates rather than just check for movement -- DUCK_SPEED is 12
# frames an update, so 400 frames is 33 of them.
if level_index >= DUCK_FREE_FROM:
    put_duck(DUCK_CAGE_X, DUCK_CAGE_Y)
    pb.memory[sym["wDuckVelX"]] = 0
    pb.memory[sym["wDuckVelY"]] = 0
    setreg("wDuckTick", DUCK_SPEED)
    pb.memory[wPlayerX], pb.memory[wPlayerY] = HARRY_START_X, HARRY_START_Y
    pb.memory[wPlayerInAir] = 0

    samples, updates = [], 0
    last = duck()
    for _ in range(ROAM_FRAMES):
        tick(1)
        now = duck()
        if now != last:
            updates += 1
            last = now
        samples.append((now[0], now[1], reg("wPlayerX"), reg("wDuckFace"),
                        reg("wDuckFrame")))
    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]
    moved = max(abs(x - DUCK_CAGE_X) for x in xs) + \
            max(abs(y - DUCK_CAGE_Y) for y in ys)
    print("level %d, %d frames: %d updates, x %d..%d y %d..%d, farthest from "
          "the cage %d px" % (level_index + 1, ROAM_FRAMES, updates, min(xs),
                              max(xs), min(ys), max(ys), moved))
    if not ROAM_FRAMES // DUCK_SPEED - 5 <= updates \
            <= ROAM_FRAMES // DUCK_SPEED + 3:
        fail("the duck updated %d times in %d frames, expected about %d "
             "(DUCK_SPEED is %d)" % (updates, ROAM_FRAMES,
                                     ROAM_FRAMES // DUCK_SPEED, DUCK_SPEED))
    if moved < 40:
        fail("level %d's duck stayed within %d px of the cage over %d frames -- "
             "it is still planted" % (level_index + 1, moved, ROAM_FRAMES))
    # The Z80 toggles MotherDuckFrame off the SAME counter that moves the duck
    # (Chuckie.asm:3481, in the draw path but gated by MotherDuckUpdateCounter),
    # so a pose change and a position change are one and the same frame. The
    # cadence in section 3 would still pass on a flap that had drifted off the
    # movement -- this is the half that would not.
    toggles = [i for i in range(1, len(samples))
               if samples[i][4] != samples[i - 1][4]]
    moves = [i for i in range(1, len(samples))
             if samples[i][:2] != samples[i - 1][:2]]
    if toggles != moves:
        off = next((i for i, (a, b) in enumerate(zip(toggles, moves)) if a != b),
                   min(len(toggles), len(moves)))
        fail("the pose toggled on %d frames and the duck moved on %d, first "
             "differing at %d -- the flap is not in step with the movement"
             % (len(toggles), len(moves), off))
    else:
        print("the flap is in step with the movement: %d pose toggles, every "
              "one on a frame the duck moved" % len(toggles))
    out = [s for s in samples
           if not (CAGE_COLS.start * 8 <= s[0] + 15
                   and s[0] < (CAGE_COLS.stop - 1) * 8 + 8
                   and CAGE_ROWS.start * 8 <= s[1] + 15
                   and s[1] < (CAGE_ROWS.stop - 1) * 8 + 8)]
    if not out:
        fail("the duck left the cage's pixels for %d px but its box was never "
             "outside the cage's own cells" % moved)
    else:
        print("first seen clear of the cage at %s" % (out[0][:2],))
    # The facing is decided in the duck's own update (section 3b), so an
    # every-frame comparison against Harry's x -- which this did, while the draw
    # re-read it each frame -- compares a held value against a moving one as soon
    # as the duck walks away from him. What is assertable is what the update
    # settled on, and that it is then held until the next one.
    beats = set(moves)
    settled = samples[0][3]
    for i, (x, y, pxx, face, _) in enumerate(samples):
        if not (0 <= x < DUCK_X_MAX and DUCK_Y_MIN <= y < DUCK_Y_MAX):
            fail("the duck reached (%d,%d), outside MoveMotherDuck's bounds "
                 "x<$%02X, $%02X<=y<$%02X" % (x, y, DUCK_X_MAX, DUCK_Y_MIN,
                                              DUCK_Y_MAX))
        if i in beats:
            settled = 0 if pxx >= x else 1
        if face != settled:
            fail("the duck at x=%d turned on frame %d, which is not one of its "
                 "beats -- Harry at x=%d, and the facing %s is %s"
                 % (x, i, pxx,
                    "this beat settled on" if i in beats else "the last beat "
                    "settled on", settled))
else:
    print("level %d is not the roaming one -- the caged sections above cover it"
          % (level_index + 1))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
