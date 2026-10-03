#!/usr/bin/env python3
"""Assert the status band and the level timer (Phase 6a).

Two halves, and they fail for different reasons. The band half checks the
window/STAT raster split: where the status row lands, that the right cells are
in it, and -- the one thing that cannot be read out of WRAM -- that it stays put
while the playfield scrolls under it. The timer half checks the two counters'
start values, cadence, and what happens at corn, at a level's end, and at the
bottom of the clock.

Everything is read back out of the running ROM, and the font is identified by
its own pixels: the ROM's glyphs are matched against the reference charset
re-encoded the same way, so a tile-order or column-offset drift in the layout
fails here rather than looking plausible on screen.

    python3 tools/verify_hud.py build/l1.gb      # bonus starts at 2
    python3 tools/verify_hud.py build/l3.gb      # bonus starts at 4, has lifts
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gbdata  # noqa: E402
import harness  # noqa: E402
import numpy as np  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"
ASM = "reference/paulie/Chuckie.asm"

LEVEL_WIDTH, LEVEL_HEIGHT = 32, 21
HUD_ROWS = 1
SCREEN0, SCREEN1, VRAM = 0x9800, 0x9C00, 0x8000
TILE_BLANK, TILE_EGG, TILE_BIRDSEED = 0, 3, 4
EGGS_PER_LEVEL = 12
HEN_MAX = 5
HEN_NONE = 0xFF

# DrawLevel puts buffer row 0 at map row 21, one lower than the level's own
# height, because the status band takes 8 px off the top of the playfield.
MAP_ROW0 = LEVEL_HEIGHT - 1 + HUD_ROWS

# The status row, exactly as BuildHud lays it out. Twenty columns, full.
HUD_ROW_LEN = 20

# --- the font -----------------------------------------------------------------
# The glyph run gbdata.py emits, in tile order, and the shade it is emitted at.
# Kept here rather than guessed at so a mismatch is a failure and not a puzzle.
HUD_CHARS = "0123456789BESTL"
HUD_SHADE = 3

# --- the timer ----------------------------------------------------------------
BONUS_STEP, TIME_STEP, UNDERFLOW = 50, 10, 0xFF

TIME_FRAMES, TIME_STEPS = 60, 6      # 60 frames at one step per 10 frames
BONUS_FRAMES, BONUS_STEPS = 100, 2   # 100 frames at one step per 50


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wHudRow", "wScore", "wEggsRemaining", "wCurrentLevel", "wLevelDone",
        "wLevelBuffer", "wPlayerX", "wPlayerY", "wPlayerInAir", "wInAirCounter",
        "wHens", "wBonus", "wTime", "wBonusTick", "wTimeTick", "wTimerRunning",
        "wTimeUp", "wPlayerDead", "wDeathTimer"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

failed = []
fail = failed.append

pb = harness.boot(ROM)

wBuffer = sym["wLevelBuffer"]


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def cell(r, c):
    return wBuffer + r * LEVEL_WIDTH + c


def map_addr(r, c):
    return SCREEN0 + (MAP_ROW0 - r) * LEVEL_WIDTH + c


def digits(name, n):
    return list(pb.memory[sym[name]:sym[name] + n])


def value3(name):
    d = digits(name, 3)
    return d[0] * 100 + d[1] * 10 + d[2]


def score():
    d = pb.memory[sym["wScore"]:sym["wScore"] + 6]
    return sum(d[i] * 10 ** (4 - i) for i in range(5))


def stand_on(r, c):
    """Put Harry where PlayerPickUp samples cell (r, c) -- ((y-8)/8, (x+8)/8)."""
    setreg("wPlayerX", c * 8 - 8)
    setreg("wPlayerY", r * 8 + 8)
    setreg("wPlayerInAir", 0)
    setreg("wInAirCounter", 4)


def pin(y):
    """Hold Harry at (24, y) for one frame's camera update.

    x is a multiple of 8 so CheckForFalling does not start a ledge countdown --
    which is also why wInAirCounter is pinned: on any y the level has no floor
    under, Harry would otherwise fall out from under the case.
    """
    setreg("wPlayerX", 24)
    setreg("wPlayerY", y)
    setreg("wPlayerInAir", 0)
    setreg("wInAirCounter", 4)


# The hens run on the same clock as the timer and would kill Harry mid-window,
# and one of them wandering into the top of the view is drawn over the band.
for s in range(HEN_MAX):
    pb.memory[sym["wHens"] + s * 4] = HEN_NONE

level = reg("wCurrentLevel")
bonus0 = min(level + 1, 9)                   # min(CurrentLevel + 1, 9)
time0 = 9 - min(level >> 4, 5)               # 9 - min(CurrentLevel >> 4, 5)
print("level index %d: bonus opens at %d, time at %d" % (level, bonus0, time0))

# --- 1. Band geometry ------------------------------------------------------
# rLYC is the line the STAT interrupt fires on, so it is also the height of the
# band; rWX=7 pins the window's left edge to screen x=0.
geo = [("rWY", pb.memory[0xFF4A], 0), ("rWX", pb.memory[0xFF4B], 7),
       ("rLYC", pb.memory[0xFF45], HUD_ROWS * 8)]
print("band geometry: WY=%d WX=%d LYC=%d STAT=$%02X"
      % (pb.memory[0xFF4A], pb.memory[0xFF4B], pb.memory[0xFF45], pb.memory[0xFF41]))
for name, got, want in geo:
    if got != want:
        fail("%s is %d, expected %d" % (name, got, want))
if not pb.memory[0xFF41] & 0x40:
    fail("rSTAT has the LYC source off, so nothing ever ends the band")

# --- 2. Map layout ---------------------------------------------------------
# The level's own rows live at map rows 21 down to 1, and the map mirrors the
# buffer cell for cell -- the pickup blanks both.
bad = []
for r in range(LEVEL_HEIGHT):
    for c in range(LEVEL_WIDTH):
        if pb.memory[map_addr(r, c)] != pb.memory[cell(r, c)]:
            bad.append((r, c))
print("level buffer at map rows %d..%d: %s"
      % (MAP_ROW0, MAP_ROW0 - LEVEL_HEIGHT + 1,
         "PASS" if not bad else "FAIL (%d cells differ)" % len(bad)))
if bad:
    r, c = bad[0]
    fail("map row %d col %d is $%02X, buffer row %d col %d is $%02X"
         % (MAP_ROW0 - r, c, pb.memory[map_addr(r, c)], r, c, pb.memory[cell(r, c)]))

# --- 3. HUD content --------------------------------------------------------
# Find the glyph run in VRAM by its pixels: the tiles matching the reference
# charset's 0-9 B E S T, re-encoded at the HUD's shade. Locating it this way
# checks the tile order and the shade as well as the base address.
gfx, _, _, _, _, _ = gbdata.build(ASM)
want_tiles = [bytes(gbdata.to_gb_tile(gfx[ord(ch) * 8:ord(ch) * 8 + 8], HUD_SHADE))
              for ch in HUD_CHARS]
vram = bytes(pb.memory[VRAM:VRAM + 256 * 16])
bases = [t for t in range(257 - len(HUD_CHARS))
         if all(vram[(t + i) * 16:(t + i + 1) * 16] == want_tiles[i]
                for i in range(len(HUD_CHARS)))]
if len(bases) != 1:
    raise SystemExit("FAIL: found %d runs of the status glyphs in VRAM (%s), "
                     "expected exactly one" % (len(bases), bases))
base = bases[0]
print("status glyphs: %d tiles at $%02X (%d of 256)" % (len(HUD_CHARS), base, base))


def hud_tile(ch):
    return 0 if ch == " " else base + HUD_CHARS.index(ch)


def hud_char(t):
    if t == 0:
        return " "
    i = t - base
    return HUD_CHARS[i] if 0 <= i < len(HUD_CHARS) else "?"


# Both halves below are read in a quiet frame. The tick runs in the visible part
# of a frame, after the VBlank that built the row from the counters, so a tick
# that steps a counter leaves WRAM a step ahead of both wHudRow and the map --
# a one-frame display lag, not a wrong row. Freezing the dividers stops anything
# stepping at all, and they are put back on the phase a fresh level starts on
# just below, so the cadence check still measures from where the level does.
setreg("wBonusTick", UNDERFLOW)
setreg("wTimeTick", UNDERFLOW)
tick(2)

tens, units = divmod(reg("wEggsRemaining"), 10)
want = ("S" + "".join("%d" % d for d in digits("wScore", 5))
        + " E%d%d" % (tens, units)
        + " T%s" % "".join("%d" % d for d in digits("wTime", 3))
        # Lives, not BONUS: the field BONUS held. The count is read from WRAM,
        # so a HUD that showed a stale or wrong life count fails here.
        + " L%02d " % reg("wLives"))
got = list(pb.memory[sym["wHudRow"]:sym["wHudRow"] + HUD_ROW_LEN])
print("status row: %r" % "".join(hud_char(t) for t in got))
if len(want) != HUD_ROW_LEN:
    fail("the expected row is %d columns, not %d" % (len(want), HUD_ROW_LEN))
elif got != [hud_tile(c) for c in want]:
    fail("the status row is %r, expected %r" % ("".join(hud_char(t) for t in got), want))

if list(pb.memory[SCREEN1:SCREEN1 + HUD_ROW_LEN]) != got:
    fail("the window's map row 0 is %s, not the buffer the ROM built"
         % list(pb.memory[SCREEN1:SCREEN1 + HUD_ROW_LEN]))

setreg("wBonusTick", 1)
setreg("wTimeTick", 1)

# --- 4. Cadence, counted over a window -------------------------------------
# Both dividers reset to 1, not to their reload value, so the first step of each
# lands on the first tick -- which is why the count over a whole number of
# periods is exact however the window falls on the phase.
#
# Harry is held still for the whole window, on a cell the level buffer says is
# empty. Left to himself he falls until something stops him, and on level 3 what
# stops him is a corn tile -- which pokes both dividers to $FF and puts the
# count out by a whole step. The cell is read out of the buffer rather than
# guessed at, so it is empty on any level, and x stays a multiple of 8 so
# CheckForFalling does not start a ledge countdown out from under the pin.
PARK_R, PARK_C = next((r, c) for r in range(LEVEL_HEIGHT)
                      for c in range(1, LEVEL_WIDTH - 2)
                      if pb.memory[cell(r, c)] == TILE_BLANK)


def step_frames(name, frames):
    prev = value3(name)
    out = []
    for f in range(frames):
        stand_on(PARK_R, PARK_C)
        tick(1)
        cur = value3(name)
        if cur != prev:
            out.append(f + 1)
            prev = cur
    return out


for name, frames, count, period in (("wTime", TIME_FRAMES, TIME_STEPS, TIME_STEP),
                                    ("wBonus", BONUS_FRAMES, BONUS_STEPS, BONUS_STEP)):
    at = step_frames(name, frames)
    gaps = [b - a for a, b in zip(at, at[1:])]
    print("%s over %d frames: %d steps at %s" % (name, frames, len(at), at))
    if len(at) != count:
        fail("%s stepped %d times in %d frames, expected %d"
             % (name, len(at), frames, count))
    if gaps and set(gaps) != {period}:
        fail("%s stepped every %s frames, expected every %d" % (name, gaps, period))
    if at and at[0] > period:
        fail("%s did not step until frame %d, so the first step of the level was "
             "not on its first tick" % (name, at[0]))

# --- 5. The band holds still while the playfield scrolls -------------------
# The assertion that proves the raster split, and the only one that is not read
# out of WRAM. The counters are frozen so the band's own text cannot change
# under the comparison, and the camera is pinned from outside: Harry has no
# floor at these heights, so he would otherwise fall out from under the case.
def frozen_frames_at(y, n=4):
    for _ in range(n):
        setreg("wBonusTick", UNDERFLOW)
        setreg("wTimeTick", UNDERFLOW)
        pin(y)
        tick(1)
    return np.array(pb.screen.ndarray)[:, :, 0], pb.memory[0xFF42]


band_a, scy_a = frozen_frames_at(120)        # past the bottom clamp
band_b, scy_b = frozen_frames_at(64)         # the first y pinned to the top
print("camera: SCY %d at y=120, %d at y=64" % (scy_a, scy_b))
if (scy_a, scy_b) != (0, 32):
    fail("the camera read SCY %d/%d for y=120/64, expected 0/32" % (scy_a, scy_b))
moved = [r for r in range(8, 144) if (band_a[r] != band_b[r]).any()]
if not moved:
    fail("nothing below the band changed when the camera moved 32 px, so this "
         "check is not measuring the playfield")
stuck = [r for r in range(8) if (band_a[r] != band_b[r]).any()]
print("band rows 0-7 %s, playfield rows 8-143: %d rows changed"
      % ("identical" if not stuck else "CHANGED at rows %s" % stuck, len(moved)))
if stuck:
    fail("the status band moved with the camera: rows %s differ" % stuck)

# --- 6. Start values, and the dividers' reset ------------------------------
# Read at the only moment they can be read: the reload happens in one frame and
# the tick does not run in that frame, so the frame the death path returns on
# shows the counters as ResetTimer left them.
setreg("wPlayerDead", 1)
setreg("wDeathTimer", 2)
for _ in range(20):
    tick(1)
    if not reg("wPlayerDead"):
        break
else:
    fail("the level never reloaded after a death")
fresh_bonus, fresh_time = digits("wBonus", 3), digits("wTime", 3)
print("after the reload: bonus %s time %s dividers %d/%d running %d"
      % (fresh_bonus, fresh_time, reg("wBonusTick"), reg("wTimeTick"),
         reg("wTimerRunning")))
if fresh_bonus != [bonus0, 0, 0]:
    fail("a fresh level starts with bonus %s, expected [%d, 0, 0]"
         % (fresh_bonus, bonus0))
if fresh_time != [time0, 0, 0]:
    fail("a fresh level starts with time %s, expected [%d, 0, 0]"
         % (fresh_time, time0))
if reg("wBonusTick") != 1 or reg("wTimeTick") != 1:
    fail("the dividers reset to %d/%d, expected 1/1 -- a divider loaded at its "
         "reload value would not step on the level's first tick"
         % (reg("wBonusTick"), reg("wTimeTick")))
if not reg("wTimerRunning") or reg("wTimeUp"):
    fail("a fresh level is running=%d timeUp=%d, expected 1/0"
         % (reg("wTimerRunning"), reg("wTimeUp")))

# --- 7. Corn pokes both dividers -------------------------------------------
# The reload leaves MainLoop parked: it resumes through halt at the next VBlank
# and then waits out the rest of that frame, so the tick does not run again
# until the frame after the one the reload returned on. Spend it here, or the
# poke below lands in a frame where nothing runs and the dividers do not move.
tick(1)
before = score()
pb.memory[cell(13, 9)] = TILE_BIRDSEED
stand_on(13, 9)
tick(1)
# $FFFF lands over the two adjacent divider bytes, and the same tick's UpdateTimer
# decrements each once on the way out.
print("corn: dividers %d/%d score %d" % (reg("wBonusTick"), reg("wTimeTick"), score()))
if reg("wBonusTick") != UNDERFLOW - 1 or reg("wTimeTick") != UNDERFLOW - 1:
    fail("corn left the dividers at %d/%d, expected %d -- it should be the $FFFF "
         "poke, not the ordinary reload"
         % (reg("wBonusTick"), reg("wTimeTick"), UNDERFLOW - 1))
if score() != before + 5:
    fail("corn scored %d, expected 5" % (score() - before))

# --- 8. The bonus drains into the score at the end of a level -------------
R, C = 12, 6
score_before = score()
setreg("wBonusTick", UNDERFLOW)
setreg("wTimeTick", UNDERFLOW)
pb.memory[sym["wBonus"]] = 0
pb.memory[sym["wBonus"] + 1] = 0
pb.memory[sym["wBonus"] + 2] = 7
pb.memory[cell(R, C)] = TILE_EGG
setreg("wEggsRemaining", 1)
stand_on(R, C)
tick(1)
if not reg("wLevelDone"):
    fail("the last egg did not end the level")
per_egg = 10 * (min(level >> 2, 9) + 1)
# A bonus of N scores N + 1: the step that borrows out scores too.
drained = 7 + 1
for _ in range(60):
    tick(1)
    if not reg("wLevelDone"):
        break
else:
    fail("the level never reloaded after the last egg")
print("bonus 7 drained: score %d, expected %d" % (score(), score_before + per_egg + drained))
if reg("wCurrentLevel") != level + 1:
    fail("wCurrentLevel is %d after the level ended, expected %d"
         % (reg("wCurrentLevel"), level + 1))
if score() != score_before + per_egg + drained:
    fail("the score did not carry across the level change: %d, expected %d "
         "(before + egg + drained bonus)" % (score(), score_before + per_egg + drained))

# --- 9. The clock running out ----------------------------------------------
# Borrowing out of the top digit writes the $FF,$09,$09 sentinel -- the residue
# of each digit borrowing once -- and sets wTimeUp, which is what 6c will read.
pb.memory[sym["wTime"]] = 0
pb.memory[sym["wTime"] + 1] = 0
pb.memory[sym["wTime"] + 2] = 1
setreg("wTimeTick", 1)
for f in range(2 * TIME_STEP + 2):
    tick(1)
    if reg("wTimeUp"):
        break
else:
    fail("the clock never ran out")
print("time up after %d frames: time %s timeUp %d"
      % (f + 1, digits("wTime", 3), reg("wTimeUp")))
if digits("wTime", 3) != [UNDERFLOW, 9, 9]:
    fail("the clock ran out to %s, expected [255, 9, 9]" % digits("wTime", 3))
if not reg("wTimeUp"):
    fail("wTimeUp is not set after the clock ran out")

# ...and running out is ALL that happens. The Z80 keeps Harry alive (its
# DecreaseTimerOrBonus sets no death flag for either array), so the only
# consequence of the clock stopping is the label on the death he later suffers
# -- LoseLife is the sentinel's only reader. 6a killed him here because a
# stopped clock had no other way to show itself.
if reg("wPlayerDead"):
    fail("the clock running out killed Harry: the Z80 stops the clock and "
         "nothing else, and the death that follows is what says OUT OF TIME !")
# The bonus is NOT forfeit either: the level-end drain is gated on TimerRunning,
# which only the BONUS array's own borrow-out clears.
if not reg("wTimerRunning"):
    fail("the clock running out stopped the bonus countdown, which the Z80's "
         "does not do")
# Stopped means stopped: the digits hold the sentinel rather than stepping on
# into nonsense the way the Z80's do (nothing there tests them but LoseLife, so
# its exact-match only lands in the nine ticks after the borrow).
frozen = digits("wTime", 3)
for f in range(2 * TIME_STEP + 2):
    tick(1)
print("%d frames with the clock out: time %s timeUp %d dead %d"
      % (2 * TIME_STEP + 2, digits("wTime", 3), reg("wTimeUp"), reg("wPlayerDead")))
if digits("wTime", 3) != frozen:
    fail("the clock kept stepping after it ran out: %s -> %s"
         % (frozen, digits("wTime", 3)))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
