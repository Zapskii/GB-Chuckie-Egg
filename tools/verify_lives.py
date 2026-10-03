#!/usr/bin/env python3
"""Assert the life count and the banked score (6c-1).

The Z80 keeps `P1Lives` and spends one per death (`Chuckie.asm:4547`); at zero
every player is out and it goes to the front-end. The port has no front-end yet,
so zero lives starts a new game -- which is what pressing start there would do.

The score is two copies in the Z80: the live `CurrentPlayerScore` the game adds
to, and the player's `P1Score`. `PlayLevel` loads the saved one at the start of a
level, `LevelCompleted` writes the live one back when the level is won, and
`HasLivesRemaining` loads the saved one again after a death -- which is what
makes dying cost the points earned on the fatal attempt.

What this checks, all read back out of the running ROM:

  * a game opens on LIVES_START lives, and the status row's `L` field says so;
  * a death costs exactly one life, keeps the level, replays it from scratch
    (twelve eggs back), and reverts the score to what it was when the level
    began -- checked both on a level that starts at zero and on one that starts
    from a banked, non-zero score, so "reverted" cannot pass as "zeroed";
  * winning a level banks the score, and the next level starts on the banked
    total;
  * the last life is spent like the others, and the death after it is game over
    -- the high-score table, then START to the title, then START to a new game on
    the level the ROM boots into, score zeroed, lives full;
  * the clock running out costs NO life by itself (the settled 6c rule), and
    the death that follows behaves like any other;
  * every thousand points pays one extra life, and only at the crossing --
    a point inside the block pays nothing, and a level that opens on a banked
    score does not pay for its first point.

The level is read from `wCurrentLevel` rather than assumed, so this runs against
any `build/lN.gb`. The first death is driven by a real hen-on-Harry collision so
the whole path is exercised; the rest are driven by the death flag directly, so
the walk is not at the mercy of where the hens wander.
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

LIVES_START = 5
EGGS_PER_LEVEL = 12
HEN_MAX = 5
HEN_NONE = 0xFF
VRAM = 0x8000
LEVEL_WIDTH, LEVEL_HEIGHT = 32, 21
TILE_EGG = 3

HUD_ROW_LEN = 20
HUD_CHARS = "0123456789BESTL"
HUD_SHADE = 3
# The lives field: `L` then two digits, the last column of the row.
LIVES_COL = 16

TIME_STEP = 10


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wLives", "wPlayerDead", "wDeathTimer", "wCurrentLevel", "wLevelDone",
        "wScore", "wScoreSaved", "wLastDigit", "wEggsRemaining", "wHudRow",
        "wTime", "wTimeTick", "wTimeUp", "wTimerRunning", "wHens", "wOnTitle",
        "wOnScores", "wLevelBuffer"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

failed = []
fail = failed.append

pb = harness.boot(ROM)


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def score():
    d = pb.memory[sym["wScore"]:sym["wScore"] + 6]
    return sum(d[i] * 10 ** (4 - i) for i in range(5))


def set_score(v):
    pb.memory[sym["wScore"]:sym["wScore"] + 5] = \
        [v // 10 ** (4 - i) % 10 for i in range(5)]


def set_banked(v):
    """The score a level loads, and the one a death falls back to."""
    pb.memory[sym["wScoreSaved"]:sym["wScoreSaved"] + 5] = \
        [v // 10 ** (4 - i) % 10 for i in range(5)]


def cell(r, c):
    return sym["wLevelBuffer"] + r * LEVEL_WIDTH + c


def stand_on(r, c):
    """Put Harry where PlayerPickUp samples cell (r, c), as verify_eggs.py does:
    the Z80 samples ((y-8)/8, (x+8)/8), and an x that is a multiple of 8 keeps
    CheckForFalling from walking him off the cell."""
    setreg("wPlayerX", c * 8 - 8)
    setreg("wPlayerY", r * 8 + 8)
    setreg("wPlayerInAir", 0)


def eat(r, c):
    """Collect one egg at (r, c) and report what it added to the score.

    A real pickup through PlayerPickUp and AddToScore -- the extra life is paid
    by the path the game pays it on, not by poking AddToScore's inputs.
    """
    pb.memory[cell(r, c)] = TILE_EGG
    stand_on(r, c)
    before = score()
    tick(1)
    return score() - before


def put_hen(slot, x, y, d, anim=0):
    a = sym["wHens"] + slot * 4
    pb.memory[a:a + 4] = [x, y, d, anim]


def park_hens():
    for s in range(HEN_MAX):
        put_hen(s, HEN_NONE, 0, 0)


# --- the status row's lives field, decoded from its own pixels ---------------
# The glyph run is located by matching the reference charset re-encoded at the
# HUD's shade, so a tile-order or column drift fails here rather than looking
# plausible -- the same identification verify_hud.py uses.
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


def hud_lives():
    """The `Lnn` field of wHudRow, as the string it shows."""
    row = pb.memory[sym["wHudRow"] + LIVES_COL:sym["wHudRow"] + HUD_ROW_LEN]
    return "".join(" " if t == 0 else HUD_CHARS[t - base] for t in row)


def check_hud(where):
    want = "L%02d " % reg("wLives")
    got = hud_lives()
    print("  hud %r lives %d (%s)" % (got, reg("wLives"), where))
    if got != want:
        fail("the status row shows %r for lives where wLives is %d, expected %r "
             "(%s)" % (got, reg("wLives"), want, where))


def wait_reload(limit=120):
    """Wait out a death's reload, not just the death flag.

    ResetHens -- which LoadLevel calls -- clears wPlayerDead part way through
    the reload, so the flag goes clear before the level has finished being
    written. A new death poked into that window is wiped by the same ResetHens
    and goes missing, which is why the flag has to stay clear for a few frames
    rather than just once.
    """
    steady = 0
    for f in range(limit):
        tick(1)
        steady = steady + 1 if not reg("wPlayerDead") else 0
        if steady >= 4:
            return f + 1
    fail("the level never finished reloading after a death")
    return None


def die(where):
    """Kill Harry and wait out the freeze and the reload."""
    setreg("wPlayerDead", 1)
    setreg("wDeathTimer", 1)
    wait_reload()


def check_death(where, lives, level, banked):
    """Everything a death should have done, read after the reload."""
    print("  %s: lives %d level %d score %d (banked %d) eggs %d"
          % (where, reg("wLives"), reg("wCurrentLevel"), score(), banked,
             reg("wEggsRemaining")))
    if reg("wLives") != lives:
        fail("%s: %d lives, expected %d" % (where, reg("wLives"), lives))
    if reg("wCurrentLevel") != level:
        fail("%s: level %d, expected it to stay at %d"
             % (where, reg("wCurrentLevel"), level))
    if score() != banked:
        fail("%s: the score is %d, expected the level's start value %d -- a "
             "death forfeits the points earned on the fatal attempt"
             % (where, score(), banked))
    if reg("wEggsRemaining") != EGGS_PER_LEVEL:
        fail("%s: replayed with %d eggs, expected %d"
             % (where, reg("wEggsRemaining"), EGGS_PER_LEVEL))
    check_hud(where)


L0 = reg("wCurrentLevel")
print("boots into level index %d with %d lives, hud %r"
      % (L0, reg("wLives"), hud_lives()))

# --- 1. A game opens on a full set -----------------------------------------
if reg("wLives") != LIVES_START:
    fail("a fresh game has %d lives, expected %d" % (reg("wLives"), LIVES_START))
if score():
    fail("a fresh game opens on a score of %d, expected 0" % score())
check_hud("at boot")

# --- 2. A hen killing Harry costs one life, and the points he earned --------
# The only death here driven by the game itself; it proves the collision path
# lands on the same counter the rest of the walk pokes. The banked score is what
# the level opened on -- zero here -- so this is the weak half of the pair; the
# non-zero case is section 4.
banked = score()
set_score(1230)
px, py = reg("wPlayerX"), reg("wPlayerY")
put_hen(0, px, py - 10, 1)             # hen on Harry, facing right
tick(2)
if not reg("wPlayerDead"):
    fail("the hen on Harry did not kill him (player=(%d,%d) hen=%s)"
         % (px, py, tuple(pb.memory[sym["wHens"]:sym["wHens"] + 4])))
park_hens()
# Skip the 90-frame freeze -- verify_hens.py already asserts the hen's death
# starts one. What is under test here is the counter the freeze ends on.
setreg("wDeathTimer", 1)
wait_reload()
check_death("after a hen death", LIVES_START - 1, L0, banked)

# --- 3. Winning a level banks the score -------------------------------------
# wLevelDone drives the same NextLevel a real pickup does -- the pickup itself
# is verify_eggs.py's and verify_hud.py's job -- and the bonus countdown is
# switched off so the banked total is exactly the score set here.
BANKED = 4000
L1 = L0 + 1
setreg("wTimerRunning", 0)
set_score(BANKED)
setreg("wLevelDone", 1)
for _ in range(120):
    tick(1)
    if reg("wCurrentLevel") == L1:
        break
else:
    fail("the level never advanced after wLevelDone")
# And then the reload itself, which is not instant: the level change puts up
# its announcement ("LEVEL n") first, and wLevelDone clears when the level is
# down. Waiting only a few frames here used to be enough; a death poked while
# the announcement is up is wiped by ResetHens, silently, exactly as
# wait_reload's comment describes.
for _ in range(120):
    tick(1)
    if not reg("wLevelDone"):
        break
else:
    fail("the level never finished reloading after wLevelDone")
print("after winning: level %d score %d eggs %d done %d"
      % (reg("wCurrentLevel"), score(), reg("wEggsRemaining"), reg("wLevelDone")))
if reg("wCurrentLevel") != L1:
    fail("the level is %d after winning, expected %d" % (reg("wCurrentLevel"), L1))
if score() != BANKED:
    fail("the score is %d after winning, expected the banked %d -- a level "
         "must carry its points forward" % (score(), BANKED))
banked = score()

# --- 4. ...and dying on the next level reverts to the banked score ----------
# The assertion section 2 could not make: the level starts on a non-zero score,
# so "the score came back" cannot pass by the score having been zeroed.
set_score(4321)
lives = LIVES_START - 2                # the hen death spent one already
die("on the banked level")
check_death("after a death on a banked level", lives, L1, banked)

# --- 5. The walk down: each death costs exactly one --------------------------
while lives > 1:
    lives -= 1
    set_score(900 + lives)
    die("at %d lives" % (lives + 1))
    check_death("at %d lives" % lives, lives, L1, banked)

# --- 6. Spending the last life is game over ---------------------------------
# The Z80 gets here through LoseLife -> CheckPlayersHighScores -> the front-end
# (Chuckie.asm:4493, :4624), so the last life lands on the high-score table, and
# START there reaches the title -- which is where the ROM boots, and what START
# on it begins the next game from. This section runs the whole route.
before = reg("wLives")
# Zero the banked total first: 0 does not beat the seeded 100, so no name entry
# opens between the table and the title and one START each is the whole route.
# Typing a name is verify_scores.py's job.
setreg("wScoreSaved", 0)
pb.memory[sym["wScoreSaved"]:sym["wScoreSaved"] + 5] = [0] * 5
die("on the last life")
print("after the last life: lives %d level %d score %d table %d title %d"
      % (reg("wLives"), reg("wCurrentLevel"), score(), reg("wOnScores"),
         reg("wOnTitle")))
if before != 1:
    fail("the walk did not reach one life (it had %d)" % before)
if not reg("wOnScores"):
    fail("game over did not put the high-score table up, it went straight back "
         "into play")
if reg("wOnTitle"):
    fail("wOnTitle is set with the table up, so the front end is confused")
# The screen is the table's, which means the camera is home and the band is off
# -- a level left under it would show through it.
if pb.memory[0xFF42] or pb.memory[0xFF43]:
    fail("the table is scrolled (SCY %d SCX %d), so a level is still showing"
         % (pb.memory[0xFF42], pb.memory[0xFF43]))

# ...and START there is the title, the same screen the ROM boots to.
harness.press_start(pb)
print("after START on the table: table %d title %d"
      % (reg("wOnScores"), reg("wOnTitle")))
if reg("wOnScores") or not reg("wOnTitle"):
    fail("START on the table did not reach the title")
if pb.memory[0xFF42] or pb.memory[0xFF43]:
    fail("the title is scrolled (SCY %d SCX %d), so a level is still showing"
         % (pb.memory[0xFF42], pb.memory[0xFF43]))

# ...and START there is a fresh game, on the level the ROM boots into.
harness.press_start(pb)
print("after START on the title: lives %d level %d score %d title %d"
      % (reg("wLives"), reg("wCurrentLevel"), score(), reg("wOnTitle")))
if reg("wOnTitle"):
    fail("START did not leave the title")
if reg("wLives") != LIVES_START:
    fail("the game START began has %d lives, expected %d"
         % (reg("wLives"), LIVES_START))
if reg("wCurrentLevel") != L0:
    fail("the game START began is on level %d, expected the boot level %d"
         % (reg("wCurrentLevel"), L0))
if score():
    fail("the game START began has a score of %d, expected it zeroed -- a new "
         "game has nothing banked to fall back on" % score())
if reg("wEggsRemaining") != EGGS_PER_LEVEL:
    fail("the game START began has %d eggs, expected %d"
         % (reg("wEggsRemaining"), EGGS_PER_LEVEL))
check_hud("after START on the title")

# --- 7. The clock running out costs nothing by itself ------------------------
# The settled 6c rule: a time-up stops the clock and stops the bonus countdown
# from being scored, and that is all -- Harry plays on until something kills
# him, and THAT death costs a life like any other. verify_hud.py checks the
# clock and the bonus; this checks the counter, which is the thing 6c-1 added.
banked = score()
lives_before = reg("wLives")
park_hens()
pb.memory[sym["wTime"]:sym["wTime"] + 3] = [0, 0, 1]
setreg("wTimeTick", 1)
for f in range(2 * TIME_STEP + 2):
    tick(1)
    if reg("wTimeUp"):
        break
else:
    fail("the clock never ran out")
print("clock out after %d frames: time %s timeUp %d lives %d"
      % (f + 1, list(pb.memory[sym["wTime"]:sym["wTime"] + 3]), reg("wTimeUp"),
         reg("wLives")))
for _ in range(2 * TIME_STEP + 4):
    tick(1)
print("  %d frames later: timeUp %d live %d lives %d"
      % (2 * TIME_STEP + 4, reg("wTimeUp"), not reg("wPlayerDead"), reg("wLives")))
if reg("wPlayerDead"):
    fail("the clock running out killed Harry")
if reg("wLives") != lives_before:
    fail("the clock running out costs lives: %d, expected %d"
         % (reg("wLives"), lives_before))

# ...and the death that follows is unremarkable: one life, the banked score.
set_score(777)
die("after the clock ran out")
check_death("the death after a time-up", lives_before - 1, L0, banked)

# --- 8. The extra life: one every thousand points ---------------------------
# The Z80's rule (Chuckie.asm:3916): after the points are added, compare the
# score's THOUSANDS digit -- +1, since the digits run from +0 with the units at
# +4 -- against LastDigitValue, its shadow, and pay a life only when the two
# differ. That digit moves every 1 000 and nothing else, so the comparison is
# what makes the life land once per block instead of once per point. The Z80
# draws a hat for it and stops at six; this HUD shows a count instead.
#
# The points come from real eggs at a cell verify_eggs.py already proved out, so
# AddToScore is reached the way the game reaches it. The level is reloaded for
# each case rather than having its score poked under a live level, because the
# reload is also what puts the shadow into a known state -- a death loads the
# banked score and re-syncs the shadow to it (the Z80's PlayLevel, :5947).
park_hens()
per_egg = 10 * (min(reg("wCurrentLevel") >> 2, 9) + 1)
R, C = 12, 6
print("the extra life: an egg is worth %d" % per_egg)

# (a) Crossing ten thousand pays exactly one. The level opens on a banked 9990
# and one egg carries the thousands digit from 9 to 0 -- the crossing is a
# thousand boundary too, so this case alone does not pin which one the rule is;
# (d) below does. The shadow is poked stale
# first: left to itself it holds whatever the last point of the previous section
# stored, and a shadow of 0 would agree with the digit after the crossing and
# make this pass for the wrong reason.
set_score(9990)
set_banked(9990)
setreg("wLastDigit", 0)
die("to reload on a banked 9990")
park_hens()
lives = reg("wLives")
got = eat(R, C)
print("egg at 9990: +%d -> score %d, lives %d -> %d"
      % (got, score(), lives, reg("wLives")))
if score() != 9990 + per_egg:
    fail("the egg on a banked 9990 scored %d, leaving %d, expected %d -- the "
         "level did not open on the banked score"
         % (got, score(), 9990 + per_egg))
if reg("wLives") != lives + 1:
    fail("crossing ten thousand paid %d lives, expected exactly one"
         % (reg("wLives") - lives))
check_hud("after the extra life")

# (b) ...and once, not on every point after it: the next egg is inside the new
# block, and its thousands digit is the one just stored.
lives = reg("wLives")
got = eat(R, C)
print("egg inside the new block: +%d -> score %d, lives %d"
      % (got, score(), reg("wLives")))
if reg("wLives") != lives:
    fail("a point inside the ten-thousand block paid another life (%d -> %d): "
         "the life must land at the crossing only"
         % (lives, reg("wLives")))

# (c) A level start pays nothing. The shadow is poked stale -- deliberately not
# the digit the loaded score has -- so a level that forgot to re-sync it would
# see the first point as a crossing and hand out a free life. This is the half
# of the rule the Z80's PlayLevel re-sync exists for, and it is invisible on a
# level that opens on 0, which is every level of a fresh game.
set_score(4000)
set_banked(4000)
setreg("wLastDigit", 0)
die("to reload on a banked 4000 with a stale shadow")
park_hens()
print("after the reload: score %d shadow %d (the banked digit is 4)"
      % (score(), reg("wLastDigit")))
if reg("wLastDigit") != 4:
    fail("the level reload left the extra life's shadow at %d with the score at "
         "%d, expected it re-synced to 4 -- a level start must not pay"
         % (reg("wLastDigit"), score()))
lives = reg("wLives")
got = eat(R, C)
print("first egg of the level: +%d -> score %d, lives %d"
      % (got, score(), reg("wLives")))
if score() != 4000 + per_egg:
    fail("the level did not open on the banked 4000: the egg scored %d, "
         "leaving %d" % (got, score()))
if reg("wLives") != lives:
    fail("the first point of a level that opened on a banked 4000 paid a life "
         "(%d -> %d), so the shadow is not re-synced at a level start"
         % (lives, reg("wLives")))

# (d) And the block is a THOUSAND, which is what the digit the Z80 reads
# actually is. Everything above crosses 10 000 because that is where a
# thousands digit also turns over, so those three cases pass under either
# reading and none of them pins it. A banked 990 turns the digit from 0 to 1,
# and only the thousands-digit rule pays there: a ten-thousands-digit rule
# (the reading "one life per 10 000 points" implies) would see no change at all.
set_score(990)
set_banked(990)
setreg("wLastDigit", 0)
die("to reload on a banked 990")
park_hens()
lives = reg("wLives")
got = eat(R, C)
print("egg at 990: +%d -> score %d, lives %d -> %d"
      % (got, score(), lives, reg("wLives")))
if score() != 990 + per_egg:
    fail("the egg on a banked 990 scored %d, leaving %d, expected %d"
         % (got, score(), 990 + per_egg))
if reg("wLives") != lives + 1:
    fail("crossing one thousand paid %d lives, expected exactly one -- the "
         "digit AddToScore watches (wScore+1, the thousands) changed, so the "
         "block is a thousand and the comment's 10 000 is wrong"
         % (reg("wLives") - lives))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
