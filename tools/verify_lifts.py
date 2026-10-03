#!/usr/bin/env python3
"""Assert the lifts match the Z80's elevators, and that Harry can ride one.

Phase 4 check. The Z80's lift block is small but has no obvious seam: two
platforms share a column 64 px apart, each wraps on its own, and the ride is a
pixel every second tick that also ends the whole tick once Harry passes the top.
Everything here is read back out of the running ROM, and the negative cases
(a platform far away in x, a level with no platforms) are here because a
landing test that always fires would otherwise pass.

    python3 tools/verify_lifts.py build/l3.gb        # a level with lifts
    python3 tools/verify_lifts.py build/l1.gb        # a level without
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"

LIFT_NONE = 0xFF
LIFT_HOME = 3
LIFT_TOP = 0xA6
LIFT_OFFSET = 64
LIFT_STAND = 17
LIFT_CEILING = 0xA5
LIFT_SPEED = 2                             # ticks between 1 px steps
LIFT_CYCLE = LIFT_TOP - LIFT_HOME          # 163: the values YPos cycles through
HEN_MAX = 5
LIFT_OAM = 4 + HEN_MAX * 4
LIFT_TILE_BASE = 20 + 12 * 4 + 8 * 4       # tiles, Harry, hens
LIFT_OBP = 0x10
DIR_RIGHT, DIR_LEFT = 0x00, 0x04

# The Z80's table at $9787, records 0..8 as x bytes; $FF is "no lifts here".
# Records 1 and 8 are empty, so 1-based levels 3..7 are the ones with platforms.
TABLE = [LIFT_NONE, LIFT_NONE, 64, 144, 200, 120, 240, LIFT_NONE]


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wLiftX", "wLiftYPos", "wLiftTick", "wPlayerOnLift", "wPlayerX",
        "wPlayerY", "wPlayerInAir", "wInAirCounter", "wPlayerJumpDirection",
        "wPlayerDirection", "wPlayerDead", "wPad", "LiftXTable"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

failed = []
fail = failed.append


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def lift_pos(i):
    return pb.memory[sym["wLiftYPos"] + i]


def ypos():
    return lift_pos(0), lift_pos(1)


def set_ypos(a, b):
    pb.memory[sym["wLiftYPos"]] = a
    pb.memory[sym["wLiftYPos"] + 1] = b


def oam(i):
    a = 0xFE00 + i * 4
    return tuple(pb.memory[a:a + 4])


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def reset(x, y, direction, on_lift=0, in_air=0, jump_dir=1, in_air_ctr=4,
          yp0=None, yp1=None, gate=0):
    """Put Harry and the platforms somewhere definite.

    The state machine is sticky by design, so every case starts from an explicit
    one rather than from the last one's leftovers. gate=0 holds the platforms
    still for the tick that follows, so a test that reads a position back gets
    the one it wrote.

    Writing state between frames is safe because the main loop now runs the tick
    in the visible part of the frame: when the tick ran inside VBlank instead, it
    crossed the frame boundary an emulator steps on, and the writes landed part
    way through it -- which looks exactly like a landing test that does not fire.
    """
    if yp0 is not None:
        set_ypos(yp0, yp1)
    setreg("wPlayerX", x)
    setreg("wPlayerY", y)
    setreg("wPlayerDirection", direction)
    setreg("wPlayerJumpDirection", jump_dir)
    setreg("wPlayerInAir", in_air)
    setreg("wInAirCounter", in_air_ctr)
    setreg("wPlayerOnLift", on_lift)
    setreg("wLiftTick", gate if gate else LIFT_SPEED)


# --- 1. The table in the image is the Z80's table, records and all ---------
# Read straight out of the ROM: this is a data lift, and the whole point of
# lifting it is that nobody retypes a record.
with open(ROM, "rb") as f:
    rom = f.read()
got = list(rom[sym["LiftXTable"]:sym["LiftXTable"] + len(TABLE)])
print("LiftXTable: %s (want %s)" % (got, TABLE))
if got != TABLE:
    fail("LiftXTable is %s, the Z80's records say %s" % (got, TABLE))

pb = harness.boot(ROM)
tick(2)

# The x is unique per level except for the two empty records, which are the same
# byte -- and the empty case is decided by the byte itself, below.
column = reg("wLiftX")
level = TABLE.index(column) + 1 if column in TABLE[2:] else 1

# --- 2. A level with no lifts has none: nothing drawn, nothing catches ------
if column == LIFT_NONE:
    print("level %d: wLiftX=$%02X (no lifts)" % (level, column))
    # The heights still count up -- the Z80's counter runs whatever the level is,
    # and the port mirrors that. What must not happen here is a platform on
    # screen or one that catches Harry, so the test is those two, not the values
    # nothing reads.
    for _ in range(20):
        tick(1)
        bad = [oam(LIFT_OAM + i) for i in range(4) if oam(LIFT_OAM + i)[0] != 0]
        if bad:
            fail("lift OAM entries are not hidden: %s" % bad)
            break
    print("lift OAM entries 24..27 hidden: %s"
          % [oam(LIFT_OAM + i) for i in range(4)])
    # The column the table would have used on a level that had one.
    reset(64, 32, DIR_RIGHT, in_air=1)
    tick(1)
    print("falling at the empty column x=64: OnLift=%d" % reg("wPlayerOnLift"))
    if reg("wPlayerOnLift"):
        fail("landed on a lift that this level does not have")
    pb.stop(save=False)
    for f in failed:
        print("FAIL:", f)
    print("RESULT:", "FAIL" if failed else "PASS")
    sys.exit(1 if failed else 0)

# --- 3. The level's column, and the two platforms' 64 px spacing ------------
x = reg("wLiftX")
want_x = TABLE[level - 1]
print("level %d: lift column x=%d (table says %d), YPos=%s"
      % (level, x, want_x, ypos()))
if x != want_x:
    fail("level %d has its lifts at x=%d, the table says %d" % (level, x, want_x))
# Each platform wraps at LIFT_TOP back to LIFT_HOME on its own, which is what
# keeps them exactly LIFT_OFFSET apart for good: the second is either 64 above
# the first or a cycle less, and never anything else.
spacing = (lift_pos(1) - lift_pos(0)) % LIFT_CYCLE
if spacing != LIFT_OFFSET:
    fail("the platforms are %d apart, expected %d (mod %d)"
         % (spacing, LIFT_OFFSET, LIFT_CYCLE))

# --- 4. One pixel every two frames, both platforms together -----------------
# Measured mod the cycle: over 200 frames a platform wraps at least once, and a
# wrap is exactly a cycle, so this counts steps without caring where it wrapped.
WINDOW = 200
before = ypos()
tick(WINDOW)
after = ypos()
print("%d frames: YPos %s -> %s" % (WINDOW, before, after))
for i in (0, 1):
    moved = (after[i] - before[i]) % LIFT_CYCLE
    if not WINDOW // 2 - 1 <= moved <= WINDOW // 2 + 1:
        fail("platform %d rose %d px in %d frames, expected %d (1 px per 2)"
             % (i, moved, WINDOW, WINDOW // 2))
if (after[1] - after[0]) % LIFT_CYCLE != LIFT_OFFSET:
    fail("the platforms drifted apart: %s" % (after,))

# --- 5. Wrapping: past LIFT_TOP a platform restarts at LIFT_HOME ------------
# One forced gate tick, so this asserts the wrap rather than when it lands.
set_ypos(LIFT_TOP - 1, LIFT_TOP - 1)
setreg("wLiftTick", 1)
tick(1)
print("YPos %d + one tick: %s (want %s)"
      % (LIFT_TOP - 1, ypos(), (LIFT_HOME, LIFT_HOME)))
if ypos() != (LIFT_HOME, LIFT_HOME):
    fail("YPos %d -> %s, expected both to restart at %d"
         % (LIFT_TOP - 1, ypos(), LIFT_HOME))

# --- 6. Where a platform is drawn is where YPos says -----------------------
# Pinned to Harry's own sprite rather than to a row number: while he rides, the
# platform's top entry must be exactly his feet -- 16 rows below his own top
# entry, which is the row his sprite ends on. A constant written here by hand
# cannot catch an anchor that is wrong by a few pixels; this can, and a platform
# he hovers beside is exactly what a wrong anchor looks like. The pair is put
# back LIFT_OFFSET apart first, or the wrap above would have them drawn on top
# of each other and one row would pass twice.
yp = 40
# gate=1, not the default: it leaves the tick at 1, so the frame read below is
# one the platforms *moved* on. That is the frame a tear would show on -- one
# half of a platform drawn from the new YPos and one from the old -- so it is
# the frame worth reading. (The two-tick read this replaces was working around
# the draw pass overrunning VBlank, since fixed: the whole pass now ends 440
# cycles inside the window and there is nothing to read around.)
reset(x, yp + LIFT_STAND, DIR_RIGHT, on_lift=1, yp0=yp, yp1=yp + LIFT_OFFSET,
      gate=1)
tick(1)
y0, y1 = ypos()
scy, scx = pb.memory[0xFF42], pb.memory[0xFF43]
harry_row = oam(0)[0]
print("riding at YPos=%d: Harry OAM row %d, feet %d" % (yp, harry_row,
                                                        harry_row + 15))
for i, plat in enumerate((y0, y1)):
    # The one he is standing on is at his feet; the other is exactly as far
    # above it as its YPos is above that one's.
    row = harry_row + 15 - (plat - y0)
    want = [(row, (x + 8 - scx) & 0xFF), (row, (x + 16 - scx) & 0xFF)]
    got = [oam(LIFT_OAM + i * 2), oam(LIFT_OAM + i * 2 + 1)]
    print("  platform %d YPos=%d -> OAM %s (want %s, %d rows above his feet)"
          % (i, plat, got, want, plat - y0))
    if [g[:2] for g in got] != want:
        fail("platform %d OAM is %s, expected %s" % (i, got, want))
    if [g[2] for g in got] != [LIFT_TILE_BASE] * 2:
        fail("platform %d is drawn with tiles %s, expected %d"
             % (i, [g[2] for g in got], LIFT_TILE_BASE))
    if [g[3] for g in got] != [LIFT_OBP] * 2:
        fail("platform %d attributes are %s, expected $%02X"
             % (i, [g[3] for g in got], LIFT_OBP))

# --- 7. Falling into the band lands Harry on it ----------------------------
# y within YPos+10..15 and x within lift_x-9..lift_x+9; the landing snaps him
# to YPos+17, two pixels above the band, and clears the in-air state.
yp = 20
reset(x + 8, yp + 12, DIR_RIGHT, in_air=1, yp0=yp, yp1=LIFT_NONE)
tick(1)
print("falling onto the platform at YPos %d: PlayerY=%d OnLift=%d InAir=%d"
      % (yp, reg("wPlayerY"), reg("wPlayerOnLift"), reg("wPlayerInAir")))
if reg("wPlayerOnLift") != 1:
    fail("did not land on a platform at x=%d y=%d (player x=%d y=%d)"
         % (x, yp + 12, reg("wPlayerX"), reg("wPlayerY")))
elif reg("wPlayerY") - lift_pos(0) != LIFT_STAND:
    fail("landed %d px above the platform, expected %d"
         % (reg("wPlayerY") - lift_pos(0), LIFT_STAND))
if reg("wPlayerInAir") != 0:
    fail("landed but PlayerInAir is %d" % reg("wPlayerInAir"))

# --- 8. Riding: one pixel every two frames, with the platform --------------
# The offset is the thing that matters: if the ride and the platform rise at
# different rates Harry slides off a platform he is standing on.
y0, p0 = reg("wPlayerY"), lift_pos(0)
tick(20)
print("riding 20 frames: PlayerY %d -> %d, YPos %d -> %d"
      % (y0, reg("wPlayerY"), p0, lift_pos(0)))
if reg("wPlayerY") - y0 != 10:
    fail("rode %d px in 20 frames, expected 10" % (reg("wPlayerY") - y0))
if reg("wPlayerY") - lift_pos(0) != LIFT_STAND:
    fail("on the platform the offset is %d, expected %d"
         % (reg("wPlayerY") - lift_pos(0), LIFT_STAND))

# --- 9. A platform 60 px away in x does not catch him ----------------------
# Without this, a landing test that ignores x passes everything above.
reset(x + 60, yp + 12, DIR_RIGHT, in_air=1, yp0=yp, yp1=LIFT_NONE)
tick(1)
print("falling 60 px to the right: OnLift=%d InAir=%d"
      % (reg("wPlayerOnLift"), reg("wPlayerInAir")))
if reg("wPlayerOnLift"):
    fail("landed on a platform 60 px away in x")

# --- 10. The other axis: at the right x but above the band ----------------
reset(x + 8, yp + 30, DIR_RIGHT, in_air=1, yp0=yp, yp1=LIFT_NONE)
tick(1)
print("falling 18 px above the band: OnLift=%d" % reg("wPlayerOnLift"))
if reg("wPlayerOnLift"):
    fail("landed on a platform from 18 px above it")

# --- 11. Walking off the end starts the step-off window, facing that way ----
for direction, want_dir in ((DIR_RIGHT, 1), (DIR_LEFT, 0xFF)):
    reset(x + 60, yp + LIFT_STAND, direction, on_lift=1, yp0=yp, yp1=LIFT_NONE)
    tick(1)
    print("walked off facing $%02X: InAir=%d InAirCounter=%d JumpDir=$%02X"
          % (direction, reg("wPlayerInAir"), reg("wInAirCounter"),
             reg("wPlayerJumpDirection")))
    if reg("wPlayerInAir") != 1:
        fail("stepping off the end did not start the step-off window")
    if reg("wInAirCounter") != 4:
        fail("stepping off set InAirCounter to %d, expected 4"
             % reg("wInAirCounter"))
    if reg("wPlayerJumpDirection") != want_dir:
        fail("stepping off facing $%02X drifted $%02X, expected $%02X"
             % (direction, reg("wPlayerJumpDirection"), want_dir))

# --- 12. A jump is the way off a platform --------------------------------
reset(x + 8, yp + LIFT_STAND, DIR_RIGHT, on_lift=1, yp0=yp, yp1=LIFT_NONE)
pb.button_press("a")
tick(1)
pb.button_release("a")
print("A while riding: OnLift=%d InAir=%d" % (reg("wPlayerOnLift"),
                                              reg("wPlayerInAir")))
if reg("wPlayerOnLift"):
    fail("PlayerOnLift is still set after a jump")
if reg("wPlayerInAir") != 2:
    fail("PlayerInAir is %d after a jump, expected 2" % reg("wPlayerInAir"))

# --- 13. Riding past LIFT_CEILING kills him --------------------------------
# The Z80's `RET NC` here returns out of MainLoop, and MainLoop was entered by
# JP, so its only return address is the one OnePlayer pushed for `CALL
# PlayLevel`. The code after that call sends a player with eggs left to
# LoseLife: a platform carried off the top of the playfield is a death, not a
# ride that keeps going. It used to keep going here -- PlayerY climbed past the
# ceiling and wrapped to the bottom of the level.
#
# Pad is the second half of the same assertion and not a separate one: leaving
# through the level's door skips the rest of the tick, so the input read after
# it never happens and the sentinel survives.
reset(x + 8, LIFT_CEILING - 1, DIR_RIGHT, on_lift=1, yp0=yp, yp1=LIFT_NONE,
      gate=1)
setreg("wPlayerDead", 0)
setreg("wPad", 0xFF)
tick(1)
print("riding past the top: PlayerY=%d Pad=$%02X Dead=%d"
      % (reg("wPlayerY"), reg("wPad"), reg("wPlayerDead")))
if reg("wPlayerY") != LIFT_CEILING:
    fail("PlayerY is %d past the ceiling, expected %d"
         % (reg("wPlayerY"), LIFT_CEILING))
if not reg("wPlayerDead"):
    fail("riding past the ceiling killed nobody: PlayerY=%d OnLift=%d"
         % (reg("wPlayerY"), reg("wPlayerOnLift")))
if reg("wPad") != 0xFF:
    fail("Pad was refreshed while riding past the top, so the tick did not bail")

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
