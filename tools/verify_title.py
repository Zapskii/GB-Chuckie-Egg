#!/usr/bin/env python3
"""Assert the title, and everything the front end does from it (6c-2, 6c-5).

The ROM boots to the title, as the Z80's does (`FrontEnd`, Chuckie.asm:4011),
and a game over comes back to it -- by way of the high-score table, as the Z80's
does. So this covers a mode the rest of the suite only passes through, plus the
three ways out of it: START begins a game, START on the table leaves for the
title, and SELECT opens the instructions (§7), which START then leaves for a
game the same way.

Everything is read back out of the running ROM. The glyphs are identified by
their own pixels, matched against the *source* charset re-encoded the same way,
exactly as verify_hud.py finds the status font -- so the tile order, the base
and the shade are all pinned by pixels rather than by trusting the generator
that emitted them. Two runs are located that way, the title's and the score
run's, because the instructions and the title's SELECT hint are drawn from the
second.

    python3 tools/verify_title.py [rom.gb]
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
TITLE_ASM = "src/title.asm"
SCORE_ASM = "src/score.asm"

SCREEN0, VRAM = 0x9800, 0x8000
SCRN_COLS = 32
TITLE_ROWS = 18                      # the title owns the whole screen, 0..17
HUD_SHADE = 3                        # the shade gbdata.py emits every glyph at

LIVES_START = 5
EGGS_PER_LEVEL = 12
MAP_ROW0 = 21                        # DrawLevel puts buffer row 0 here


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


def asm_def(name, path):
    """A DEF out of a generated src/*.asm."""
    m = re.search(r"^DEF %s\s+EQU\s+(\d+)" % name, open(path).read(), re.M)
    if not m:
        raise SystemExit("FAIL: DEF %s is not in %s" % (name, path))
    return int(m.group(1))


sym = symbols(SYM)
need = ["wOnTitle", "wOnScores", "wLives", "wScore", "wScoreSaved",
        "wEggsRemaining", "wCurrentLevel", "wPlayerDead", "wDeathTimer",
        "wMusicPtr", "wLevelBuffer"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

failed = []
fail = failed.append

# The title, with the ROM left alone -- no START, so what is read below is the
# boot state and not a game's.
pb = harness.boot(ROM, start=False)


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def word(name):
    """A little-endian 16-bit WRAM variable."""
    a = sym[name]
    return pb.memory[a] | pb.memory[a + 1] << 8


def score():
    d = pb.memory[sym["wScore"]:sym["wScore"] + 6]
    return sum(d[i] * 10 ** (4 - i) for i in range(5))


def map_byte(r, c):
    return pb.memory[SCREEN0 + r * SCRN_COLS + c]


# --- 1. The mode --------------------------------------------------------------
# EnterTitle writes LCDC_BASE with OBJ and WIN cleared. OBJ is the load-bearing
# one: nothing has written OAM at boot, and on hardware an unwritten OAM is
# noise rather than the blank sprites an emulator hands back. WIN is the status
# band, which belongs to a game.
lcdc, scy, scx = pb.memory[0xFF40], pb.memory[0xFF42], pb.memory[0xFF43]
print("title mode: wOnTitle %d LCDC $%02X OBJ %d WIN %d SCY %d SCX %d LYC %d"
      % (reg("wOnTitle"), lcdc, lcdc >> 1 & 1, lcdc >> 5 & 1, scy, scx,
         pb.memory[0xFF45]))
if not reg("wOnTitle"):
    fail("the ROM did not boot to the title")
if not lcdc & 0x80:
    fail("the LCD is off on the title")
if lcdc & 0x02:
    fail("the title draws OBJ, which at boot is uninitialised")
if lcdc & 0x20:
    fail("the title draws the window band, which belongs to a game")
if (scy, scx) != (0, 0):
    fail("the title is scrolled: SCY %d SCX %d, expected 0/0" % (scy, scx))
# The band's raster split belongs to a game, but EnterTitle leaves the STAT
# configuration alone -- so LYC and the STAT source must still be set for
# StartGame's re-enabled window to land in the right place.
if pb.memory[0xFF45] != 8 or not pb.memory[0xFF41] & 0x40:
    fail("the title disturbed the band's STAT split: LYC %d STAT $%02X"
         % (pb.memory[0xFF45], pb.memory[0xFF41]))

# --- 2. The glyph run, located by pixels -------------------------------------
# TitleGlyphs holds only the characters the title's own lines use, in ASCII
# order; TitleGlyphsAscii names them. Re-encoding the source charset the same
# way and finding the one matching run in VRAM pins the base, the tile order
# and the shade at once, independently of gbdata.py's own encoder.
gfx, _, _, _, _, _ = gbdata.build(ASM)
m = re.search(r"TitleGlyphsAscii:\n    db ([^\n]+)", open(TITLE_ASM).read())
if not m:
    raise SystemExit("FAIL: %s has no TitleGlyphsAscii" % TITLE_ASM)
ascii_codes = [int(t, 16) for t in re.findall(r"\$([0-9A-Fa-f]{2})", m.group(1))]
want_tiles = [bytes(gbdata.to_gb_tile(gfx[c * 8:c * 8 + 8], HUD_SHADE))
              for c in ascii_codes]

glyph_count = asm_def("TITLE_GLYPH_COUNT", TITLE_ASM)
logo_count = asm_def("TITLE_LOGO_COUNT", TITLE_ASM)
if glyph_count != len(want_tiles):
    fail("title.asm says %d glyphs but TitleGlyphsAscii lists %d"
         % (glyph_count, len(want_tiles)))

vram = bytes(pb.memory[VRAM:VRAM + 256 * 16])
bases = [t for t in range(257 - len(want_tiles))
         if all(vram[(t + i) * 16:(t + i + 1) * 16] == want_tiles[i]
                for i in range(len(want_tiles)))]
if len(bases) != 1:
    raise SystemExit("FAIL: found %d runs of the title glyphs in VRAM (%s), "
                     "expected exactly one" % (len(bases), bases))
base = bases[0]
logo_base = base + glyph_count
print("title glyphs: %d tiles at $%02X (%s); logo run at $%02X, %d tiles"
      % (len(want_tiles), base, "".join(chr(c) for c in ascii_codes),
         logo_base, logo_count))

# The score run beside it, the same way. The title's SELECT hint and the whole
# instructions screen are drawn out of THIS run, so its base is pinned by pixels
# rather than assumed to follow the logo.
m = re.search(r"ScoreGlyphsAscii:\n    db ([^\n]+)", open(SCORE_ASM).read())
if not m:
    raise SystemExit("FAIL: %s has no ScoreGlyphsAscii" % SCORE_ASM)
score_codes = [int(t, 16) for t in re.findall(r"\$([0-9A-Fa-f]{2})", m.group(1))]
score_want = [bytes(gbdata.to_gb_tile(gfx[c * 8:c * 8 + 8], HUD_SHADE))
              for c in score_codes]
if asm_def("SCORE_GLYPH_COUNT", SCORE_ASM) != len(score_want):
    fail("score.asm says %d glyphs but ScoreGlyphsAscii lists %d"
         % (asm_def("SCORE_GLYPH_COUNT", SCORE_ASM), len(score_want)))
score_bases = [t for t in range(257 - len(score_want))
               if all(vram[(t + i) * 16:(t + i + 1) * 16] == score_want[i]
                      for i in range(len(score_want)))]
if len(score_bases) != 1:
    raise SystemExit("FAIL: found %d runs of the score glyphs in VRAM (%s), "
                     "expected exactly one" % (len(score_bases), score_bases))
score_base = score_bases[0]
print("score glyphs: %d tiles at $%02X (%s)"
      % (len(score_want), score_base, "".join(chr(c) for c in score_codes)))
# The chain main.asm declares -- SCORE_TILE_BASE = LOGO_TILE_BASE +
# TITLE_LOGO_COUNT -- checked against where the two runs actually landed, so a
# drifting base fails here rather than as a screen of wrong tiles.
if score_base != logo_base + logo_count:
    fail("the score run is at $%02X, not the logo run's end ($%02X): the VRAM "
         "base chain in main.asm has drifted" % (score_base, logo_base + logo_count))

# --- 3. The screen ------------------------------------------------------------
# Decoded through the base found above: a wrong column, a dropped row, a shifted
# base or a line drawn one tile late all land here. The expected lines are the
# source's strings, stated here rather than read from the generator, so a
# generator that emits the wrong text fails instead of agreeing with itself.
EXPECTED = [
    (1, "A & F SOFTWARE"),
    (3, "presents"),
    (12, "by  n.alderton"),          # both blanks, exactly as the source has
    (15, "PRESS START"),
    # Drawn from the SCORE run rather than the title's, so it costs the title's
    # glyph set nothing -- every capital is already in the run the table and the
    # instructions share, resident whatever screen is up. Row 17 and not 16:
    # PRESS START is on 15, and full-height capitals on ADJACENT rows touch.
    (17, "SELECT HELP"),
]
LOGO_ROWS = range(5, 11)             # the Z80's 14x6 block, less its flip
LOGO_COLS = range(3, 17)


def centered(text):
    """A line as it lands on the screen. The centring is the layout, so it is
    asserted rather than stripped -- a line drawn at the wrong column fails."""
    return " " * ((20 - len(text)) // 2) + text


def decode(t):
    i = t - base
    if t == 0:
        return " "
    if 0 <= i < len(ascii_codes):
        return chr(ascii_codes[i])
    j = t - score_base              # the row drawn from the score run
    if 0 <= j < len(score_codes):
        return chr(score_codes[j])
    return "?"                       # a logo tile: not a character


got = {}
for r in range(TITLE_ROWS):
    text = "".join(decode(map_byte(r, c)) for c in range(20)).rstrip()
    if text.strip():
        got[r] = text
print("title screen:")
for r in sorted(got):
    print("  row %2d |%-20s|" % (r, got[r]))

for r, text in EXPECTED:
    if got.get(r) != centered(text):
        fail("map row %d is %r, expected %r" % (r, got.get(r), centered(text)))

# Nothing else carries text: a line drawn on the wrong row shows up as an extra
# one, which is what catches a RowColAddr that read the column as the row.
extra = [r for r in got if r not in dict(EXPECTED) and r not in LOGO_ROWS]
if extra:
    fail("rows %s carry text the title has no line for" % extra)

# The logo, by shape: every cell of the 6x14 block is a tile out of the logo run
# (a blank cell included -- the block's own $00 is one of them) and every cell
# outside it is not. That pins the block's position without re-deriving its art,
# which is the mGBA eye test's job.
bad = []
for r in range(TITLE_ROWS):
    for c in range(20):
        t = map_byte(r, c)
        in_logo = r in LOGO_ROWS and c in LOGO_COLS
        if in_logo != (logo_base <= t < logo_base + logo_count):
            bad.append((r, c, t))
print("logo: %d x %d cells at row %d col %d: %s"
      % (len(LOGO_ROWS), len(LOGO_COLS), LOGO_ROWS[0], LOGO_COLS[0],
         "PASS" if not bad else "FAIL (%d cells)" % len(bad)))
if bad:
    r, c, t = bad[0]
    fail("map (%d,%d) is tile $%02X: the logo's %dx%d block is not where "
         "TitleLogoCells puts it" % (r, c, t, len(LOGO_COLS), len(LOGO_ROWS)))

title_map = bytes(pb.memory[SCREEN0:SCREEN0 + TITLE_ROWS * SCRN_COLS])

# --- 4. The tune --------------------------------------------------------------
# wMusicPtr is the whole of "playing", so the title has to have left it inside
# TitleMusic and the driver has to be walking it -- the walk verify_music.py
# does in full, here at boot rather than under a poked pointer.
ptr = word("wMusicPtr")
print("tune: wMusicPtr $%04X, TitleMusic $%04X..$%04X"
      % (ptr, sym["TitleMusic"], sym["TitleMusicEnd"]))
if not sym["TitleMusic"] <= ptr < sym["TitleMusicEnd"]:
    fail("wMusicPtr is $%04X, outside TitleMusic ($%04X..$%04X) -- the title is "
         "not playing its tune" % (ptr, sym["TitleMusic"], sym["TitleMusicEnd"]))
# The first note is duration 1, and the driver counts a note out over
# (10 // duration) * NOTE_UNIT frames -- so the wait has to outlast one whole
# note rather than a round number of frames. verify_music.py walks every note;
# all this wants is that it is moving.
for f in range(120):
    tick(1)
    after = word("wMusicPtr")
    if after != ptr:
        break
print("  next note on frame %d: $%04X" % (f + 1, after))
if after == ptr:
    fail("the title tune is not advancing: wMusicPtr stuck at $%04X" % ptr)
elif not sym["TitleMusic"] <= after < sym["TitleMusicEnd"]:
    fail("the tune left TitleMusic after one note, to $%04X" % after)

# --- 5. START ----------------------------------------------------------------
# The whole way out: the mode, the OBJ and WIN bits, the camera, and the level
# actually in the map rather than merely claimed in WRAM.
harness.press_start(pb)
lcdc, scy = pb.memory[0xFF40], pb.memory[0xFF42]
print("after START: wOnTitle %d LCDC $%02X OBJ %d SCY %d lives %d eggs %d "
      "score %d" % (reg("wOnTitle"), lcdc, lcdc >> 1 & 1, scy, reg("wLives"),
                    reg("wEggsRemaining"), score()))
if reg("wOnTitle"):
    fail("START did not leave the title")
# OBJ is off here, and that is the design rather than a fault: the status band
# covers scanlines 0..7, so the VBlank handler clears OBJ along with setting WIN
# -- nothing may draw over the row -- and the STAT handler at LY=8 puts OBJ back
# for the playfield. A tick leaves the frame at LY 0, which is inside the band,
# so the game's LCDC reads WIN on / OBJ off and the title's reads neither. WIN
# is therefore what says a game's LCDC is up; OBJ cannot, being off in both.
# (This used to pass on OBJ, back when the VBlank handler overran the window:
# the tail's write landed past LY 0, so the sample caught the previous frame's
# state. On hardware those writes are in mode 3 and simply dropped.)
if not lcdc & 0x20:
    fail("the LCDC a game runs has no band, so START did not put one up")
if scy == 0:
    fail("SCY is still 0 after START, so the camera never went back on")
if reg("wLives") != LIVES_START:
    fail("the game START began has %d lives, expected %d"
         % (reg("wLives"), LIVES_START))
if reg("wEggsRemaining") != EGGS_PER_LEVEL:
    fail("the game START began has %d eggs, expected %d"
         % (reg("wEggsRemaining"), EGGS_PER_LEVEL))
if score():
    fail("the game START began has a score of %d, expected 0" % score())

# buffer row 0 lands on map row 21 (DrawLevel draws it bottom-up, above the
# status band), so that pair is the cheap proof the level reached the map.
buf_first = bytes(pb.memory[sym["wLevelBuffer"]:
                            sym["wLevelBuffer"] + SCRN_COLS])
map_row = bytes(pb.memory[SCREEN0 + MAP_ROW0 * SCRN_COLS:
                          SCREEN0 + MAP_ROW0 * SCRN_COLS + SCRN_COLS])
print("map row %d vs the buffer's first row: %s"
      % (MAP_ROW0, "PASS" if buf_first == map_row else "FAIL"))
if buf_first != map_row:
    fail("the map's level row is not the buffer's -- no level was loaded: "
         "%s vs %s" % (list(map_row[:8]), list(buf_first[:8])))
if not any(map_row):
    fail("map row %d is all blank, so the level was cleared rather than drawn"
         % MAP_ROW0)

def game_over_to_table(where):
    """Force the last life out of the running game and wait for the table.
    Returns the frames it took. The banked score is zeroed first, so the score
    does not qualify and no name entry opens on the way -- typing a name is
    verify_scores.py's job, and a START during one only ends it."""
    setreg("wScoreSaved", 0)
    pb.memory[sym["wScoreSaved"]:sym["wScoreSaved"] + 5] = [0] * 5
    setreg("wLives", 1)
    setreg("wPlayerDead", 1)
    setreg("wDeathTimer", 1)
    for f in range(300):
        tick(1)
        if reg("wOnScores"):
            return f + 1
    fail("the last life never reached the high-score table (%s)" % where)
    return 300


# --- 6. Game over comes back here --------------------------------------------
# The last life routes through the high-score table to the title (LoseLife ->
# CheckPlayersHighScores -> FrontEnd in the Z80), so the way back is two STARTs:
# one to leave the table, one to leave the title.
frames = game_over_to_table("§6")
f = frames - 1

lcdc, scy, scx = pb.memory[0xFF40], pb.memory[0xFF42], pb.memory[0xFF43]
print("after the last life (%d frames): wOnScores %d wOnTitle %d LCDC $%02X "
      "OBJ %d WIN %d SCY %d SCX %d" % (f + 1, reg("wOnScores"), reg("wOnTitle"),
                                       lcdc, lcdc >> 1 & 1, lcdc >> 5 & 1, scy, scx))
if not reg("wOnScores"):
    fail("game over left the player in a level instead of showing the table")
if reg("wOnTitle"):
    fail("wOnTitle is still set with the table up, so the front end is confused")
if lcdc & 0x02:
    fail("the table after a game over still draws OBJ")
if lcdc & 0x20:
    fail("the table after a game over still draws the window band")
if (scy, scx) != (0, 0):
    fail("the table after a game over is scrolled: SCY %d SCX %d" % (scy, scx))
if reg("wPlayerDead"):
    fail("wPlayerDead is still set under the table, so the death never ended")

# The table is not the title: its screen is its own, drawn from the table the
# ROM seeded, so the boot title's map must NOT be what is up here.
scores_map = bytes(pb.memory[SCREEN0:SCREEN0 + TITLE_ROWS * SCRN_COLS])
if scores_map == title_map:
    fail("the high-score screen is showing the title's map")

harness.press_start(pb)
print("after START on the table: wOnScores %d wOnTitle %d"
      % (reg("wOnScores"), reg("wOnTitle")))
if not reg("wOnTitle") or reg("wOnScores"):
    fail("START on the table did not reach the title")

lcdc, scy, scx = pb.memory[0xFF40], pb.memory[0xFF42], pb.memory[0xFF43]
print("the title after it: LCDC $%02X OBJ %d WIN %d SCY %d SCX %d"
      % (lcdc, lcdc >> 1 & 1, lcdc >> 5 & 1, scy, scx))
if lcdc & 0x02:
    fail("the title after a game over still draws OBJ")
if lcdc & 0x20:
    fail("the title after a game over still draws the window band")
if (scy, scx) != (0, 0):
    fail("the title after a game over is scrolled: SCY %d SCX %d" % (scy, scx))

now = bytes(pb.memory[SCREEN0:SCREEN0 + TITLE_ROWS * SCRN_COLS])
if now != title_map:
    diff = [i for i in range(len(title_map)) if now[i] != title_map[i]]
    fail("the title after a game over is not the one the ROM booted with: %d "
         "cells differ, first at row %d col %d"
         % (len(diff), diff[0] // SCRN_COLS, diff[0] % SCRN_COLS))

harness.press_start(pb)
print("after START: wOnTitle %d lives %d eggs %d score %d"
      % (reg("wOnTitle"), reg("wLives"), reg("wEggsRemaining"), score()))
if reg("wOnTitle"):
    fail("START after a game over did not leave the title")
if reg("wLives") != LIVES_START or reg("wEggsRemaining") != EGGS_PER_LEVEL \
        or score():
    fail("the game START began after a game over is not fresh: lives %d eggs "
         "%d score %d" % (reg("wLives"), reg("wEggsRemaining"), score()))

# --- 7. The instructions ------------------------------------------------------
# The Z80 reaches one from `I` at the front end (TestKeys, Chuckie.asm:4113);
# SELECT here, because a DMG has no I key. A screen OFF the title -- the tune
# keeps running under it, and leaving is the same EnterTitle a game over takes.
game_over_to_table("§7")
harness.press_start(pb)
if not reg("wOnTitle") or reg("wOnScores"):
    fail("the table did not lead back to the title for the instructions test")

harness.tap(pb, "select")
lcdc, scy, scx = pb.memory[0xFF40], pb.memory[0xFF42], pb.memory[0xFF43]
print("after SELECT: wOnInstr %d wOnTitle %d wOnScores %d LCDC $%02X OBJ %d "
      "WIN %d SCY %d SCX %d" % (reg("wOnInstr"), reg("wOnTitle"),
                                reg("wOnScores"), lcdc, lcdc >> 1 & 1,
                                lcdc >> 5 & 1, scy, scx))
if not reg("wOnInstr"):
    fail("SELECT on the title did not open the instructions")
if reg("wOnTitle") or reg("wOnScores"):
    fail("the front-end flags are not exclusive with the instructions up: "
         "wOnTitle %d wOnScores %d" % (reg("wOnTitle"), reg("wOnScores")))
if not lcdc & 0x80:
    fail("the LCD is off on the instructions")
if lcdc & 0x02:
    fail("the instructions draw OBJ, and nothing on them is a sprite")
if lcdc & 0x20:
    fail("the instructions draw the window band, which belongs to a game")
if (scy, scx) != (0, 0):
    fail("the instructions are scrolled: SCY %d SCX %d, expected 0/0"
         % (scy, scx))

# Every cell, through the score run: the text the generator emits is stated here
# independently, so a generator that emits the wrong words fails instead of
# agreeing with itself. Cell by cell rather than by decoded line, because the
# control block's internal blanks are real cells -- a line drawn short would
# otherwise read as a line with blanks in it.
INSTR = [
    (1,  "INSTRUCTIONS"),
    (3,  "COLLECT THE EGGS"),
    (5,  "FROM THE HEN-HOUSE"),
    (7,  "AVOID THE HENS"),
    (9,  "PAD     MOVE"),
    (11, "A       JUMP"),
    (13, "START   PLAY"),
    (15, "SELECT  BACK"),
]
want = {}
for row, text in INSTR:
    for j, ch in enumerate(text):
        want[row, (20 - len(text)) // 2 + j] = \
            score_base + score_codes.index(ord(ch))
bad = [(r, c, map_byte(r, c), want.get((r, c), 0))
       for r in range(TITLE_ROWS) for c in range(20)
       if map_byte(r, c) != want.get((r, c), 0)]
print("instructions: %d cells, %d lines: %s"
      % (TITLE_ROWS * 20, len(INSTR),
         "PASS" if not bad else "FAIL (%d cells)" % len(bad)))
for r in sorted({row for row, _ in INSTR}):
    print("  row %2d |%s|" % (r, "".join(decode(map_byte(r, c))
                                         for c in range(20)).rstrip()))
if bad:
    r, c, t, w = bad[0]
    fail("the instructions map (%d,%d) is tile $%02X, expected $%02X -- the "
         "screen drawn is not the one stated here" % (r, c, t, w))

# SELECT closes them, back to the title -- and to the *same* map, so the exit
# redraws the title rather than leaving the instructions up under the tune.
harness.tap(pb, "select")
print("after SELECT again: wOnInstr %d wOnTitle %d wOnScores %d"
      % (reg("wOnInstr"), reg("wOnTitle"), reg("wOnScores")))
if reg("wOnInstr") or not reg("wOnTitle"):
    fail("SELECT on the instructions did not close them: wOnInstr %d "
         "wOnTitle %d" % (reg("wOnInstr"), reg("wOnTitle")))
now = bytes(pb.memory[SCREEN0:SCREEN0 + TITLE_ROWS * SCRN_COLS])
if now != title_map:
    diff = [i for i in range(len(title_map)) if now[i] != title_map[i]]
    fail("the title the instructions closed to is not the boot title: %d cells "
         "differ, first at row %d col %d"
         % (len(diff), diff[0] // SCRN_COLS, diff[0] % SCRN_COLS))

# START from the instructions begins the game, as the Z80's `S` does
# (Chuckie.asm:4177). StartGame has to leave both front-end flags clear, or the
# branch in MainLoop keeps firing and the level is drawn but never ticked -- so
# the clock is poked and the tick has to walk it.
harness.tap(pb, "select")
harness.press_start(pb)
lcdc = pb.memory[0xFF40]
print("after SELECT then START: wOnInstr %d wOnTitle %d OBJ %d lives %d eggs "
      "%d score %d" % (reg("wOnInstr"), reg("wOnTitle"), lcdc >> 1 & 1,
                       reg("wLives"), reg("wEggsRemaining"), score()))
if reg("wOnInstr") or reg("wOnTitle"):
    fail("START on the instructions did not leave the front end: wOnInstr %d "
         "wOnTitle %d" % (reg("wOnInstr"), reg("wOnTitle")))
if not lcdc & 0x20:                        # the band's WIN; see §5 on OBJ
    fail("the game START began on the instructions has no band up")
if reg("wLives") != LIVES_START or reg("wEggsRemaining") != EGGS_PER_LEVEL \
        or score():
    fail("the game START began on the instructions is not fresh: lives %d "
         "eggs %d score %d" % (reg("wLives"), reg("wEggsRemaining"), score()))
setreg("wTimeUp", 0)
pb.memory[sym["wTime"] + 2] = 5
tick(12)
if pb.memory[sym["wTime"] + 2] == 5:
    fail("the clock did not move 12 frames into the game, so MainLoop is still "
         "short-circuiting on a front-end flag and the level never ticks")
print("the clock 12 frames in: %d (poked 5)"
      % pb.memory[sym["wTime"] + 2])

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
