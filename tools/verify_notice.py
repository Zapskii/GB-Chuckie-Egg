#!/usr/bin/env python3
"""Assert the three announcements (Phase 7).

The Z80 has one routine for all of them -- `ScrollTextLine` (Chuckie.asm:5051),
at three call sites: the level's number as one closes (:4464, in
NextPlayerPlayLevel), "OUT OF TIME !" on a death after the clock had already run
out (:4518), and "game over " when the last life goes (:4559). It blanks the
screen and sweeps the word across it; the port blanks the same screen and holds
the word still, since a pixel scroll of the BG here is a camera move, not a
print.

What this checks, all read back out of the running ROM:

  * each announcement appears on the real route that raises it -- a level change
    driven by wLevelDone, and the two deaths driven by a real hen-on-Harry
    collision, so KillPlayer's choice of word is exercised rather than poked;
  * the word on the screen is the record's, glyph for glyph, decoded through
    the run's own index-to-ASCII table and pinned to pixels against the source
    charset -- so a wrong tile base or a shifted index cannot pass;
  * the level's digit is the level it just moved to, off-by-one included;
  * the screen really is blank behind the word: nothing else in map 0, the
    camera home, and the sprites and the window band switched off -- which is
    what wOnNotice buys, and would all fail if the handler's draw pass ran;
  * a death with lives still in hand says nothing, and freezes instead -- the
    Z80's own distinction between the two death paths.

    python3 tools/verify_notice.py [rom.gb]
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
SCORE_ASM = "src/score.asm"

SCREEN0, SCRN_BYTES = 0x9800, 1024
SCREEN_COLS = 32
HUD_SHADE = 3
LCDC_OBJON, LCDC_WINON = 0x02, 0x20

HEN_MAX = 5
HEN_NONE = 0xFF
DEATH_FREEZE_MIN = 1                 # a death in hand sets DEATH_DELAY, > this


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


def score_def(name):
    """A DEF out of the generated src/score.asm."""
    m = re.search(r"^DEF %s\s+EQU\s+(\d+)" % name, open(SCORE_ASM).read(), re.M)
    if not m:
        raise SystemExit("FAIL: DEF %s is not in %s" % (name, SCORE_ASM))
    return int(m.group(1))


sym = symbols(SYM)
need = ["wOnNotice", "wCurrentLevel", "wLevelDone", "wLives", "wPlayerDead",
        "wDeathTimer", "wTimeUp", "wHens", "wPlayerX", "wPlayerY", "wOnScores",
        "NoticeLevel", "NoticeGameOver", "NoticeTimeUp"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

# The run's index-to-character table, emitted beside the tiles: index 0 is the
# space glyph. This is what turns a tile index back into the letter it draws.
m = re.search(r"^ScoreGlyphsAscii:\n\s+db ((?:\$[0-9A-F]{2},?)+\n?)+",
              open(SCORE_ASM).read(), re.M)
if not m:
    raise SystemExit("FAIL: ScoreGlyphsAscii is not in %s" % SCORE_ASM)
glyphs = [chr(int(x, 16)) for x in re.findall(r"\$([0-9A-F]{2})", m.group(0))]
NOTICE_TENS = score_def("NOTICE_TENS")
NOTICE_DIGIT = score_def("NOTICE_DIGIT")

with open(ROM, "rb") as f:
    rom = f.read()


def record(name):
    """The announcement as the ROM holds it: a row, a column, a cell count,
    then that many glyph indices. LEVEL's last TWO indices are NOTICE_TENS and
    NOTICE_DIGIT -- the level's number is two cells, as the Z80's own text has
    it, and the tens is the blank glyph below level ten."""
    a = sym[name]
    row, col, n = rom[a], rom[a + 1], rom[a + 2]
    return row, col, [rom[a + 3 + i] for i in range(n)]


def spell(indices, tens=" ", digit=None):
    """The indices as the text they draw. NOTICE_TENS is blank by default --
    which is what the ROM itself writes there under level ten -- and
    NOTICE_DIGIT is the caller's to fill."""
    out = ""
    for i in indices:
        if i == NOTICE_DIGIT:
            out += digit
        elif i == NOTICE_TENS:
            out += tens
        elif i < len(glyphs):
            out += glyphs[i]
        else:
            out += "?"
    return out


failed = []
fail = failed.append

pb = harness.boot(ROM)

# --- The run's own pixels, so the tile base and the index order are pinned ----
# Located by matching the whole glyph table against the source charset
# re-encoded the way gbdata.py emits it -- verify_lives.py's identification of
# the status row, and the reason a shifted index or a wrong base fails here
# rather than spelling something plausible. The run is found rather than read
# from SCORE_TILE_BASE because that DEF is an expression in main.asm; this way
# it is pinned by pixels and never taken on trust.
gfx, _, _, _, _, _ = gbdata.build(ASM)
vram = bytes(pb.memory[0x8000:0x8000 + 256 * 16])
want_tiles = [bytes(gbdata.to_gb_tile(gfx[ord(ch) * 8:ord(ch) * 8 + 8], HUD_SHADE))
              for ch in glyphs]
bases = [t for t in range(257 - len(glyphs))
         if all(vram[(t + i) * 16:(t + i + 1) * 16] == want_tiles[i]
                for i in range(len(glyphs)))]
if len(bases) != 1:
    raise SystemExit("FAIL: found %d runs of the score glyphs in VRAM (%s), "
                     "expected exactly one" % (len(bases), bases))
TILE_BASE = bases[0]
print("the score run is at tile %d, %d glyphs, index %d is %r"
      % (TILE_BASE, len(glyphs), glyphs.index("!"), "!"))


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def park_hens():
    for s in range(HEN_MAX):
        pb.memory[sym["wHens"] + s * 4:sym["wHens"] + s * 4 + 4] = [HEN_NONE, 0, 0, 0]


def hen_kill(limit=8):
    """Put a hen on Harry and wait for the collision, as verify_lives.py does.

    The real path on purpose: KillPlayer is where the word is chosen, so poking
    wPlayerDead would test everything except the thing under test.
    """
    px, py = reg("wPlayerX"), reg("wPlayerY")
    pb.memory[sym["wHens"]:sym["wHens"] + 4] = [px, py - 10, 1, 0]
    for _ in range(limit):
        tick(1)
        if reg("wPlayerDead"):
            break
    else:
        fail("the hen on Harry did not kill him (player=(%d,%d))" % (px, py))
    park_hens()


def shown():
    """The notice line as the map has it: (row, first column, the tiles).

    Also asserts that the line is the only thing on the map -- the level the
    reload wrote is gone behind it, because ShowNotice blanked the whole map
    before it drew. What the per-frame draw pass would put back over the top is
    the camera, the window band and the sprites, and check_notice reads those
    off the registers: the map cells are not where that shows up.
    """
    m = list(pb.memory[SCREEN0:SCREEN0 + SCRN_BYTES])
    rows = sorted({i // SCREEN_COLS for i, v in enumerate(m) if v})
    if len(rows) != 1:
        fail("the map has text on %d rows (%s) under a notice, expected the one "
             "the word is on -- something else is drawing over it"
             % (len(rows), rows[:4]))
        return None
    r = rows[0]
    cells = m[r * SCREEN_COLS:(r + 1) * SCREEN_COLS]
    run = [c for c in cells if c]
    c0 = cells.index(run[0])
    if cells[c0:c0 + len(run)] != run:
        fail("the notice on row %d is not one run of cells: %s" % (r, cells))
        return None
    return r, c0, run


def wait_clear(name, where, limit=200, steady=4):
    """Wait for a flag to stay clear, not just to be clear once.

    A reload clears wPlayerDead part way through -- ResetHens does it -- so a
    hen parked on the first clear is wiped and goes missing, which is the trap
    verify_lives.py's wait_reload documents. Four clear frames in a row is the
    same test.
    """
    n = 0
    for _ in range(limit):
        tick(1)
        n = n + 1 if not reg(name) else 0
        if n >= steady:
            return True
    fail("%s: %s never settled clear" % (where, name))
    return False


def wait_notice_down(where, limit=200):
    for _ in range(limit):
        tick(1)
        if not reg("wOnNotice"):
            return True
    fail("%s: the announcement never came down" % where)
    return False


def wait_notice(where, limit=6):
    for _ in range(limit):
        tick(1)
        if reg("wOnNotice"):
            return True
    fail("%s: no announcement came up (wOnNotice %d)" % (where, reg("wOnNotice")))
    return False


def check_notice(where, name, word, tens=" ", digit=None):
    """The record, the screen and the hardware state, all against each other."""
    row, col, indices = record(name)
    want = spell(indices, tens, digit)
    if want != word:
        fail("%s: the %s record spells %r, expected %r -- the announcement's own "
             "text is wrong" % (where, name, want, word))
    got = shown()
    if got is None:
        return
    r, c, run = got
    chars = "".join(glyphs[t - TILE_BASE] if 0 <= t - TILE_BASE < len(glyphs)
                    else "?" for t in run)
    print("  %s: row %d col %d %r" % (where, r, c, chars))
    if (r, c) != (row, col):
        fail("%s: the word is at row %d col %d, the record puts it at %d,%d"
             % (where, r, c, row, col))
    if chars != want:
        fail("%s: the screen spells %r, expected %r" % (where, chars, want))
    if pb.memory[0xFF42] or pb.memory[0xFF43]:
        fail("%s: the notice is scrolled (SCY %d SCX %d), so the camera is still "
             "running" % (where, pb.memory[0xFF42], pb.memory[0xFF43]))
    lcdc = pb.memory[0xFF40]
    if lcdc & LCDC_OBJON:
        fail("%s: sprites are on under a notice (LCDC $%02X)" % (where, lcdc))
    if lcdc & LCDC_WINON:
        fail("%s: the window band is on under a notice (LCDC $%02X)" % (where, lcdc))


def level_cells(n):
    """The level's two cells, as SetLevelDigits writes them.

    The Z80's own arithmetic, in its own shape (Chuckie.asm:4431-4460): the
    `CP $C8` / `CP $64` subtract pair, then a repeated subtract of ten for the
    tens digit, which is left BLANK rather than zero when it comes out zero. So
    the number wraps at a hundred but the display does not gain a leading zero
    with it -- level 100 reads "LEVEL  0", not "LEVEL 00". (Past 299 the Z80's
    single subtract leaves a tens digit of 10 or more, which is not a level any
    game reaches; this mirrors it rather than tidying it.)
    """
    if n >= 200:
        n -= 200
    elif n >= 100:
        n -= 100
    tens, units = divmod(n, 10)
    return (" " if tens == 0 else str(tens)), str(units)


def level_text(n):
    return "LEVEL " + "".join(level_cells(n))


park_hens()
L0 = reg("wCurrentLevel")
print("boots into level index %d, wOnNotice %d" % (L0, reg("wOnNotice")))

# --- 1. A level closing says its number --------------------------------------
# The Z80 prints this in NextPlayerPlayLevel (:4464), i.e. on a *completed*
# level; a death goes straight to the reload and says nothing. wLevelDone drives
# the same NextLevel a real last egg does.
setreg("wLevelDone", 1)
if wait_notice("a level change"):
    # NextLevel has already stepped wCurrentLevel, and ShowNotice reads it to fill
    # the two cells -- so this is the level it moved *to*, read live.
    tens, units = level_cells(reg("wCurrentLevel") + 1)
    check_notice("a level change", "NoticeLevel",
                 level_text(reg("wCurrentLevel") + 1), tens=tens, digit=units)
    wait_notice_down("a level change")
    # ...and then the reload the notice was the front of, which is what leaves
    # the level playable again. A hen parked before it lands is wiped by
    # ResetHens and the rest of this check would be testing nothing.
    wait_clear("wLevelDone", "after a level change")

# --- 1b. The number is two cells, and it wraps at a hundred -------------------
# The counter is unbounded, so the interesting levels are the ones whose number
# needs the second cell. Poked rather than played to: ShowNotice reads
# wCurrentLevel, and NextLevel steps it once more before raising the word.
#
# The bonus countdown is switched off first: it runs before the word goes up and
# its length is the level's own bonus, so it would put the announcement's frame
# at the mercy of the number being tested.
for want_n, note in ((12, "a two-digit level"), (100, "level 100")):
    park_hens()
    setreg("wTimerRunning", 0)
    setreg("wCurrentLevel", want_n - 2)         # NextLevel's INC lands on want_n - 1
    setreg("wLevelDone", 1)
    if wait_notice(note, 12):
        n = reg("wCurrentLevel") + 1
        tens, units = level_cells(n)
        check_notice(note, "NoticeLevel", level_text(n), tens=tens, digit=units)
        print("    (counter %d, so level %d reads %r)"
              % (reg("wCurrentLevel"), n, level_text(n)))
        wait_notice_down(note)
        wait_clear("wLevelDone", "after " + note)

# --- 2. A death with lives in hand says nothing, and freezes -----------------
# KillPlayer's first branch: DEATH_DELAY of freeze, no word. If the announcement
# were raised here too, every death would blank the level for a beat.
park_hens()
setreg("wLives", 3)
hen_kill()
if reg("wOnNotice"):
    fail("a death with lives in hand put an announcement up, expected only the "
         "freeze")
if reg("wDeathTimer") <= DEATH_FREEZE_MIN:
    fail("a death with lives in hand left wDeathTimer at %d, expected the "
         "freeze" % reg("wDeathTimer"))
print("  a death in hand: wOnNotice %d, freeze %d frames"
      % (reg("wOnNotice"), reg("wDeathTimer")))
setreg("wDeathTimer", 1)                 # skip the freeze the rest of the suite owns
wait_clear("wPlayerDead", "after a death in hand")
park_hens()

# --- 3. A death after the clock ran out says OUT OF TIME ! -------------------
# The Z80's own gate (:4514): the TimeRemaining sentinel, which is the port's
# wTimeUp. One word, not two -- where the Z80 scrolls "OUT OF TIME !" and then
# "game over " in sequence on a last life, the port shows the first, which is
# the one that says what happened.
setreg("wTimeUp", 1)
hen_kill()
if wait_notice("a death after time up"):
    check_notice("after the clock ran out", "NoticeTimeUp", "OUT OF TIME !")
wait_notice_down("a death after time up")
setreg("wTimeUp", 0)
wait_clear("wPlayerDead", "after a death on a spent clock")
park_hens()

# --- 4. The last life says GAME OVER -----------------------------------------
park_hens()
setreg("wLives", 1)
hen_kill()
if wait_notice("the last life"):
    check_notice("the last life", "NoticeGameOver", "GAME OVER")
# ...and the notice is the beat before the table, not a screen of its own: the
# route on past it is verify_title.py's and verify_lives.py's.
wait_notice_down("the last life")
for _ in range(30):
    tick(1)
    if reg("wOnScores"):
        break
print("after the announcement: table %d notice %d"
      % (reg("wOnScores"), reg("wOnNotice")))
if not reg("wOnScores"):
    fail("the last life's announcement did not lead to the high-score table")

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
