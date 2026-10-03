#!/usr/bin/env python3
"""Assert eggs are collected, score, and the level advances when they run out.

Phase 5 check. Everything is read back out of the running ROM: the level buffer
in WRAM, the BG map in VRAM, and the score digits. The cells are written into
the buffer by the test rather than hunted for in the level data, so the rule
being checked is the sampling rule and not "wherever an egg happens to be".

    python3 tools/verify_eggs.py build/l1.gb      # score 10 an egg
    python3 tools/verify_eggs.py build/l5.gb      # score 20
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"

LEVEL_WIDTH, LEVEL_HEIGHT = 32, 21
LEVEL_SIZE = LEVEL_WIDTH * LEVEL_HEIGHT
TILE_BLANK, TILE_EGG, TILE_BIRDSEED = 0, 3, 4
EGGS_PER_LEVEL = 12
HEN_MAX = 5
HEN_NONE = 0xFF
HUD_ROWS = 1
SCREEN0 = 0x9800
# DrawLevel puts buffer row 0 at map row 21 -- one lower than the level's own
# height, because the status band takes 8 px off the top of the playfield (see
# PLAN.md Phase 6a) -- so the map address of a buffer cell is
# 672 - 32*row + column from the start of the map.
MAP_LAST_ROW = (LEVEL_HEIGHT - 1 + HUD_ROWS) * LEVEL_WIDTH


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wEggsRemaining", "wScore", "wCurrentLevel", "wLevelDone", "wLevelBuffer",
        "wPlayerX", "wPlayerY", "wPlayerInAir", "wHens", "Level1", "Level2"]
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
    return SCREEN0 + MAP_LAST_ROW - r * LEVEL_WIDTH + c


def score():
    """The six digits are decimal, one per byte, units at wScore+4."""
    d = pb.memory[sym["wScore"]:sym["wScore"] + 6]
    return sum(d[i] * 10 ** (4 - i) for i in range(5))


def put_hen(slot, x):
    pb.memory[sym["wHens"] + slot * 4] = x


for s in range(HEN_MAX):
    put_hen(s, HEN_NONE)              # no hens: this is about eggs

level = reg("wCurrentLevel")
per_egg = 10 * (min(level >> 2, 9) + 1)
print("level index %d: an egg is worth %d" % (level, per_egg))

# --- 1. Fresh state --------------------------------------------------------
eggs0, score0 = reg("wEggsRemaining"), score()
print("start: EggsRemaining=%d score=%d LevelDone=%d"
      % (eggs0, score0, reg("wLevelDone")))
if eggs0 != EGGS_PER_LEVEL:
    fail("EggsRemaining starts at %d, expected %d" % (eggs0, EGGS_PER_LEVEL))
if score0 != 0:
    fail("score starts at %d, expected 0" % score0)
if reg("wLevelDone"):
    fail("LevelDone is set at the start of a level")


def stand_on(r, c):
    """Put Harry where PlayerPickUp samples cell (r, c).

    The Z80 reads HL,(PlayerX) -- little-endian over the adjacent PlayerX and
    PlayerY -- then takes 8 off y and adds 8 to x, so the cell sampled is
    ((y-8)/8, (x+8)/8). Solving that for the cell we want, and leaving x a
    multiple of 8 so CheckForFalling does not start a ledge countdown, Harry
    stays exactly where he is put.
    """
    setreg("wPlayerX", c * 8 - 8)
    setreg("wPlayerY", r * 8 + 8)
    setreg("wPlayerInAir", 0)


# --- 2. The egg he is standing on is collected -----------------------------
R, C = 12, 6
pb.memory[cell(R, C)] = TILE_EGG
stand_on(R, C)
x, y = reg("wPlayerX"), reg("wPlayerY")
tick(1)
print("egg at (row %d, col %d), Harry at (%d,%d): cell=%d Eggs=%d score=%d"
      % (R, C, x, y, pb.memory[cell(R, C)], reg("wEggsRemaining"), score()))
if pb.memory[cell(R, C)] != TILE_BLANK:
    fail("the egg at (row %d, col %d) is still %d in the level buffer"
         % (R, C, pb.memory[cell(R, C)]))
if pb.memory[map_addr(R, C)] != TILE_BLANK:
    fail("the egg at (row %d, col %d) is still %d in the BG map -- eaten but "
         "still on screen" % (R, C, pb.memory[map_addr(R, C)]))
if reg("wEggsRemaining") != eggs0 - 1:
    fail("EggsRemaining is %d after one egg, expected %d"
         % (reg("wEggsRemaining"), eggs0 - 1))
if score() != score0 + per_egg:
    fail("score is %d after one egg at level index %d, expected %d"
         % (score(), level, score0 + per_egg))

if reg("wPlayerX") != x or reg("wPlayerY") != y:
    fail("Harry moved to (%d,%d) while standing still, so the cell sampled was "
         "not the one set up" % (reg("wPlayerX"), reg("wPlayerY")))

# --- 3. An egg one column over is not --------------------------------------
# Without this, a pickup that ignores the cell it sampled passes everything.
R2, C2 = 15, 20
pb.memory[cell(R2, C2)] = TILE_EGG
stand_on(R2, C2 + 1)
tick(1)
print("egg at (row %d, col %d), Harry sampling (row %d, col %d): cell=%d"
      % (R2, C2, R2, C2 + 1, pb.memory[cell(R2, C2)]))
if pb.memory[cell(R2, C2)] != TILE_EGG:
    fail("collected an egg one column away from the cell sampled")
if reg("wEggsRemaining") != eggs0 - 1:
    fail("EggsRemaining moved for an egg he was not standing on")

# --- 4. Corn is 5, and is blanked in the map as well -----------------------
before = score()
pb.memory[cell(R2, C2)] = TILE_BIRDSEED
stand_on(R2, C2)
tick(1)
print("corn at (row %d, col %d): cell=%d map=%d score=%d"
      % (R2, C2, pb.memory[cell(R2, C2)], pb.memory[map_addr(R2, C2)], score()))
if pb.memory[cell(R2, C2)] != TILE_BLANK:
    fail("corn at (row %d, col %d) was not eaten" % (R2, C2))
if pb.memory[map_addr(R2, C2)] != TILE_BLANK:
    fail("corn is still %d in the BG map" % pb.memory[map_addr(R2, C2)])
if score() != before + 5:
    fail("corn scored %d, expected 5" % (score() - before))
if reg("wEggsRemaining") != eggs0 - 1:
    fail("corn changed EggsRemaining")

# --- 5. The last egg ends the level, and the next one loads -----------------
# The score survives a level change; the eggs and the eaten cells do not.
#
# Since 6a the level-completion score is not just the eggs: NextLevel drains
# wBonus into it a point a step (the Z80's LevelCompleted loop) before the
# reload. Freeze both dividers first so the bonus cannot step between reading
# it and the last egg landing, then expect the drain to be value + 1 -- the
# step that borrows out scores too, which is the original's own arithmetic.
score_before = score()
setreg("wBonusTick", 0xFF)
setreg("wTimeTick", 0xFF)
bonus = pb.memory[sym["wBonus"]:sym["wBonus"] + 3]
bonus_value = sum(bonus[i] * 10 ** (2 - i) for i in range(3))
drained = bonus_value + 1 if reg("wTimerRunning") else 0
print("bonus at the last egg: %s (%d) -> %d points" % (bonus, bonus_value, drained))
pb.memory[cell(R, C)] = TILE_EGG
setreg("wEggsRemaining", 1)
stand_on(R, C)
tick(1)
print("last egg: Eggs=%d LevelDone=%d" % (reg("wEggsRemaining"), reg("wLevelDone")))
if reg("wEggsRemaining") != 0:
    fail("EggsRemaining is %d after the last egg" % reg("wEggsRemaining"))
if not reg("wLevelDone"):
    fail("the last egg did not end the level")

# The reload blanks the screen and writes the whole level, so it takes a few
# frames; wLevelDone clears with it, which is the completion signal. The
# announcement the level change puts up first ("LEVEL n", NOTICE_HOLD frames)
# is most of the wait, hence the window rather than a handful of frames.
for _ in range(60):
    tick(1)
    if not reg("wLevelDone"):
        break
else:
    fail("the level never reloaded after the last egg")

with open(ROM, "rb") as f:
    rom = f.read()
# The counter steps without a bound, but the map it points at is masked -- the
# Z80's AND $07, the only wrap left in the port.
next_index = level + 1
next_map = next_index & 7
level2 = rom[sym["Level%d" % (next_map + 1)]:][:LEVEL_SIZE]
print("after the reload: LevelIndex=%d Eggs=%d score=%d buffer-is-level-%d=%s"
      % (reg("wCurrentLevel"), reg("wEggsRemaining"), score(), next_map + 1,
         pb.memory[wBuffer:wBuffer + LEVEL_SIZE] == list(level2)))
if reg("wCurrentLevel") != next_index:
    fail("wCurrentLevel is %d after the level ended, expected %d"
         % (reg("wCurrentLevel"), next_index))
if reg("wEggsRemaining") != EGGS_PER_LEVEL:
    fail("eggs are %d after a reload, expected %d"
         % (reg("wEggsRemaining"), EGGS_PER_LEVEL))
if score() != score_before + per_egg + drained:
    fail("the score did not carry across the level change: %d, expected %d "
         "(before + egg + drained bonus)"
         % (score(), score_before + per_egg + drained))
if pb.memory[wBuffer:wBuffer + LEVEL_SIZE] != list(level2):
    bad = [i for i in range(LEVEL_SIZE)
           if pb.memory[wBuffer + i] != level2[i]]
    fail("the reloaded level differs from Level%d in %d cells, first at %s"
         % (next_map + 1, len(bad), bad[:4]))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
