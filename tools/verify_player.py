#!/usr/bin/env python3
"""Assert Harry exists, is drawn where the camera says, and moves when driven.

Phase 3 check. Everything here is read back out of the running ROM -- OAM and
WRAM through PyBoy -- so it fails if the movement code, the camera or the
sprite blitter breaks, independently of what a screenshot happens to show.

    python3 tools/verify_player.py [rom.gb]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbdata  # noqa: E402
import harness  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"

# Must match src/main.asm. Not 182 any more: the tiles are compacted to the 20
# the levels reference, and Harry is loaded straight after them.
TILE_COUNT = 20
DIR_RIGHT, DIR_LEFT, DIR_CLIMB = 0x00, 0x04, 0x0D
SCX_MAX = 96                 # 256 - 160
IN_AIR_START = 0x8C          # InAirCounter set by DoJump


def symbols(path):
    """RGBDS .sym lines are `BB:AAAA Name`; section names are not in there."""
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wPlayerX", "wPlayerY", "wPlayerAnimFrame", "wPlayerDirection",
        "wPlayerInAir", "wInAirCounter", "wPlayerJumpDirection",
        "wFallingCounter", "wPlayerAirDirection", "wPlayerDead", "wHens"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

# Aliases for the ones the tests poke directly rather than through reg().
wPlayerX = sym["wPlayerX"]
wPlayerY = sym["wPlayerY"]
wPlayerInAir = sym["wPlayerInAir"]
wPlayerDirection = sym["wPlayerDirection"]
wHens = sym["wHens"]

# The spawn cell on level 1, which section 11 stands him back on. PlayLevel's
# $64/$17, not the image block's $AE/$37 -- see src/main.asm:184.
SPAWN_X, SPAWN_Y = 100, 23
HEN_NONE = 0xFF

pb = harness.boot(ROM)

failed = []
fail = failed.append


def reg(name):
    return pb.memory[sym[name]]


def oam(i):
    a = 0xFE00 + i * 4
    return tuple(pb.memory[a:a + 4])


def tick(n=1, buttons=()):
    for b in buttons:
        pb.button_press(b)
    for _ in range(n):
        pb.tick(1, True)
    for b in buttons:
        pb.button_release(b)


OAM_ROW_BASE = 191          # src/main.asm: PLAYFIELD_ROW_BASE + 16
OAM_COL_OFFSET = 8          # src/main.asm: a sprite's left edge is at OAM x - 8


def screen_pos():
    """Where Harry's top-left should be, from his position and the camera."""
    return (OAM_ROW_BASE - reg("wPlayerY") - pb.memory[0xFF42],
            (reg("wPlayerX") - pb.memory[0xFF43] + OAM_COL_OFFSET) & 0xFF)


def expected_tiles():
    """The four quadrant tiles for the current pose. Must match DrawHarry."""
    frame = reg("wPlayerAnimFrame")
    if reg("wPlayerDirection") == DIR_CLIMB:
        frame += 8            # our table packs the climb frames after the walks
    else:
        frame += reg("wPlayerDirection")
    return [TILE_COUNT + frame * 4 + i for i in range(4)]


# The LCD is switched on by our own code mid-frame, so the first VBlank handler
# has not run yet at the moment the readiness test passes. Let it run.
tick(2)

# --- 1. He is drawn, at the position the camera implies --------------------
x, y = reg("wPlayerX"), reg("wPlayerY")
scy, scx = pb.memory[0xFF42], pb.memory[0xFF43]
print("spawn: x=%d y=%d  camera SCY=%d SCX=%d  OAM0=(%d,%d) screen=(%d,%d)"
      % ((x, y, scy, scx) + oam(0)[:2] + (oam(0)[1], oam(0)[0] - 16)))
if oam(0)[:2] != screen_pos():
    fail("OAM0 is %s, expected %s (y=%d SCY=%d x=%d SCX=%d)"
         % (oam(0)[:2], screen_pos(), y, scy, x, scx))

# --- 2. All four quadrants are on screen, consecutive, laid out correctly ---
quad = [oam(i) for i in range(4)]
if [q[2] for q in quad] != expected_tiles():
    fail("quadrant tiles are %s, expected %s" % ([q[2] for q in quad],
                                                 expected_tiles()))
if not (quad[1][1] == quad[0][1] + 8 and quad[2][0] == quad[0][0] + 8
        and quad[3][1] == quad[2][1] + 8 and quad[3][0] == quad[1][0] + 8):
    fail("quadrants are not laid out TL/TR/BL/BR: %s" % (quad,))
if not (1 <= quad[0][1] and quad[1][1] <= 159 and 16 <= quad[0][0]
        and quad[3][0] <= 160):
    fail("Harry is partly off screen: %s" % (quad,))

# --- 2b. Every frame of his sprite sheet is in VRAM, pixel for pixel -------
# OAM names a tile index; nothing so far has checked that what is AT that index
# is Harry rather than level graphics. This walks the sheet the ROM loaded.
_, _, _, harry, _, _ = gbdata.build("reference/paulie/Chuckie.asm")
badtiles = []
for frame, sprite in enumerate(harry):
    for q, tile in enumerate(gbdata.sprite_tiles(sprite)):
        tid = TILE_COUNT + frame * 4 + q
        if tile != bytes(pb.memory[0x8000 + tid * 16:0x8000 + tid * 16 + 16]):
            badtiles.append((frame, q))
if badtiles:
    fail("%d of %d Harry tiles in VRAM do not match the source sprite: %s"
         % (len(badtiles), len(harry) * 4, badtiles[:4]))
print("Harry's sprite sheet: %d frames x 4 tiles in VRAM" % len(harry))


# --- 3. Walking right advances him, and the camera follows ----------------
start_x, start_scx = reg("wPlayerX"), pb.memory[0xFF43]
tick(30, ("right",))
tick(2)                      # let the camera catch up with the last move
walked = reg("wPlayerX")
print("hold right 30: x %d -> %d, SCX %d -> %d" % (start_x, walked, start_scx,
                                                   pb.memory[0xFF43]))
if walked - start_x < 25:
    fail("30 frames of right moved x only %d px" % (walked - start_x))
if reg("wPlayerDirection") != DIR_RIGHT:
    fail("wPlayerDirection is $%02X after walking right"
         % reg("wPlayerDirection"))
if oam(0)[:2] != screen_pos():
    fail("OAM0 %s does not track the camera %s" % (oam(0)[:2], screen_pos()))

# --- 4. The horizontal camera is x-72 clamped to 0..96, all the way down ---
# Walk back left far enough to leave the right-hand clamp, then check the
# formula holds at each end. It is checked against the x the ROM actually has,
# so a movement bug cannot mask a camera bug or the reverse.
tick(60, ("left",))
tick(2)
for label in ("after 60 more left",):
    x = reg("wPlayerX")
    want = max(0, min(SCX_MAX, x - 72))
    got = pb.memory[0xFF43]
    print("  %s: x=%d -> SCX %d (want %d)" % (label, x, got, want))
    if got != want:
        fail("SCX is %d at x=%d, expected %d" % (got, x, want))
if reg("wPlayerDirection") != DIR_LEFT:
    fail("wPlayerDirection is $%02X after walking left"
         % reg("wPlayerDirection"))

# --- 5. A starts a jump, with the counters the Z80's physics reads ---------
y_before = reg("wPlayerY")
tick(1, ("a",))
if reg("wPlayerInAir") != 2:
    fail("PlayerInAir is %d after A, expected 2" % reg("wPlayerInAir"))
if reg("wInAirCounter") != IN_AIR_START:
    fail("InAirCounter is $%02X after A, expected $%02X"
         % (reg("wInAirCounter"), IN_AIR_START))
if reg("wPlayerAirDirection") != 1:
    fail("PlayerAirDirection is $%02X after A, expected 1 (rising)"
         % reg("wPlayerAirDirection"))
if reg("wFallingCounter") != 0:
    fail("FallingCounter is $%02X after A, expected 0" % reg("wFallingCounter"))

# --- 6. He rises, then falls, then lands ----------------------------------
# The arc is a sequence of single-pixel steps, so sample it rather than just
# waiting for it to finish: a rise with no fall would otherwise pass.
peak, in_air, frames = y_before, True, 0
for _ in range(600):
    pb.tick(1, True)
    frames += 1
    peak = max(peak, reg("wPlayerY"))
    if reg("wPlayerInAir") == 0:
        in_air = False
        break
print("jump: y %d -> peak %d -> %d, landed after %d frames"
      % (y_before, peak, reg("wPlayerY"), frames))
if in_air:
    fail("never landed: PlayerInAir=%d after %d frames"
         % (reg("wPlayerInAir"), frames))
if peak - y_before != 11:
    # 11, not 12: the step that DETECTS the apex adds the +10 that wraps past
    # $FA, and moves him by PlayerAirDirection == 0. It costs a move.
    fail("jump rose %d px, expected 11" % (peak - y_before))
if reg("wPlayerY") >= peak:
    fail("landed at y=%d, which is not below the peak %d"
         % (reg("wPlayerY"), peak))

# --- 7. Landing snaps to the cell grid, as LandedOnFloor requires ----------
if (reg("wPlayerY") + 1) & 7:
    fail("landed at y=%d, which is not y+1 %% 8 == 0" % reg("wPlayerY"))
if reg("wPlayerInAir") != 0:
    fail("PlayerInAir is %d after landing" % reg("wPlayerInAir"))

# --- 8. He is still drawable and still moving after all that --------------
tick(10, ("right",))
tick(2)                      # both OAM and SCX are written at VBlank, from the
                             # x at that moment; let them catch up before comparing
if reg("wPlayerX") == walked:
    fail("x did not change after landing, movement is stuck")
if oam(0)[:2] != screen_pos():
    fail("OAM0 %s does not track the camera after landing" % (oam(0)[:2],))

# --- 9. Climbing: on a ladder, and x cell-aligned, up moves him up --------
# x must be a multiple of 8 and the cell one row above his head must be a
# ladder. Level row index rises with y, so climbing up walks up the table.
level = gbdata.build("reference/paulie/Chuckie.asm")[2][0]
LADDER = 1
ladder = next(((r, c) for r in range(3, 19) for c in range(1, 31)
               if level[r * 32 + c] == LADDER
               and level[(r + 1) * 32 + c] == LADDER), None)
if ladder is None:
    fail("no two-cell ladder found in level 1 to test against")
else:
    r, c = ladder
    pb.memory[wPlayerInAir] = 0
    pb.memory[wPlayerX] = c * 8          # cell-aligned, which climbing requires
    pb.memory[wPlayerY] = r * 8 - 1      # so the cell above is row r
    tick(1)
    if reg("wPlayerDirection") == DIR_CLIMB:
        fail("started climbing without UP held")
    climb_y = reg("wPlayerY")
    tick(4, ("up",))
    print("climb at ladder (row %d, col %d): y %d -> %d" % (r, c, climb_y,
                                                            reg("wPlayerY")))
    if reg("wPlayerY") != climb_y + 4:
        fail("4 frames of UP moved y %d, expected 4 (ladders are 1px a frame)"
             % (reg("wPlayerY") - climb_y))
    if reg("wPlayerDirection") != DIR_CLIMB:
        fail("wPlayerDirection is $%02X while climbing, expected $0D"
             % reg("wPlayerDirection"))
    if reg("wPlayerInAir") != 0:
        fail("PlayerInAir is %d while climbing, expected 0"
             % reg("wPlayerInAir"))
    if oam(0)[2] < TILE_COUNT + 32 or oam(0)[2] > TILE_COUNT + 47:
        fail("climb is drawn with tile %d, expected the climb frames %d..%d"
             % (oam(0)[2], TILE_COUNT + 32, TILE_COUNT + 47))

    # A ladder is two cells wide (LADDERLEFT's partner is LADDERRIGHT), and the
    # climber is two cells wide, so his sprite must cover exactly those cells.
    # Read from the level and the camera, never from the sprite transform: this
    # is the check that catches a sprite drawn half a cell left of the map, and
    # it is worth having on this axis because the transform's own +8 hid there
    # for the whole port -- invisible on an 8 px tile, glaring on a two-cell
    # ladder, where he hung off the left rail.
    sprite_left = oam(0)[1] - OAM_COL_OFFSET
    want_left = c * 8 - pb.memory[0xFF43]
    print("climbing: sprite screen cols %d..%d, his ladder cells %d..%d"
          % (sprite_left, sprite_left + 15, want_left, want_left + 15))
    if sprite_left != want_left:
        fail("the climber spans screen cols %d..%d but his ladder is at %d..%d "
             "-- %+d px off centre on it"
             % (sprite_left, sprite_left + 15, want_left, want_left + 15,
                sprite_left - want_left))

    # and back down
    down_y = reg("wPlayerY")
    tick(3, ("down",))
    if reg("wPlayerY") != down_y - 3:
        fail("3 frames of DOWN moved y %d, expected -3"
             % (reg("wPlayerY") - down_y))

# --- 10. Walking off an edge: a countdown, then a fall --------------------
# CheckForFalling starts this whenever x is NOT cell-aligned and there is
# nothing solid under his right foot -- the exact complement of climbing.
hole = next(((r, c) for r in range(4, 19) for c in range(1, 30)
             if level[(r - 2) * 32 + c + 1] == 0
             and level[(r - 2) * 32 + c + 2] == 0), None)
if hole is None:
    fail("no edge to walk off in level 1")
else:
    r, c = hole
    pb.memory[wPlayerInAir] = 0
    pb.memory[wPlayerDirection] = DIR_RIGHT
    pb.memory[wPlayerX] = c * 8 + 4      # deliberately NOT cell-aligned
    pb.memory[wPlayerY] = r * 8 - 1
    tick(1)
    print("step off edge at (row %d, col %d): PlayerInAir=%d" % (r, c,
                                                                 reg("wPlayerInAir")))
    if reg("wPlayerInAir") != 1:
        fail("PlayerInAir is %d after stepping over a hole, expected 1"
             % reg("wPlayerInAir"))
    fell = False
    for _ in range(200):
        pb.tick(1, True)
        if reg("wPlayerInAir") == 2 and reg("wPlayerAirDirection") == 0xFF:
            fell = True
            break
    if not fell:
        fail("never started falling: PlayerInAir=%d AirDirection=$%02X"
             % (reg("wPlayerInAir"), reg("wPlayerAirDirection")))

# --- 11. His feet are on the tile he is standing on -------------------------
# The property a player notices and no OAM check can see. A sprite's bottom row
# is OAM-1, so a player standing on a tile has that tile's TOP EDGE at exactly
# his OAM row: there is no gap between his feet and the ground.
#
# 6a displaced the playfield one map row to make room for the status band and
# left the sprite constant at its old value, so every sprite in the game floated
# 8 px above the tiles. Every check above still passed, because they all compare
# OAM against the same stale transform -- the disagreement is only ever visible
# on the screen. So this one reads the screen, and it needs no constant at all.
for s in range(5):
    pb.memory[wHens + s * 4] = HEN_NONE
pb.memory[wPlayerX] = SPAWN_X
pb.memory[wPlayerY] = SPAWN_Y
pb.memory[wPlayerInAir] = 0
pb.memory[sym["wInAirCounter"]] = 4
pb.memory[wPlayerDirection] = DIR_RIGHT
tick(3)

oam_row, oam_x = oam(0)[0], oam(0)[1]
# The cell the game says he stands on -- PlayerX is the sprite's left edge, so
# the cell is PlayerX's own, and this band is a whole tile wide rather than the
# 2 px his sprite box happens to share with it.
cell_left = (reg("wPlayerX") & ~7) - pb.memory[0xFF43]
band = range(cell_left, cell_left + 8)
frame = pb.screen.ndarray[:, :, 0]
ground = [r for r in range(oam_row, 144) if any(frame[r][c] for c in band)]
print("standing: OAM row %d, his cell at screen cols %d..%d; first drawn row "
      "below it: %s" % (oam_row, band.start, band.stop - 1, ground[:1]))
if not ground or ground[0] != oam_row:
    fail("his feet are at OAM row %d but the tile under him starts at row %s -- "
         "the sprite and the playfield disagree about where the ground is"
         % (oam_row, ground[0] if ground else "nowhere on screen"))

# --- 11b. A landing stops ON the tile, whatever the frame phase ------------
# The part of section 7 that only shows on a raised platform. AirPhysics replays
# PHYSICS_STEPS Spectrum iterations for one frame, and on the iteration he lands
# CheckBelow clears PlayerInAir -- the Z80 takes the ground path from the next
# iteration on. Replaying the fall regardless carried him up to 3 px into the
# platform he had already landed on, and left PlayerInAir clear at a y that is
# NOT y+1 % 8 == 0, which is a state nothing recovers from except a jump: the
# player sees Harry sunk into a platform he dropped onto. Section 7 lands him on
# the floor, where an overshoot has almost nothing below it to sink into and the
# frame usually ends first, so it passed throughout. Driving the same drop from
# all eight phases of the falling counter makes the sink deterministic.
PLATFORM = 5
ledge = next(((r, c) for r in range(2, 14) for c in range(1, 30)
              if level[r * 32 + c] == PLATFORM
              and level[r * 32 + c + 1] == PLATFORM
              and all(level[(r + d) * 32 + c + e] == 0
                      for d in range(1, 7) for e in (0, 1))), None)
if ledge is None:
    fail("no clear platform in level 1 to drop him onto")
else:
    r, c = ledge
    want = r * 8 + 23                 # the y a landing on row r must give
    sinks = {}
    for phase in range(8):
        pb.memory[wPlayerInAir] = 1
        pb.memory[sym["wPlayerAirDirection"]] = 0xFF
        pb.memory[sym["wPlayerJumpDirection"]] = 0
        pb.memory[sym["wInAirCounter"]] = 0x28
        pb.memory[sym["wFallingCounter"]] = phase
        pb.memory[wPlayerX] = c * 8   # cell-aligned, so nothing else moves him
        pb.memory[wPlayerY] = want + 40
        pb.memory[sym["wPlayerDead"]] = 0
        for _ in range(400):
            pb.tick(1, True)
            if reg("wPlayerInAir") == 0:
                break
        sinks[phase] = reg("wPlayerY") - want
    print("drop onto the platform at (row %d, col %d), landing y should be "
          "%d; sink by frame phase: %s"
          % (r, c, want, [sinks[p] for p in sorted(sinks)]))
    if any(sinks.values()):
        fail("a landing on row %d stopped %s px past it (one entry per frame "
             "phase) -- the frame's physics replay does not stop when he lands"
             % (r, [sinks[p] for p in sorted(sinks)]))
    if reg("wPlayerDead"):
        fail("the drop onto the platform killed Harry")

# --- 12. Falling through a hole in the floor kills him ----------------------
# The Z80 leaves the level from under the floor: `POP HL / POP HL / RET` unwinds
# past MainLoop -- which was entered by JP and so has no return address of its
# own -- back to the frame after `CALL PlayLevel`, and that code sends a player
# with eggs left to LoseLife. The port used to stop him there instead, which
# soft-locked him: PlayerInAir stayed 2, so he could neither jump nor walk, and
# no death ever came.
pb.memory[sym["wPlayerDead"]] = 0
pb.memory[wPlayerInAir] = 2
pb.memory[sym["wPlayerAirDirection"]] = 0xFF  # falling
pb.memory[sym["wInAirCounter"]] = 0x28        # the floor the fall bottoms out at
pb.memory[sym["wFallingCounter"]] = 1         # so the very next step is a move
pb.memory[wPlayerY] = 8                      # under the floor: y + $FF < $10
dead_at = None
for i in range(5):
    pb.tick(1, True)
    if reg("wPlayerDead"):
        dead_at = i + 1
        break
print("fell under the floor: y=%d InAir=%d Dead=%d (after %s frames)"
      % (reg("wPlayerY"), reg("wPlayerInAir"), reg("wPlayerDead"), dead_at))
if not reg("wPlayerDead"):
    fail("falling under the floor killed nobody: PlayerY=%d PlayerInAir=%d"
         % (reg("wPlayerY"), reg("wPlayerInAir")))
elif reg("wPlayerY") != 8:
    fail("the fall to his death moved him to y=%d, expected to stop at 8"
         % reg("wPlayerY"))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
