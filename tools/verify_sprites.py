#!/usr/bin/env python3
"""Assert the 10-sprites-a-scanline limit never costs the player or a hen.

The DMG shows only the first ten OAM entries on a line, in OAM order -- PyBoy
enforces it at pyboy/core/lcd.py:621 (`if sprite_count == 10: break`), walking
OAM from $FE00 and never looking at x. A 16x16 sprite needs TWO entries a line
whichever OBJ mode is in use: in 8x8 mode the left and right halves of one row
band, so LCDC's 8x16 bit halves the TOTAL entry count (40, of which 32 are
used) and not the per-line one. There is therefore no layout that avoids the
limit. The only thing that can be chosen is who is dropped when it bites, and
that choice is OAM order:

    Harry 0-3, the hens 4-23, the lifts 24-27, the duck 28-31   (src/main.asm)

This check pins that order as load-bearing instead of leaving it a comment.
Reorder the draws -- put a hen's block after the lifts, say -- and the player
starts flickering in a crowd while the caged duck stays solid; this fails, and
names the hen.

Measured before it was written: idle, scripted and 6000-frame randomised runs of
all eight levels peak at 8 of the 10, because a level spawns at most four hens and
four is exactly the fit. **Level 25 is where that stops being true**: from there
the hen table's own five records all run (`CP $18` is a size -- `$14` = 20 bytes =
every slot; see PLAN.md's five laps), so a line can want 12 with no duck in sight
and the drop reaches the birds. What goes is the last live hen, never Harry and
never one ahead of it -- and that is checked by the column the bird is drawn at,
not by its slot number, because a reshuffled draw order moves which hen owns a
slot without moving any slot's number.

    python3 tools/verify_sprites.py build/l5.gb      # four hens, exactly the fit
    python3 tools/verify_sprites.py build/l8.gb      # the lethal duck, no lifts
    python3 tools/verify_sprites.py build/l25.gb     # five hens, the ceiling reached
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"

OAM = 0xFE00
ENTRIES = 40
LIMIT = 10                  # what the PPU draws on a line
LINES = 144                 # the visible ones

# The slot chain, from src/main.asm. These are `DEF`s, so they are not in the
# .sym file -- the same four numbers verify_duck.py carries.
HEN_MAX = 5
HARRY_OAM = 4               # Harry's first slot; the hens start where he ends
HEN_OAM = HARRY_OAM
LIFT_OAM = HARRY_OAM + HEN_MAX * 4
DUCK_OAM = LIFT_OAM + 4
HEN_NONE = 0xFF

# Harry is parked where the GAME parks him -- NewGame's own spawn, read back out
# of the ROM -- and the hens are spread along his row but out of his overlap
# window, which is hen_x-8 < player_x <= hen_x+5. Without that spread the
# collision kills him and the level reloads mid-scene, which wipes every poke.
# The spawn is not a convenience: the fixed corner this used to park at (x=72) is
# inside a hen's own spawn once a level runs all five records, so on level 25 he
# died on the way in and the whole scene was built on a level that had already
# reloaded. One x per hen slot HEN_MAX allows -- every live hen is slid onto the
# line, whatever the level spawns, so a level that spawns a fifth is caught here
# rather than capped away.
HEN_XS = [8, 24, 40, 56, 88]
SPAWN_X = SPAWN_Y = 0                    # read back after the boot below

# Held high so nothing walks out of the scene between the write and the draw.
QUIET_TICK = 0xFF

# A deterministic wander: along the floor, a few jumps, back the other way. The
# point is not to play well -- it is to walk Harry and the hens past each other,
# which is when two 16x16 boxes share a line.
SCRIPT = [("right", 150), ("a", 6), ("left", 90), ("a", 6),
          ("right", 120), ("a", 6), ("left", 150), ("a", 6), (None, 60)]


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wHens", "wDuckX", "wDuckY", "wDuckTick", "wHenTick", "wCurrentLevel",
        "wPlayerX", "wPlayerY", "wPlayerInAir", "wPlayerDead"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

wHens = sym["wHens"]
failed = []
fail = failed.append


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def oam_slot(n):
    return tuple(pb.memory[OAM + n * 4:OAM + n * 4 + 4])


def read_oam():
    return list(pb.memory[OAM:OAM + ENTRIES * 4])


def line_slots(oam):
    """Every OAM slot whose 8-row box covers each visible line, in OAM order.

    The hardware rule rather than a model of it: an entry covers eight lines
    from its y (minus 16, as OAM states it), and a 16x16 sprite is two such
    entries a band -- so it takes two slots a line, which is why OBJ 8x16 mode
    cannot help.
    """
    return [[n for n in range(ENTRIES)
             if oam[n * 4] - 16 <= ly < oam[n * 4] - 8]
            for ly in range(LINES)]


def kind(slot):
    if slot < HARRY_OAM:
        return "Harry"
    if slot < LIFT_OAM:
        return "a hen"
    if slot < DUCK_OAM:
        return "a lift"
    return "the duck"


def check_drop(where, slots, oam):
    """Nothing is dropped ahead of the last thing the level draws.

    The PPU keeps the first ten entries in OAM order, so the casualty is always
    the tail of that order: the last live hen when a level runs five of them
    (from level 25 -- `CP $18` is a size, so the table's own five records all
    run), otherwise the lifts, otherwise the duck. Harry and every hen but the
    last must survive, and when a hen does go it has to be the LAST one.
    """
    dropped = slots[LIMIT:]
    last = len(hens) - 1
    block = HEN_OAM + 4 * last
    early = [s for s in dropped if s < block]
    if early:
        fail("%s: the PPU drops %s, ahead of the last hen drawn -- the OAM order "
             "in src/main.asm is what keeps the player and the hens first"
             % (where, ["%s(slot %d)" % (kind(s), s) for s in early]))
    # Which hen's entries went, if any. The last one may and only the last one:
    # three or four hens never reach the limit, so a hen among the dropped on
    # those levels is a draw order that put a bird behind the decoration. (An
    # earlier bird moved to the end fails this check sooner than this, in the
    # scene build above, which watches each hen's own slot.)
    gone = [s for s in dropped if s < LIFT_OAM]
    want_gone = [block, block + 1] if len(hens) > 4 else []
    if gone != want_gone:
        fail("%s: the PPU drops %s; expected %s -- the OAM order in src/main.asm "
             "is what keeps the player first and the hens in record order after "
             "him, so the last bird drawn is the first to go"
             % (where, ["%s(slot %d) drawn at column %d" % (kind(s), s, oam[s * 4 + 1])
                        for s in gone] or "no hen",
                ["%s(slot %d) drawn at column %d" % (kind(s), s, oam[s * 4 + 1])
                 for s in want_gone] or "no hen"))


def live_hens():
    return [h for h in range(HEN_MAX) if pb.memory[wHens + h * 4] != HEN_NONE]


def park():
    pb.memory[sym["wPlayerInAir"]] = 0
    pb.memory[sym["wPlayerX"]] = SPAWN_X
    pb.memory[sym["wPlayerY"]] = SPAWN_Y


pb = harness.boot(ROM)
level = reg("wCurrentLevel") + 1
print("level %d: %d live hens" % (level, len(live_hens())))

# --- 1. A wandering game never drops the player or a hen ---------------------
# Checked on every frame rather than at the end, because the moment that
# matters is the crowded one and it is not a frame any script can aim at. The
# worst line is reported so a change that eats into the margin is visible even
# while it still passes.
worst, worst_at, drops = 0, None, []
for button, n in SCRIPT:
    if button:
        pb.button_press(button)
    for _ in range(n):
        pb.tick(1, True)
        for ly, slots in enumerate(line_slots(read_oam())):
            if len(slots) > worst:
                worst, worst_at = len(slots), ly
            for slot in slots[LIMIT:]:
                k = kind(slot)
                if k != "the duck" and k != "a lift":
                    drops.append((ly, slot, k))
    if button:
        pb.button_release(button)
print("%d frames of play: worst line %d entries%s"
      % (sum(n for _, n in SCRIPT), worst,
         " at line %d" % worst_at if worst_at is not None else ""))
if drops:
    ly, slot, k = drops[0]
    fail("%d sprite entries of the player or a hen were dropped, first %s "
         "(slot %d) on line %d -- the OAM order in src/main.asm is what keeps "
         "them first" % (len(drops), k, slot, ly))

# --- 2. Forced: the boundary, then one over it -------------------------------
# Ten entries is exactly Harry (2) and four hens (2 each) -- the fit -- and then
# one more sprite goes on the line and something must give. What gives has to be
# the last thing the level draws, and which sprite that is depends on the level:
# four hens plus the duck is 12, so the duck goes; five hens with no duck is
# already 12, so the fifth hen goes. Both are forced here.
#
# Everything is moved by reading its drawn row back and applying the
# difference, not by recomputing OAM_ROW_BASE - y - SCY here: a check that
# recomputes the transform agrees with the transform whatever it says, so it
# cannot see the anchor move.
#
# A fresh boot rather than the game above: the wander can end mid-death, and a
# reload landing inside this scene would reset the very records it pokes.
pb.stop(save=False)
pb = harness.boot(ROM)

setreg("wHenTick", QUIET_TICK)
setreg("wDuckTick", QUIET_TICK)
SPAWN_X, SPAWN_Y = reg("wPlayerX"), reg("wPlayerY")
park()
tick(4)
row = oam_slot(0)[0]
line = row - 16
print("Harry parked at the game's spawn (%d,%d), drawn at OAM row %d (line %d)"
      % (SPAWN_X, SPAWN_Y, row, line))
if not row:
    raise SystemExit("FAIL: Harry is not on the line at (%d,%d) -- the scene "
                     "cannot be built" % (SPAWN_X, SPAWN_Y))

# The column transform's offset, learned rather than recomputed: Harry's record
# x and his drawn column are two numbers read off the same frame, and the hens
# share the offset (main.asm draws both as `column = x - SCX`, plus 8). A check
# that recomputes `x - SCX + 8` agrees with the transform whatever it does -- the
# lesson verify_player.py's section 9 pays for -- so this way it cannot.
COL_OFFSET = oam_slot(0)[1] - SPAWN_X


def hen_col(i):
    """Hen i's drawn OAM column, with its record x of HEN_XS[i]."""
    return (HEN_XS[i] + COL_OFFSET) & 0xFF

hens = live_hens()
if len(hens) > len(HEN_XS):
    raise SystemExit("FAIL: %d live hens but only %d spread x's -- HEN_MAX "
                     "grew past this check" % (len(hens), len(HEN_XS)))


def slide(slot, get_y, set_y, want, tries=4):
    """Move a sprite's state y until its drawn OAM row is `want`."""
    for _ in range(tries):
        got = oam_slot(slot)[0]
        if got == want:
            return True
        if not got:
            return False
        park()
        set_y((get_y() - (want - got)) & 0xFF)
        pb.tick(1, True)
    return oam_slot(slot)[0] == want


def settle():
    """Two ticks, then the OAM is the frame's.

    The draw pass runs inside the VBlank handler and spills past the frame
    boundary the emulator steps on, so a single tick can land between two OAM
    entries and read the last one stale -- which looks exactly like a draw that
    only wrote half a sprite. verify_lifts.py carries the same note.
    """
    park()
    tick(2)


for i, h in enumerate(hens):
    pb.memory[wHens + h * 4] = HEN_XS[i]           # out of Harry's overlap window
    ok = slide(HEN_OAM + h * 4,
               lambda h=h: pb.memory[wHens + h * 4 + 1],
               lambda v, h=h: pb.memory.__setitem__(wHens + h * 4 + 1, v),
               row)
    if not ok:
        fail("could not put hen %d on Harry's row (%d): it is drawn at %s"
             % (h, row, oam_slot(HEN_OAM + h * 4)))

settle()
oam = read_oam()
slots = line_slots(oam)[line]
print("level %d: %d entries want Harry's line -- %s"
      % (level, len(slots), ", ".join("%s(slot %d)" % (kind(s), s) for s in slots)))
if len(slots) != 2 + 2 * len(hens):
    fail("the forced line holds %d entries, expected %d (Harry 2 + %d hens)"
         % (len(slots), 2 + 2 * len(hens), len(hens)))
# Ten entries is the fit, so four hens drop nothing and a fifth is the level-25
# case where the drop reaches the birds.
check_drop("with %d hens on the line" % len(hens), slots, oam)

# Now the caged duck, on the same line. It is drawn last on every level and it
# is the same four slots there, so this is the arrangement that does happen --
# and the one whose casualties have to be the decoration.
setreg("wDuckTick", QUIET_TICK)
ok = slide(DUCK_OAM, lambda: reg("wDuckY"),
           lambda v: setreg("wDuckY", v), row)
if not ok:
    fail("could not put the duck on Harry's row (%d): it is drawn at %s"
         % (row, oam_slot(DUCK_OAM)))

settle()
oam = read_oam()
slots = line_slots(oam)[line]
dropped = slots[LIMIT:]
print("with the duck: %d entries want the line, the PPU draws %d and drops %s"
      % (len(slots), min(len(slots), LIMIT),
         ["%s(slot %d)" % (kind(s), s) for s in dropped] or "nothing"))
if len(slots) != 2 + 2 * len(hens) + 2:
    fail("Harry + %d hens + the duck is %d entries, expected %d"
         % (len(hens), len(slots), 2 + 2 * len(hens) + 2))
# The same rule with the duck appended, and now with the hens' own overflow in
# front of it: three hens plus the duck is exactly ten and drops nothing, four
# hens plus the duck drops the duck, five hens drops the fifth bird and then the
# duck. What may never go is anything ahead of the last thing drawn.
check_drop("with the duck on the line", slots, oam)

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
