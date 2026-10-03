#!/usr/bin/env python3
"""Assert the high-score table, the insert, and the name entry (Phase 6c-3).

The Z80's route between the last life and the title is `LoseLife` ->
`CheckPlayersHighScores` -> `FrontEnd` (Chuckie.asm:4493, :4624, :4664): ten
entries, a descending table, an insert, and a name typed with a cursor. This
covers the whole of it -- the sort's strictness, the shift, the screen, the
alphabet panel, and the way out -- read back out of the running ROM.

Only eight of those ten entries fit this screen; see SCORE_COUNT in
tools/gbdata.py for why, and the layout block below for the rows.

The layout is stated here rather than read from the generator, as
verify_title.py's is, so a generator that emits the wrong rows fails instead of
agreeing with itself. The only things read out of src/score.asm are the sizes
and orderings the decoder genuinely needs: which ASCII characters the tile run
holds, and where its inverted and banner groups start.

    python3 tools/verify_scores.py [rom.gb]
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

SCREEN0, VRAM = 0x9800, 0x8000
SCRN_COLS = 32
SCREEN_ROWS, SCREEN_COLS = 18, 20
HUD_SHADE = 3                        # the shade gbdata.py emits every glyph at

# --- The screen, as the plan lays it out --------------------------------------
HEADING, HEADING_ROW, HEADING_COL = "high score table", 0, 2
COUNT, NAME_LEN, SCORE_LEN = 8, 10, 5
ENTRY_ROW0, ENTRY_COL = 2, 2         # entry 1; the eight run rows 2..9
GRID_ROW, GRID_COL, GRID_COLS = 11, 3, 14
GRID_ROWSTEP = 2                     # the panel's rows, two apart so they do not touch
ALPHABET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ "
GRID_ROWS = len(ALPHABET) // GRID_COLS
GRID_ROWS_AT = tuple(GRID_ROW + i * GRID_ROWSTEP for i in range(GRID_ROWS))
LEGEND = [("PAD move  A type", 15, 2), ("B rub  START done", 17, 1)]
BANNER = list(range(0x8F, 0x97))     # the Z80's default-name banner tiles
BANNER_LEN = len(BANNER)
DEFAULT_SCORE = [0, 0, 1, 0, 0]      # 100, as the data block has it
BLANK = 0                            # index 0 of the run: the space glyph

LIVES_START = 5

# 325: beats the fifth of the eight, so the insert lands mid-table and has real
# entries to shift. 999 live against it shows which one is read.
BANKED = [0, 0, 3, 2, 5]             # 325
LIVE = [0, 0, 9, 9, 9]               # 999: what a death must NOT offer
RANK = 5                             # the first of the eight that 325 beats


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
need = ["wOnTitle", "wOnScores", "wHighScores", "wScore", "wScoreSaved",
        "wLives", "wPlayerDead", "wDeathTimer", "wNameEntry", "wNamePos",
        "wGridRow", "wGridCol", "wNameDone", "wBlinkOn", "wEggsRemaining"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

failed = []
fail = failed.append

# --- The tile run, located by pixels ------------------------------------------
# ScoreGlyphsAscii names the run's first group in ASCII order. Re-encoding the
# source charset the same way and finding the one matching run in VRAM pins the
# base, the tile order and the shade at once, independently of gbdata.py.
#
# It matches the WHOLE run -- glyphs, inverted alphabet, banner -- and not just
# the glyphs, because the BG map cannot see the difference: it holds indices, and
# an index into a tile that never reached VRAM still reads back as the right
# number. That is exactly how 54 of the 89 tiles shipped missing (Start copied
# ScoreTilesEnd - ScoreTiles, and the label sat at the end of the glyph group)
# with a passing screen check.
gfx, _, _, _, _, _ = gbdata.build(ASM)
m = re.search(r"ScoreGlyphsAscii:\n    db ([^\n]+)", open(SCORE_ASM).read())
if not m:
    raise SystemExit("FAIL: %s has no ScoreGlyphsAscii" % SCORE_ASM)
ascii_codes = [int(t, 16) for t in re.findall(r"\$([0-9A-Fa-f]{2})", m.group(1))]

GLYPH_COUNT = score_def("SCORE_GLYPH_COUNT")
INV_FIRST = score_def("SCORE_INV_FIRST")
LOGO_FIRST = score_def("SCORE_LOGO_FIRST")
TILE_COUNT = score_def("SCORE_TILE_COUNT")
DIGIT_FIRST = score_def("SCORE_DIGIT_FIRST")
ENTRY_BYTES = score_def("SCORE_ENTRY_BYTES")

glyph_of = lambda c: bytes(gbdata.to_gb_tile(gfx[c * 8:c * 8 + 8], HUD_SHADE))
want_tiles = ([glyph_of(c) for c in ascii_codes]
              + [gbdata.to_gb_inverted(gfx[ord(ch) * 8:ord(ch) * 8 + 8])
                 for ch in ALPHABET]
              + [glyph_of(c) for c in BANNER])
if TILE_COUNT != len(want_tiles):
    fail("score.asm says %d tiles but the run is %d glyphs, %d inverted and %d "
         "banner" % (TILE_COUNT, len(ascii_codes), len(ALPHABET), len(BANNER)))
if GLYPH_COUNT != len(ascii_codes):
    fail("score.asm says %d glyphs but ScoreGlyphsAscii lists %d"
         % (GLYPH_COUNT, len(ascii_codes)))
if (INV_FIRST, LOGO_FIRST) != (GLYPH_COUNT, GLYPH_COUNT + len(ALPHABET)):
    fail("the run's groups are not where the layout says: inverted at %d, "
         "banner at %d, expected %d and %d"
         % (INV_FIRST, LOGO_FIRST, GLYPH_COUNT, GLYPH_COUNT + len(ALPHABET)))
if (ENTRY_BYTES, DIGIT_FIRST) != (NAME_LEN + SCORE_LEN, ascii_codes.index(0x30)):
    fail("the entry is %d bytes and its zero is at %d, expected %d and %d"
         % (ENTRY_BYTES, DIGIT_FIRST, NAME_LEN + SCORE_LEN,
            ascii_codes.index(0x30)))

# The ROM left alone at boot: the title, and the table it seeded.
pb = harness.boot(ROM, start=False)


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def entry(i):
    """Table entry i, 0-based, as its 15 bytes."""
    a = sym["wHighScores"] + i * ENTRY_BYTES
    return list(pb.memory[a:a + ENTRY_BYTES])


def table():
    return [entry(i) for i in range(COUNT)]


def mine():
    """The entry the name is being typed into: the rank the insert took."""
    return entry(RANK - 1)


def score():
    d = pb.memory[sym["wScore"]:sym["wScore"] + 6]
    return sum(d[i] * 10 ** (4 - i) for i in range(5))


def map_byte(r, c):
    return pb.memory[SCREEN0 + r * SCRN_COLS + c]


vram = bytes(pb.memory[VRAM:VRAM + 256 * 16])
bases = [t for t in range(257 - TILE_COUNT)
         if all(vram[(t + i) * 16:(t + i + 1) * 16] == want_tiles[i]
                for i in range(TILE_COUNT))]
if len(bases) != 1:
    raise SystemExit("FAIL: found %d runs of the score tiles in VRAM (%s), "
                     "expected exactly one -- a group missing or a base wrong"
                     % (len(bases), bases))
BASE = bases[0]
print("score tiles: %d at $%02X (%d glyphs, inverted at +%d, banner at +%d)"
      % (TILE_COUNT, BASE, GLYPH_COUNT, INV_FIRST, LOGO_FIRST))

# --- 1. The seeded table ------------------------------------------------------
# The seeded entries the Z80's data block starts with: a blank, the 8-tile banner
# mid-field, a blank, and a score of 100. Seeded in Start, once per power-on.
seed = [BLANK] + [LOGO_FIRST + n for n in range(BANNER_LEN)] + [BLANK] \
       + DEFAULT_SCORE
t0 = table()
print("seeded entry 1: %s" % t0[0])
if any(e != seed for e in t0):
    bad = [i for i, e in enumerate(t0) if e != seed]
    fail("entries %s are not the source's default name and score: %s"
         % (bad, t0[bad[0]]))
if not reg("wOnTitle"):
    fail("the ROM did not boot to the title")
if reg("wOnScores"):
    fail("the ROM booted onto the high-score table")

# --- 2. A qualifying score, offered and inserted ------------------------------
# The seeded eight are all identical, so an insert that shifted nothing would
# leave the table looking exactly like one that shifted -- the shift has to be
# given something distinguishable to move. Eight descending scores, and a banked
# total that lands in the middle of them: rank 5, so three entries below it
# shift and the eighth falls off the end.
setreg("wScoreSaved", 0)
for i, d in enumerate(BANKED):
    pb.memory[sym["wScoreSaved"] + i] = d

harness.press_start(pb)
if reg("wOnTitle"):
    fail("START did not leave the title")

# 999 live against 175 banked, because the Z80 reads P1Score here:
# CheckPlayersHighScores only runs on the lives-left path, so the last life
# offers the score banked at the end of the last FINISHED level. Written AFTER
# the game starts, or LoadSavedScore on the way in overwrites it with the bank.
setreg("wScore", 0)
for i, d in enumerate(LIVE):
    pb.memory[sym["wScore"] + i] = d
RANKS = [500, 450, 400, 350, 300, 250, 200, 150]
for i, v in enumerate(RANKS):
    pb.memory[sym["wHighScores"] + i * ENTRY_BYTES + NAME_LEN:
              sym["wHighScores"] + i * ENTRY_BYTES + NAME_LEN + SCORE_LEN] = \
        [int(d) for d in "%05d" % v]
seeded = table()
print("seeded scores: %s" % [int("".join(map(str, e[NAME_LEN:]))) for e in seeded])

setreg("wLives", 1)
setreg("wPlayerDead", 1)
setreg("wDeathTimer", 1)
for f in range(300):
    tick(1)
    if reg("wOnScores"):
        break
else:
    fail("the last life never reached the high-score table")
print("table up after %d frames: wOnScores %d wNameEntry %d wScore %d "
      "wScoreSaved %d" % (f + 1, reg("wOnScores"), reg("wNameEntry"),
                          score(), int("".join(map(str, pb.memory[sym["wScoreSaved"]:
                                                               sym["wScoreSaved"] + 5])))))

if not reg("wOnScores"):
    fail("game over left the player somewhere other than the table")
if reg("wOnTitle"):
    fail("wOnTitle is still set on the table, so the front end is confused")
if reg("wNameEntry") != RANK:
    fail("a %d against %s took rank %d, expected %d -- CheckHighScore stops at "
         "the first entry the score is strictly greater than"
         % (int("".join(map(str, BANKED))), RANKS, reg("wNameEntry"), RANK))
t1 = table()
print("after the insert: %s"
      % [int("".join(map(str, e[NAME_LEN:]))) for e in t1])
if t1[RANK - 1][:NAME_LEN] != [BLANK] * NAME_LEN:
    fail("the new entry's name was not blanked for typing: %s"
         % t1[RANK - 1][:NAME_LEN])
if t1[RANK - 1][NAME_LEN:] != BANKED:
    fail("the inserted score is %s, expected the banked %s -- the table is "
         "reading the wrong score" % (t1[RANK - 1][NAME_LEN:], BANKED))
# The whole table, against the shift done by hand: the entries above the rank
# untouched, the player in at the rank, the ones below moved down one slot, and
# the tenth gone. Anything short of that -- no shift at all, a shift the wrong
# way, a rank off by one, a lost byte -- differs from this somewhere.
expected = seeded[:RANK - 1] + [[BLANK] * NAME_LEN + BANKED] + seeded[RANK - 1:COUNT - 1]
if t1 != expected:
    bad = [i for i in range(COUNT) if t1[i] != expected[i]]
    fail("the shift is wrong at entries %s: %s vs the expected %s"
         % (bad, t1[bad[0]], expected[bad[0]]))
if len(t1) != COUNT:
    fail("the table is %d entries, expected %d" % (len(t1), COUNT))

# --- 3. The screen, every cell ------------------------------------------------
# Built from the table actually in WRAM, so the drawing is checked against the
# data and the data against the source: between them a shifted row, a wrong
# column, a dropped entry or a mis-based tile has nowhere to hide.
want = {}


def put(r, c, v):
    if 0 <= r < SCREEN_ROWS and 0 <= c < SCREEN_COLS:
        want[(r, c)] = v


def gid(ch):
    """A character's index in the tile run."""
    return ascii_codes.index(ord(ch))


for j, ch in enumerate(HEADING):
    put(HEADING_ROW, HEADING_COL + j, gid(ch))
for i in range(COUNT):
    e = t1[i]
    for j in range(NAME_LEN):
        put(ENTRY_ROW0 + i, ENTRY_COL + j, e[j])
    for j in range(SCORE_LEN):
        put(ENTRY_ROW0 + i, ENTRY_COL + NAME_LEN + j, DIGIT_FIRST + e[NAME_LEN + j])
for n, ch in enumerate(ALPHABET):
    put(GRID_ROW + (n // GRID_COLS) * GRID_ROWSTEP, GRID_COL + n % GRID_COLS,
        INV_FIRST + n if n == 1 and reg("wBlinkOn") else gid(ch))
for text, r, c in LEGEND:
    for j, ch in enumerate(text):
        put(r, c + j, gid(ch))


def cell_ok(tile, v):
    """v is a run index, or None for a cell nothing should have written."""
    if v is None:
        return tile == 0
    return tile == BASE + v


bad = []
for r in range(SCREEN_ROWS):
    for c in range(SCREEN_COLS):
        if not cell_ok(map_byte(r, c), want.get((r, c))):
            bad.append((r, c, map_byte(r, c), want.get((r, c))))
print("screen: %d cells checked, %s"
      % (SCREEN_ROWS * SCREEN_COLS, "PASS" if not bad else "FAIL (%d)" % len(bad)))
if bad:
    for r, c, got, w in bad[:6]:
        print("  (%2d,%2d) tile $%02X, wanted %s" % (r, c, got, w))
    fail("the table screen does not match the layout, %d cells wrong" % len(bad))

lcdc = pb.memory[0xFF40]
print("table mode: LCDC $%02X OBJ %d WIN %d SCY %d SCX %d"
      % (lcdc, lcdc >> 1 & 1, lcdc >> 5 & 1, pb.memory[0xFF42], pb.memory[0xFF43]))
if not lcdc & 0x80:
    fail("the LCD is off on the table")
if lcdc & 0x02:
    fail("the table draws OBJ, and nothing on it is a sprite")
if lcdc & 0x20:
    fail("the table draws the window band, which belongs to a game")
if (pb.memory[0xFF42], pb.memory[0xFF43]) != (0, 0):
    fail("the table is scrolled: SCY %d SCX %d, expected 0/0"
         % (pb.memory[0xFF42], pb.memory[0xFF43]))

# --- 4. The name entry --------------------------------------------------------
# The cursor starts on 'A' (cell 1), not on the space at cell 0, so that the
# first A press types a letter rather than a leading blank. One step per press,
# so right twice lands on 'C' (cell 3) -- which is also what tells a wPadNew
# gate from a held-button one: a held direction would run, and a held A would
# type every frame.
START_COL = 1
STEPS = 2
LETTER = ALPHABET[START_COL + STEPS]     # 'C'
CELL = START_COL + STEPS
C = gid(LETTER)
harness.tap(pb, "right")
harness.tap(pb, "right")
if (reg("wGridRow"), reg("wGridCol")) != (0, CELL):
    fail("two rights moved the cursor to (%d,%d), expected (0,%d)"
         % (reg("wGridRow"), reg("wGridCol"), CELL))

# The cursor and its blink, sampled: the cell under it must come up inverted
# some frames and plain others, and no cell it has left may stay inverted -- the
# panel is redrawn whole, so a stale cursor anywhere on the row shows up here. A
# single look would only catch whichever half of the blink it landed on.
seen = set()
for _ in range(60):
    tick(1)
    seen.add(map_byte(GRID_ROW, GRID_COL + CELL))
    stray = [c for c in range(GRID_COLS)
             if c != CELL and map_byte(GRID_ROW, GRID_COL + c) >= BASE + INV_FIRST]
    if stray:
        fail("the cursor is still drawn on cells it left: %s" % stray)
print("cursor blink over 60 frames: %s"
      % sorted("$%02X" % t for t in seen))
if BASE + INV_FIRST + CELL not in seen:
    fail("the grid cursor never lit up on cell %d (%s), where the grid should "
         "invert %r" % (CELL, sorted(seen), LETTER))
if BASE + gid(LETTER) not in seen:
    fail("the grid cursor never blinked off on cell %d: only %s, and %r should "
         "come back plain" % (CELL, sorted(seen), LETTER))

harness.tap(pb, "a")
print("after one A: wNamePos %d name %s" % (reg("wNamePos"), mine()[:NAME_LEN]))
if reg("wNamePos") != 1:
    fail("one press typed %d characters, so a held A is repeating rather than "
         "the press edge being used" % reg("wNamePos"))
if mine()[0] != C:
    fail("A typed %d, expected the cell's own glyph index %d" % (mine()[0], C))
harness.tap(pb, "a")
harness.tap(pb, "b")
if reg("wNamePos") != 1 or mine()[:2] != [C, BLANK]:
    fail("A A B left wNamePos %d and %s, expected 1 and [%d, 0]"
         % (reg("wNamePos"), mine()[:NAME_LEN], C))
harness.tap(pb, "b")
if reg("wNamePos"):
    fail("B at the start of the field stepped back past it")

# The Z80 stops at nine (an L running $10..$18 against `CP $19`), and the tenth
# is simply not stored. Twelve more presses is past the field and past the end
# of the row, so a wrap would show up here too.
for _ in range(12):
    harness.tap(pb, "a")
print("after 12 more A: wNamePos %d name %s"
      % (reg("wNamePos"), mine()[:NAME_LEN]))
if reg("wNamePos") != 9:
    fail("the name field took %d characters, expected the Z80's 9"
         % reg("wNamePos"))
if any(v == BLANK for v in mine()[:9]) or mine()[9] != BLANK:
    fail("the field is not 9 characters then a blank: %s" % mine()[:NAME_LEN])

harness.tap(pb, "start")
if reg("wNameDone") != 1:
    fail("START did not finish the name entry")
if reg("wBlinkOn"):
    fail("the cursor is still blinking after the name entry finished")
if not reg("wOnScores"):
    fail("finishing the name entry left the table screen")
after = mine()
print("the typed entry (rank %d): %s" % (RANK, after))

# --- 5. Equal does not displace -----------------------------------------------
# A second game over: this one offers exactly the lowest entry's score, so it
# beats nothing -- CompareScore's flag is only set for a strict `>` -- and the
# table has to come back byte for byte.
before = table()
harness.press_start(pb)
if reg("wOnScores"):
    fail("START did not leave the table for the title")
if not reg("wOnTitle"):
    fail("START on the table did not reach the title")
harness.press_start(pb)
if reg("wOnTitle"):
    fail("START on the title after the table did not begin a game")

setreg("wScoreSaved", 0)
for i, d in enumerate(BANKED):
    pb.memory[sym["wScoreSaved"] + i] = d
LOWEST = [int(d) for d in "%05d" % RANKS[-1]]
for i, d in enumerate(LOWEST):
    pb.memory[sym["wScoreSaved"] + i] = d
setreg("wLives", 1)
setreg("wPlayerDead", 1)
setreg("wDeathTimer", 1)
for f in range(300):
    tick(1)
    if reg("wOnScores"):
        break
else:
    fail("the second game over never reached the table")
print("second table after %d frames: wNameEntry %d" % (f + 1, reg("wNameEntry")))
if reg("wNameEntry"):
    fail("a score equal to the lowest entry took rank %d, when CompareScore's "
         "strict `>` means it takes none" % reg("wNameEntry"))
if table() != before:
    bad = [i for i in range(COUNT) if table()[i] != before[i]]
    fail("a score that did not qualify still changed entries %s" % bad)
if reg("wBlinkOn"):
    fail("a name entry started for a score that did not make the table")
# ...and the screen must not offer one either. The panel and its legend are what
# say "move a cursor and type", so with no rank there is nothing to move and
# nothing to type: drawn anyway, this is the screen that promised a d-pad over a
# grid with no cursor on it -- the control named and dead.
panel_rows = [r for r in GRID_ROWS_AT + tuple(l[1] for l in LEGEND)
              if any(map_byte(r, c) for c in range(SCREEN_COLS))]
print("  panel rows still drawn: %s" % (panel_rows or "none"))
if panel_rows:
    fail("the alphabet panel and its legend are on the table at rows %s under a "
         "score that did not qualify -- the screen promises controls NameEntry, "
         "a no-op at rank 0, cannot answer" % panel_rows)
if any(map_byte(r, c) == BASE + INV_FIRST
       for r in GRID_ROWS_AT for c in range(SCREEN_COLS)):
    fail("a cursor is drawn on the panel under a non-qualifying score")

# --- 6. The route -------------------------------------------------------------
# Table -> title -> a fresh game, with the typed entry still on the table: the
# high scores survive between games in a session, as the original's do.
harness.press_start(pb)
print("after START: wOnScores %d wOnTitle %d"
      % (reg("wOnScores"), reg("wOnTitle")))
if reg("wOnScores") or not reg("wOnTitle"):
    fail("START on the table did not reach the title")
harness.press_start(pb)
print("after a second START: wOnTitle %d lives %d eggs %d score %d"
      % (reg("wOnTitle"), reg("wLives"), reg("wEggsRemaining"), score()))
if reg("wOnTitle"):
    fail("START on the title did not begin a game")
if reg("wLives") != LIVES_START:
    fail("the new game has %d lives, expected %d" % (reg("wLives"), LIVES_START))
if score():
    fail("the new game's score is %d, expected 0" % score())
if table()[RANK - 1] != after:
    fail("the typed entry did not survive the next game: %s vs %s"
         % (table()[RANK - 1], after))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
