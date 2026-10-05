#!/usr/bin/env python3
"""Assert the hens are in the ROM, drawn, moving, and lethal.

Phase 4 check. The one PLAN.md names is the death path; everything before it is
what has to be true for the death path to mean anything (a collision predicate
that fires unconditionally would pass the death check on its own).

    python3 tools/verify_hens.py [rom.gb]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbdata  # noqa: E402
import harness  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"

# Must match src/main.asm. Tiles are compacted to the 20 the levels use; Harry
# follows them, the hens follow Harry.
TILE_COUNT = 20
HARRY_FRAMES, HARRY_FRAME_TILES = 12, 4
HEN_TILE_BASE = TILE_COUNT + HARRY_FRAMES * HARRY_FRAME_TILES
HEN_MAX = 5
HEN_NONE = 0xFF
DEATH_DELAY = 90
HARRY_START_X, HARRY_START_Y = 100, 23   # PlayLevel's $64/$17; src/main.asm:184
OBP1 = 0x10                   # attribute bit 4: draw this with OBP1

HEN_LEFT, HEN_RIGHT, HEN_DOWN, HEN_UP, HEN_PECK = 1, 2, 3, 4, 6


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wPlayerX", "wPlayerY", "wPlayerInAir", "wPlayerDead", "wDeathTimer",
        "wHens", "wHenTick", "wHenFrameCtr", "wCurrentHen"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

wHens = sym["wHens"]
wPlayerX, wPlayerY = sym["wPlayerX"], sym["wPlayerY"]
wPlayerDead = sym["wPlayerDead"]

pb = harness.boot(ROM)

failed = []
fail = failed.append


def reg(name):
    return pb.memory[sym[name]]


def oam(i):
    a = 0xFE00 + i * 4
    return tuple(pb.memory[a:a + 4])


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def hen(slot):
    a = wHens + slot * 4
    return tuple(pb.memory[a:a + 4])


def put_hen(slot, x, y, d, anim=0):
    a = wHens + slot * 4
    pb.memory[a:a + 4] = [x, y, d, anim]


gbdata_ = gbdata.build("reference/paulie/Chuckie.asm")
_, _, levels, harry, hens, hentable = gbdata_

# The LCD comes on mid-frame; the first VBlank handler has not run yet.
tick(2)

# --- 1. The level's hens are loaded, at the positions HenStarts gives ------
spawn = hentable[0]
live = [s for s in range(HEN_MAX) if hen(s)[0] != HEN_NONE]
print("spawn: %d live slots %s, records %s" % (len(live), live,
                                               [hen(s) for s in live]))
if len(live) != len(spawn):
    fail("level 1 has %d live hens, HenStarts says %d" % (len(live), len(spawn)))
for s, rec in zip(live, spawn):
    if hen(s)[:3] != rec[:3]:
        fail("hen slot %d is %s, HenStarts says %s" % (s, hen(s), rec))
if hen(HEN_MAX - 1)[0] != HEN_NONE:
    fail("slot %d should be empty, got x=%d" % (HEN_MAX - 1, hen(HEN_MAX - 1)[0]))

# --- 2. Every hen frame is in VRAM, pixel for pixel ------------------------
# The whole reason this is here: the hen base address was wrong once and read
# as plausible garbage, so OAM naming a tile proves nothing on its own.
badtiles = []
for frame, sprite in enumerate(hens):
    for q, tile in enumerate(gbdata.sprite_tiles(sprite)):
        tid = HEN_TILE_BASE + frame * 4 + q
        if tile != bytes(pb.memory[0x8000 + tid * 16:0x8000 + tid * 16 + 16]):
            badtiles.append((frame, q))
if badtiles:
    fail("%d of %d hen tiles in VRAM do not match the source sprite: %s"
         % (len(badtiles), len(hens) * 4, badtiles[:4]))
print("hen sprite sheet: %d frames x 4 tiles in VRAM" % len(hens))

# ...and the frames the draw uses must start their ink at column 0. DrawOneHen
# puts the whole 16px sprite at the hen's own x, so a frame whose ink starts
# further right is standing 4px off that x -- which is what the Z80's art for
# the walk and climb pairs does, on purpose: its sprite writes are byte-aligned
# (x >> 3), so it draws the +4 copy whenever the hen's x is at the half cell.
# Left in, a climbing hen parked 4px off its ladder for the whole climb (which
# is how it was found) and a wandering one jittered as the cycle alternated,
# since only the +4 half of it was displaced. Checked on the sprite sheet rather
# than on a screen pixel, so it fails on the art and not on catching a hen
# mid-step.
off = {f: min(c for c in range(16)
              if any(row >> (15 - c) & 1 for row in
                      ((sp[r * 2] << 8) | sp[r * 2 + 1] for r in range(16))))
       for f, sp in enumerate(hens) if f not in (6, 7)}
bad = {f: c for f, c in off.items() if c}
if bad:
    fail("hen frames %s start their ink %s px into the window, so they draw "
         "that far right of the hen's own x -- the Z80's x&4 shift is back in "
         "the art (see gbdata.py, HEN_SHIFTED)"
         % (sorted(bad), [bad[f] for f in sorted(bad)]))

# --- 3. Each live hen is four OAM entries, on OBP1, laid out TL/TR/BL/BR ---
def oam_quad(slot):
    return [oam(4 + slot * 4 + i) for i in range(4)]


for s in live:
    q = oam_quad(s)
    if [e[3] for e in q] != [OBP1] * 4:
        fail("hen %d attributes are %s, expected all $%02X (OBP1)"
             % (s, [e[3] for e in q], OBP1))
    if any(not (HEN_TILE_BASE <= e[2] < HEN_TILE_BASE + len(hens) * 4)
           for e in q):
        fail("hen %d is drawn with tiles %s, outside %d..%d"
             % (s, [e[2] for e in q], HEN_TILE_BASE,
                HEN_TILE_BASE + len(hens) * 4 - 1))
    if not (q[1][1] == q[0][1] + 8 and q[2][0] == q[0][0] + 8
            and q[3][1] == q[2][1] + 8 and q[3][0] == q[1][0] + 8):
        fail("hen %d quadrants are not TL/TR/BL/BR: %s" % (s, q))
    # The four tiles of one frame are consecutive, in quadrant order.
    if [e[2] for e in q] != [q[0][2], q[0][2] + 1, q[0][2] + 2, q[0][2] + 3]:
        fail("hen %d tiles are %s, expected four consecutive from %d"
             % (s, [e[2] for e in q], q[0][2]))

# --- 4. Where a hen is drawn is where the camera puts it -------------------
# Harry's transform in the COLUMN and its own in the ROW: a hen's y is the level
# pixel its feet stand on, not the top of its sprite, so its OAM row is
# HEN_OAM_ROW_BASE - (y+SCY) with a base 15 lower than Harry's. Both bases are
# derived in src/main.asm from PLAYFIELD_ROW_BASE -- do not hardcode them here
# without checking that chain, which is exactly how 6a shipped sprites 8 px off
# with every check green. A hen left of the camera lands at 232..255, which is
# where the hardware hides it -- DrawHens does no clipping of its own, and this
# is the test that would catch a clip being added. Both of level 1's hens are in
# view at the spawn camera now (SCX 28), so section 4 covers the on-screen case
# here and the wrap case only where a hen really is behind him.
OAM_ROW_BASE = 191
OAM_COL_OFFSET = 8          # src/main.asm: an OAM column is a screen column + 8
HEN_OAM_ROW_BASE = OAM_ROW_BASE - 15   # src/main.asm: a hen's y is its FEET,
                                       # so its top edge is 15 lines lower
for s in live:
    x, y = hen(s)[0], hen(s)[1]
    # Both subtractions are 8-bit and wrap, as they do for Harry. A hen left of
    # the camera therefore lands at 232..255, which is where the hardware
    # hides it -- DrawHens does no clipping of its own.
    want = ((HEN_OAM_ROW_BASE - y - pb.memory[0xFF42]) & 0xFF,
            (x + OAM_COL_OFFSET - pb.memory[0xFF43]) & 0xFF)
    got = oam(4 + s * 4)[:2]
    print("  hen %d at (%d,%d) -> OAM %s (camera implies %s)" % (s, x, y, got, want))
    if got != want:
        fail("hen %d OAM is %s, camera says %s" % (s, got, want))

# --- 4b. A hen stands ON the tile its record names, and covers its cells ----
# The property the player sees, and the one section 4 cannot check: it compares
# OAM against the transform, so it agrees with the transform whatever it says.
# HenStarts' y is the pixel the hen STANDS on while PlayerY is the sprite's TOP,
# so drawing a hen with Harry's formula sank it 15 px into the platform it was
# walking on -- head where its body should be. Invisible on the flat, obvious on
# a platform, and the spawn data proves the reading: 21 of the 26 hen starts
# across the eight levels stand exactly on a platform or ladder cell at row
# (y-1)/8; read as the head, none of them do. So this test reads the level and
# the screen and uses no transform at all: the top edge of the platform a hen
# stands on must be the first drawn screen row below its sprite. The column half
# below is verify_player.py section 9's ladder check, on a hen.
PLATFORM = 5
for s in range(HEN_MAX):
    put_hen(s, HEN_NONE, 0, HEN_RIGHT)
pb.memory[wPlayerX], pb.memory[wPlayerY] = HARRY_START_X, HARRY_START_Y
pb.memory[sym["wPlayerInAir"]] = 0
tick(2)
scx, scy = pb.memory[0xFF43], pb.memory[0xFF42]
level = levels[0]


def hen_on_screen(r, c):
    """A platform cell a parked hen can stand on, clear of the HUD and of Harry."""
    left = c * 8 - scx
    sprite_row = HEN_OAM_ROW_BASE - (r * 8 + 8) - scy
    return (0 <= left and left + 15 <= 159              # wholly on screen
            and 24 <= sprite_row <= 128                 # wholly below the band
            and abs(c * 8 - reg("wPlayerX")) > 40)      # no collision


stand = next(((r, c) for r in range(2, 15) for c in range(1, 28)
              if level[r * 32 + c] == PLATFORM
              and level[r * 32 + c + 1] == PLATFORM
              and not any(level[(r + d) * 32 + c + e]
                          for d in (1, 2) for e in (0, 1))
              and hen_on_screen(r, c)), None)
if stand is None:
    fail("no clear platform on screen in level 1 to stand a hen on")
else:
    r, c = stand
    tick_before = reg("wHenTick")
    pb.memory[sym["wHenTick"]] = 0xFF   # else the round-robin walks it off again
    put_hen(0, c * 8, r * 8 + 8, HEN_RIGHT)   # y = the platform's top edge + 1
    tick(2)
    row, col = oam(4)[0], oam(4)[1]
    want_left = c * 8 - pb.memory[0xFF43]
    sprite_left = col - OAM_COL_OFFSET
    band = range(want_left, want_left + 8)
    frame = pb.screen.ndarray[:, :, 0]
    ground = [y for y in range(row, 144) if any(frame[y][x] for x in band)]
    print("hen standing at (row %d, col %d), feet y=%d: OAM %s, sprite screen "
          "cols %d..%d (the platform cell is %d..%d); first drawn row below it: "
          "%s" % (r, c, r * 8 + 8, (row, col), sprite_left, sprite_left + 15,
                  want_left, want_left + 15, ground[:1]))
    if sprite_left != want_left:
        fail("the hen spans screen cols %d..%d but the platform cell it stands "
             "on is at %d..%d -- %+d px off it"
             % (sprite_left, sprite_left + 15, want_left, want_left + 15,
                sprite_left - want_left))
    if not ground or ground[0] != row:
        fail("the hen's feet are at OAM row %d but the platform under it starts "
             "at row %s -- the record is anchored at the hen's head, not its "
             "feet" % (row, ground[0] if ground else "nowhere on screen"))
    if reg("wPlayerDead"):
        fail("the standing test killed Harry")

# Sections 6-9 walk the `live` slots round-robin and count their steps, so hand
# the spawn state back rather than leaving them parked: an empty slot sits still
# and reads as a hen that has stopped moving.
for s, rec in zip(live, spawn):
    put_hen(s, *rec)
pb.memory[sym["wHenTick"]] = tick_before

# --- 5. The frame chosen for each direction, driven directly ---------------
# Write the record, let one frame draw it, read the tile back. The walk cycle
# comes from the record's 4th byte, which is our own choice; the rest is the
# source's table (0/1 standing, 2/3 climbing, 4/5 walking, 6/7 eating).
CASES = [
    (HEN_LEFT, 0, 0), (HEN_LEFT, 1, 4),
    (HEN_RIGHT, 0, 1), (HEN_RIGHT, 1, 5),
    (HEN_DOWN, 0, 2), (HEN_DOWN, 1, 3),
    (HEN_UP, 0, 2), (HEN_UP, 1, 3),
    (HEN_PECK + HEN_LEFT, 0, 0), (HEN_PECK + HEN_RIGHT, 7, 1),
]
for d, anim, frame in CASES:
    put_hen(0, 0x40, 0x40, d, anim)
    tick(1)
    want = HEN_TILE_BASE + frame * 4
    got = oam(4)[2]
    if got != want:
        fail("dir %d anim %d drew tile %d, expected frame %d (tile %d)"
             % (d, anim, got, frame, want))
print("frame table: %d direction/anim cases" % len(CASES))

# --- 6. A hen moves, at the Z80's rate, without any input -------------------
# The rate is the thing not to rescale, so count steps rather than just check
# for movement: HenUpdateSpeed reloads to 3 and each expiry advances ONE of the
# five slots, so a given hen steps once per 15 frames. Over 150 frames that is
# 10 steps; the ±1 is the round-robin phase, not slack in the constant -- 2x or
# 3x off would come out at 20 or 30.
STEPS_WINDOW, STEPS_WANT = 150, 10
steps = {s: 0 for s in live}
last = {s: hen(s) for s in live}
for _ in range(STEPS_WINDOW):
    tick(1)
    for s in live:
        if hen(s) != last[s]:
            steps[s] += 1
            last[s] = hen(s)
print("%d idle frames: %s steps (expected %d each)"
      % (STEPS_WINDOW, steps, STEPS_WANT))
for s in live:
    if not STEPS_WANT - 1 <= steps[s] <= STEPS_WANT + 1:
        fail("hen %d took %d steps in %d frames, expected %d (HEN_SPEED * HEN_MAX)"
             % (s, steps[s], STEPS_WINDOW, STEPS_WANT))
if reg("wPlayerDead"):
    fail("Harry died while nobody was touching anything")

# --- 7. The collision predicate: a distant hen is not a collision ----------
# Half of this test is that the near case below fires; without this one, a
# predicate that always returns true passes.
px, py = reg("wPlayerX"), reg("wPlayerY")
put_hen(0, px + 60, py - 10, HEN_RIGHT)
put_hen(1, HEN_NONE, 0, HEN_RIGHT)
tick(2)
print("hen 60px to the right: PlayerDead=%d" % reg("wPlayerDead"))
if reg("wPlayerDead"):
    fail("collided with a hen 60px away (player_x=%d hen_x=%d)"
         % (px, reg("wHens")))

# --- 8. ...and a hen on top of him is -------------------------------------
put_hen(0, px, py - 10, HEN_RIGHT)
tick(2)
print("hen on Harry: PlayerDead=%d DeathTimer=%d"
      % (reg("wPlayerDead"), reg("wDeathTimer")))
if not reg("wPlayerDead"):
    fail("no collision with a hen at the player's own position "
         "(player=(%d,%d) hen=%s)" % (px, py, hen(0)))
if reg("wDeathTimer") == 0:
    fail("PlayerDead is set but DeathTimer is 0, so the freeze is over already")

# --- 9. The death path ends: freeze, then the level restarts ---------------
# Everything must be back to the spawn state, hens included -- the Z80 reloads
# them through PlayLevel, which is what ResetHens stands in for.
restarted = False
for _ in range(DEATH_DELAY + 20):
    tick(1)
    if not reg("wPlayerDead"):
        restarted = True
        break
print("after the freeze: PlayerDead=%d player=(%d,%d) hens=%s"
      % (reg("wPlayerDead"), reg("wPlayerX"), reg("wPlayerY"),
         [hen(s) for s in live]))
if not restarted:
    fail("still dead after %d frames, the freeze never ends" % (DEATH_DELAY + 20))
if (reg("wPlayerX"), reg("wPlayerY")) != (HARRY_START_X, HARRY_START_Y):
    fail("restarted with player at (%d,%d), expected (%d,%d)"
         % (reg("wPlayerX"), reg("wPlayerY"), HARRY_START_X, HARRY_START_Y))
for s, rec in zip(live, spawn):
    if hen(s)[:3] != rec[:3]:
        fail("hen slot %d restarted at %s, HenStarts says %s"
             % (s, hen(s), rec))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
