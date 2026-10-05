#!/usr/bin/env python3
"""Extract Chuckie Egg level data + tile graphics from the Z80 disassembly.

Parse the reference source by ADDRESS rather than by label: the graphics are
one contiguous run from $84F0, but the source labels it in pieces
(gfx_CharacterSet, gfx_CharacterSetNumbers, ...). Address-based extraction
can't drift when labels move, and it lets us assert we got every byte.

Verified against mrcook's address table (chuckie-egg.ctl):
    tile id n -> graphic at $84F0 + n*8
      id 0 blank   $84F0      id 3 egg       $8508
      id 1 ladderL $84F8      id 4 corn      $8510
      id 2 ladderR $8500      id 5 platform  $8518
      id $a8..$b5 birdcage    $8A30..$8A9F

So the GB tile index can equal the Spectrum tile id -- no mapping table.

    python3 tools/gbdata.py --write src/
"""
import re
import sys

GFX_BASE = 0x84F0
GFX_LEN = 182 * 8          # ids 0 .. $b5 inclusive
LEVEL_COUNT = 8
LEVEL_SIZE = 32 * 21       # 672

# Note: the levels are located by label, not by address. `org $b200` is followed
# by `ds 256, $9c` and then code, so the org address is NOT the level base.

# Which shade each tile's ink gets on the GB. Deliberately a demake: the
# Spectrum has 15 colours and a per-cell attribute; the GB has 4 shades and one
# BG palette. Bitmaps are 1bpp with black paper, so index 0 = background (black)
# and 1/2/3 = ink, ordered dark -> light. This table is the one knob to turn
# when tuning how readable the level looks; see PLAN.md Phase 2.
SHADE = {0: 0, 1: 2, 2: 2, 3: 3, 4: 3, 5: 2}
SHADE_CAGE = 1
SHADE_OTHER = 2
# Harry gets the lightest ink the 4-shade palette has, so he stands out against
# the greys of the level (platforms and ladders are shade 2, the cage shade 1).
SPRITE_SHADE = 3

# The only tile ids the level data is allowed to reference. Asserted below, so
# a level using something unexpected fails loudly instead of rendering noise.
ALLOWED = set(range(0, 6)) | set(range(0xA8, 0xB6))


def parse_num(tok):
    tok = tok.strip()
    if tok.startswith("$"):
        return int(tok[1:], 16)
    if tok.lower().startswith("0x"):
        return int(tok, 16)
    if tok.startswith("%"):
        return int(tok[1:], 2)
    return int(tok, 0)


def parse_asm(path):
    """Return (mem, labels): byte values by address, and label addresses.

    Tracks the current address from `org` and advances it only for data
    directives, so instructions are skipped without desyncing the address.
    """
    mem, labels, addr = {}, {}, 0
    for lineno, raw in enumerate(open(path), 1):
        line = raw.split(";")[0].rstrip()
        if not line.strip():
            continue

        m = re.match(r"\s*org\s+(\S+)", line, re.I)
        if m:
            addr = parse_num(m.group(1))
            continue

        m = re.match(r"^([A-Za-z_.][A-Za-z0-9_.]*):", line)
        if m:
            labels[m.group(1)] = addr
            line = line[m.end():]
            if not line.strip():
                continue

        m = re.match(r"\s*(db|dw|ds)\s+(.*)", line, re.I)
        if not m:
            continue
        op, rest = m.group(1).lower(), m.group(2)
        try:
            if op == "db":
                for tok in rest.split(","):
                    if tok.strip():
                        mem[addr] = parse_num(tok) & 0xFF
                        addr += 1
            elif op == "dw":
                for tok in rest.split(","):
                    v = parse_num(tok)
                    mem[addr], mem[addr + 1] = v & 0xFF, (v >> 8) & 0xFF
                    addr += 2
            elif op == "ds":
                parts = rest.split(",")
                n = parse_num(parts[0])
                v = parse_num(parts[1]) & 0xFF if len(parts) > 1 else 0
                for i in range(n):
                    mem[addr + i] = v
                addr += n
        except ValueError:
            continue  # expression we can't evaluate; the gap check will catch it
    return mem, labels


def db_values(rest):
    """The bytes a `db` operand list produces, with "strings" expanded one
    character per byte. parse_asm does not need this -- the blocks it reads are
    all numbers -- but TitleText is written as text and has to be read back the
    way the assembler reads it. (A comma inside a quoted string would split
    wrongly; none of the source's strings has one.)"""
    out = []
    for tok in re.findall(r'"[^"]*"|[^,]+', rest):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith('"'):
            out += [ord(c) for c in tok[1:-1]]
        else:
            out.append(parse_num(tok) & 0xFF)
    return out


def db_after_label(path, label, count):
    """Read `count` db bytes following `label:` in FILE order.

    The address tracker can't be used here: the hen-start and lift tables sit
    after a block of code, and `parse_asm` only advances its address on data
    directives, so it never reaches them. Reading in file order sidesteps that
    entirely, and `count` is asserted rather than trusted.
    """
    lines = open(path).read().split("\n")
    i = next(i for i, l in enumerate(lines) if re.match(r"^%s:" % label, l)) + 1
    vals = []
    while i < len(lines) and len(vals) < count:
        line = lines[i].split(";")[0].strip()
        i += 1
        if not line:
            continue
        if re.match(r"^[A-Za-z_.][A-Za-z0-9_.]*:", line):
            break   # end of the block; the length check below judges the total
        m = re.match(r"^db\s+(.*)", line, re.I)
        if not m:
            raise SystemExit("%s: hit non-db %r after %d/%d bytes"
                             % (label, line[:40], len(vals), count))
        vals += db_values(m.group(1))
    if len(vals) > count:
        raise SystemExit("%s: got %d bytes, expected at most %d"
                         % (label, len(vals), count))
    if len(vals) < count:
        # The source's last record can be a byte short: level 8's HenStarts
        # entry is 20 bytes where the others are 21, so its 21st byte would be
        # the first opcode of ResetTileColours. Harmless -- the runtime copies
        # only `count` bytes -- so pad, but refuse anything more than one
        # record short, which would mean the parse drifted.
        if count - len(vals) >= count // 8:
            raise SystemExit("%s: got %d of %d bytes -- too short to be padding"
                             % (label, len(vals), count))
        vals += [0] * (count - len(vals))
    return vals


def extract(mem, base, length, what):
    missing = [a for a in range(base, base + length) if a not in mem]
    if missing:
        raise SystemExit(
            "extract %s: %d/%d bytes unmapped at $%04X (first gap $%04X) -- "
            "the parser desynced, fix it before trusting any output"
            % (what, len(missing), length, base, missing[0])
        )
    return bytes(mem[a] for a in range(base, base + length))


def to_gb_tile(spectrum_8, shade):
    """1bpp Spectrum tile -> 2bpp GB tile.

    GB colour index is (high << 1) | low, so:
        shade 1 -> low=bmp, high=0     shade 2 -> low=0, high=bmp
        shade 3 -> low=bmp, high=bmp   shade 0 -> blank (background)
    """
    if shade == 0:
        return bytes(16)
    out = bytearray()
    for row in spectrum_8:
        if shade == 1:
            out += bytes((row, 0x00))
        elif shade == 2:
            out += bytes((0x00, row))
        else:
            out += bytes((row, row))
    return bytes(out)


def to_gb_inverted(spectrum_8):
    """1bpp Spectrum tile -> 2bpp GB tile with ink and paper swapped.

    Shade 3 is (row, row): ink at colour index 3. Both planes complemented puts
    the paper at 3 and the ink at 0, i.e. white paper with black letters. The
    all-blank tile inverts to solid white, which is the name field's cursor.
    """
    out = bytearray()
    for row in spectrum_8:
        out += bytes((~row & 0xFF, ~row & 0xFF))
    return bytes(out)


def shade_for(tile_id):
    if tile_id in SHADE:
        return SHADE[tile_id]
    if 0xA8 <= tile_id <= 0xB5:
        return SHADE_CAGE
    return SHADE_OTHER


# --- Harry's sprites -------------------------------------------------------
# One table at gfx_PlayerRight, indexed gfx_PlayerRight + n*32, 32 bytes each:
# 16 rows x 2 bytes, so 16x16 pixels, 1bpp, byte 0 = left half, byte 1 = right.
SPRITE_LABEL = "gfx_PlayerRight"
SPRITE_BYTES = 32
# Frames 0-3 walk right, 4-7 walk left, 8-11 the mother duck, 12 blank,
# 13-16 climb (13/15 and 14/16 are the two alternating poses), 17+ hens.
HARRY_FRAMES = [0, 1, 2, 3, 4, 5, 6, 7, 13, 14, 15, 16]

# The mother duck's poses, out of the same table. The Z80 picks the facing at
# draw time -- `LD C,$08` / `LD C,$0A` (Chuckie.asm:3475) -- and adds
# MotherDuckFrame, which toggles 0/1 every update. So 8/9 are its two right-
# facing poses (wings down, wings up) and 10/11 the same two mirrored; 10/11
# are the pixel-exact mirror of 8/9, asserted in duck_frames. The port emits
# only 8 and 9 -- the right-facing pair -- and draws the left facing with OAM's
# X-flip and the columns swapped, which that assert is what makes safe. All four
# are still read, so the mirror keeps being proved rather than assumed.
DUCK_FRAMES = [8, 9]                 # the emitted frames, both right-facing
DUCK_SOURCE_FRAMES = [8, 9, 10, 11]  # every pose: 10/11 are the mirror proof

# --- HUD font --------------------------------------------------------------
# gfx_CharacterSet is indexed by ASCII code DIRECTLY: the glyph for character c
# is the 8 bytes at GFX_BASE + c*8. Confirmed three ways rather than assumed --
#   * PrintCharacter (Chuckie.asm:2636) computes BC = code*8 and adds it to
#     gfx_CharacterSet, so the index is the ASCII code, not a charset ordinal;
#   * the score path reads gfx_CharacterSetNumbers at code 48, and that label
#     sits at exactly GFX_BASE + 48*8 -- i.e. it IS codes 48-57;
#   * rendering 48-57 and 66/69/76/83/84 comes out as 0-9 and B L S T.
# (An earlier pass assumed `ord(ch) - $20` and rendered nonsense. It is not.)
HUD_CHARS = "0123456789BESTL"
HUD_SHADE = 3               # white ink on the black paper index 0 already gives


def asm_font(gfx):
    """The status row's glyphs, one tile per character, in HUD_CHARS order."""
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; The status row's font. Tile n here is the character HUD_CHARS[n],",
           "; addressed from main.asm as HUD_TILE_BASE + HUD_CH_<c>.",
           "; Straight ASCII into gfx_CharacterSet -- see gbdata.py for the",
           "; three confirmations, so the indexing is not re-litigated here.",
           'SECTION "Font", ROM0', "", "FontTiles:"]
    for ch in HUD_CHARS:
        t = to_gb_tile(gfx[ord(ch) * 8:ord(ch) * 8 + 8], HUD_SHADE)
        assert any(t), "glyph %r came out blank -- the ASCII index is wrong" % ch
        rows = ["$%02X,$%02X" % (t[i], t[i + 1]) for i in range(0, 16, 2)]
        out.append("    ; %r (ASCII $%02X)" % (ch, ord(ch)))
        out.append("    db " + ",".join(rows))
    out += ["FontTilesEnd:", ""]
    for n, ch in enumerate(HUD_CHARS):
        out.append("DEF HUD_CH_%s EQU %d" % (ch, n))
    out += ["DEF HUD_TILE_COUNT EQU %d" % len(HUD_CHARS),
            "DEF HUD_ROW_LEN    EQU 20",
            ""]
    return "\n".join(out)


# --- the title screen ------------------------------------------------------
# FrontEnd (Chuckie.asm:4011) walks TitleText as a fixed grid -- `CP $0E` is 14
# columns and the row counter runs H=2..$17, so 22 rows at Spectrum rows 2..23,
# 22*14 = 308 cells, which is exactly what the data holds.
#
# The logo is the 14x6 block in the middle of it, in the ROM's own tiles
# $7F-$8A -- codes that are not characters. `PrintHighScoreTable` fills the
# columns to the RIGHT of the art on the Spectrum's 32-column screen, so on
# ours it becomes its own screen (6c-3) and only the art is drawn here.
TITLE_TEXT_LABEL = "TitleText"
TITLE_COLS = 14
TITLE_LOGO_ROW0, TITLE_LOGO_ROW1 = 11, 16    # inclusive, in TitleText rows
LOGO_ROW, LOGO_COL = 5, 3                    # where it lands on the GB screen

# TitleText is stored BOTTOM-UP: `FrontEnd` draws it with H running 2..23 and
# `PrintCharacter` picks the screen third from H, so H counts up from the bottom
# and TitleText row r lands on Spectrum screen row 21 - r. Row 0 is the blank
# bottom line, row 21 -- the last -- is "A & F SOFTWARE" at the top.
#
# What the title says, top to bottom, and the drop. The Z80's fourth line, "1 to
# 4 players of skill for a game", is dropped: it advertises a four-player game
# this port does not have, and the room is what lets the rest breathe on an
# 18-row screen. It sat between the logo and the byline, so removing it just
# closes the gap. The last line is ours: the Z80 scrolls its prompt in from the
# right, and this one is static.
#
# The byline keeps BOTH blanks the source has between "by" and "n.alderton"
# (TitleText row 2 is literally `db $00,"n.alderton"` after `by`) -- it is the
# original's own spacing, and stripping it would be an edit, not a port.
TITLE_LINES = [
    (1,  "A & F SOFTWARE"),     # TitleText row 21, the Spectrum's screen row 0
    (3,  "presents"),           # TitleText row 19, screen row 2
    (12, "by  n.alderton"),     # TitleText row 2,  screen row 19
    (15, "PRESS START"),        # our own
]


def title_logo(asm_path):
    """The 14x6 logo block out of TitleText, one row of Spectrum tile codes.

    Returned in SCREEN order, top row first -- the block is reversed on the way
    out, because TitleText is stored bottom-up (see TITLE_LINES). Without that
    flip the wordmark renders upside down; it is not a guess, it is what the
    extracted bytes do.

    Read in FILE order, like the hen-start and lift tables: TitleText sits after
    a block of code, so parse_asm's address tracker never reaches it -- the
    `mem` it returns is zero there. (That is the trap `db_after_label` was
    written for; the address-based read of this block came back all zeros.)
    """
    cells = db_after_label(asm_path, TITLE_TEXT_LABEL, 22 * TITLE_COLS)
    rows = [cells[r * TITLE_COLS:(r + 1) * TITLE_COLS]
            for r in range(TITLE_LOGO_ROW0, TITLE_LOGO_ROW1 + 1)]
    return rows[::-1]


def asm_title(gfx, logo):
    """The title screen's tiles and its layout.

    Only the glyphs the title's own strings use are emitted, in ASCII order,
    and the lines are emitted PRE-ENCODED -- as 1-based indices into that run,
    relative so the emitter never has to know where main.asm puts the tiles.
    So the ROM never sees an ASCII code and DrawText is a copy loop.

    Returns (text, glyphs, logotiles) so main() can count them in the budget.
    """
    chars = sorted({c for _, line in TITLE_LINES for c in line})
    glyphs = {}
    for ch in chars:
        t = to_gb_tile(gfx[ord(ch) * 8:ord(ch) * 8 + 8], HUD_SHADE)
        if ch != " ":
            assert any(t), "glyph %r came out blank -- the ASCII index is wrong" % ch
        glyphs[ch] = t
    index = {ch: n + 1 for n, ch in enumerate(chars)}      # 0 ends a line

    codes = sorted({c for row in logo for c in row})
    logoid = {c: n + 1 for n, c in enumerate(codes)}       # 0 is a blank cell

    out = ["; Generated by tools/gbdata.py -- do not edit.",
           ";",
           "; The title screen. The glyph run holds only the characters the",
           "; title's own lines use, in ASCII order, so it costs the fewest",
           "; tiles; TitleLines carries those lines already encoded as 1-based",
           "; indices into it, plus where each one goes. The tiles' base",
           "; addresses are main.asm's business, not this file's.",
           ";",
           "; The logo is the Z80's own $7F-$8A block out of TitleText, rows",
           "; reversed: TitleText is stored bottom-up, so the block reads",
           "; upside down unless it is flipped.",
           ";",
           "; Divergence: the Z80 guards TitleMusic with MusicFlag so it plays",
           "; once a session. Here it is started every time the title is",
           "; entered, which is after every game over -- the point of a title",
           "; tune.",
           'SECTION "Title", ROM0', "", "TitleGlyphs:"]
    for ch in chars:
        t = glyphs[ch]
        out.append("    ; %r (ASCII $%02X)" % (ch, ord(ch)))
        out.append("    db " + ",".join("$%02X,$%02X" % (t[i], t[i + 1])
                                        for i in range(0, 16, 2)))
    out += ["TitleGlyphsEnd:", "", "TitleGlyphsAscii:",
            "    db " + ",".join("$%02X" % ord(ch) for ch in chars), ""]

    out.append("TitleLogoTiles:")
    for c in codes:
        t = to_gb_tile(gfx[c * 8:c * 8 + 8], HUD_SHADE)
        out.append("    ; TitleText tile $%02X" % c)
        out.append("    db " + ",".join("$%02X,$%02X" % (t[i], t[i + 1])
                                        for i in range(0, 16, 2)))
    out += ["TitleLogoEnd:", "",
            "; row, col, then the line as glyph indices, 0-terminated.",
            "TitleLines:"]
    for row, line in TITLE_LINES:
        col = (20 - len(line)) // 2
        out.append("    db %d,%d        ; %r" % (row, col, line))
        out.append("    db " + ",".join("$%02X" % index[c] for c in line) + ",0")
    out.append("    db $FF")

    # 1-based like the lines, and the block's blank tile is one of the twelve,
    # so every cell is a tile index and none of them needs a special case.
    out += ["", "; The logo as a %d x %d grid of the same 1-based indices."
            % (TITLE_COLS, len(logo)), "TitleLogoCells:"]
    for row in logo:
        out.append("    db " + ",".join("$%02X" % logoid[c] for c in row))

    out += ["",
            "DEF TITLE_GLYPH_COUNT EQU %d" % len(chars),
            "DEF TITLE_LOGO_COUNT  EQU %d" % len(codes),
            "DEF TITLE_LOGO_W      EQU %d" % TITLE_COLS,
            "DEF TITLE_LOGO_H      EQU %d" % len(logo),
            "DEF TITLE_LOGO_ROW    EQU %d" % LOGO_ROW,
            "DEF TITLE_LOGO_COL    EQU %d" % LOGO_COL,
            ""]
    return "\n".join(out), len(chars), len(codes)


# --- The high-score screen (6c-3) ------------------------------------------
# The Z80's table is 10 entries x 16 bytes: a 10-byte name field of raw tile
# codes and SIX ASCII digits. The ASCII is load-bearing there -- CompareScore
# (Chuckie.asm:5104) walks the field byte by byte, MSB first, which is a
# numeric compare only because it is fixed-width zero-padded ASCII, and
# CheckPlayersHighScores converts the live score with `ADD A,$30` before it.
# This port's scores are already one decimal digit per byte with the same
# layout as wScore, so the compare needs no conversion at all (OfferScore).
#
# The entry is 15 bytes, not 16. The Z80's sixth digit is a permanent pad:
# AddToScore (Chuckie.asm:3900) bumps +4 and carries only toward +0, so the
# data block's "001000" is internally 100 with a stray 0 printed after it. The
# status row here shows the five real digits, so the table does too.
SCORE_HEADING = "high score table"
# The d-pad is named first because it is the control nothing else implies: the
# panel is an alphabet grid and the cursor in it has to be moved to be any use,
# while A/B/START each say what they do. Both lines are centred, 17 and 16 of
# the 20 columns.
SCORE_LEGEND = ["PAD move  A type", "B rub  START done"]
# 28 cells, not 27, so the grid is a full 14x2: A-Z and the blank cell that
# rubs a character out, with a spare blank either side to square it. The blank
# MUST stay at index 0 -- the inverted cell 0 is the name field's own cursor
# (DrawEditingRow), and nothing searches for it.
SCORE_ALPHABET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ "
SCORE_GRID_COLS = 14
SCORE_HEADING_ROW = 0
# EIGHT entries, not the Z80's ten. This screen has 18 map rows where the
# Spectrum has 24, and it is the only one of the port's screens that has to
# hold two things at once: the table, and the alphabet panel a name is typed
# on. Every line on it needs a blank row under it -- a capital fills its whole
# 8x8 cell, so two lines on ADJACENT rows touch and read as one garbled line
# (see SCORE_INSTR). Ten entries plus the panel does not fit that way; ten
# entries at the Z80's own pitch, two rows an entry (Chuckie.asm:5517), would
# need 20. Two entries buy the three blank rows the panel is short by.
SCORE_COUNT = 8
SCORE_ENTRY_ROW0 = 2                             # entry 1; the eight run 2..9
SCORE_GRID_ROW = 11                              # the 14x2 panel's first row
# Two map rows between the panel's own LINES, for the same reason the blank
# rows above exist: a capital fills its whole 8x8 cell, so the two alphabet rows
# drawn consecutively touch, and so do the two legend lines. Every line this
# panel draws steps by this -- the grid rows in DrawGrid and GridRowAddr, the
# legend rows below.
SCORE_PANEL_STEP = 2
SCORE_LEGEND_ROW0 = 15
SCORE_NAME_LEN = 10
SCORE_SCORE_LEN = 5
# The Z80's own default name: ' ', tiles $8F-$96, ' '. Rendered they read
# "A&F CHUCKIE EGG" -- the 8-tile banner the whole table starts as.
SCORE_BANNER = list(range(0x8F, 0x97))
SCORE_DEFAULT_SCORE = [0, 0, 1, 0, 0]            # 100, as the data block has it

# --- the announcements (Phase 7) -------------------------------------------
# The Z80's ScrollTextLine (Chuckie.asm:5051) at its three call sites: the
# level's number as one closes (:4464, in NextPlayerPlayLevel), "game over "
# when the last life goes (:4559), and "OUT OF TIME !" on a death after the
# clock had already run out (:4518). It blanks the screen and sweeps the word
# across it a pixel at a time; the port blanks the same screen and holds the
# word still, since a pixel scroll of the BG is a camera move here and not a
# print.
#
# The glyphs come from the score run, which is resident through a game anyway.
# The art is capitals for either case (the source charset's lowercase is drawn
# as caps), so the words are stored exactly as they read.
SCORE_NOTICE_LEVEL = "LEVEL "                    # then the level's digit
SCORE_NOTICE_OVER = "GAME OVER"
SCORE_NOTICE_TIME = "OUT OF TIME !"
SCORE_NOTICE_ROW = 8                             # the middle of 18
SCORE_NOTICE_MARK = 0xFF                         # "the level's digit goes here"
# ...and the cell before it, for its tens: BLANK below level ten, the way the
# Z80's own text carries the pair (`LevelDig1`/`LevelDig2`, Chuckie.asm:5633).
SCORE_NOTICE_TENS = 0xFE

# --- the instructions screen --------------------------------------------------
# The Z80 reaches one from `I` at the front end (TestKeys, :4113) and it is a
# picture of the SPECTRUM's own key tables: "keys are user defineable", why the
# three key types are preset, and a UDG diagram of the cursor keys against the
# 1/2/3/4 and 9/0/z/m columns. None of that survives -- a DMG has a pad and two
# buttons and no redefinition -- so the screen is re-authored rather than ported.
# What does survive is its purpose and one of its sentences: the objective, "to
# collect eggs from the hen-house", is the original's own wording out of
# InstructionTextKeys, hyphen and all, and redefinition is simply absent rather
# than advertised.
#
# CAPITALS, and for a budget reason rather than a taste one: this run's lowercase
# is only the letters the score screen's own strings use, so "jump", "back" and
# "from" would each cost a tile out of a VRAM that is three from full -- while
# A-Z is all there already. The announcements are capitals for the same reason.
#
# (row, text), every line centred as the table's are. The four control lines are
# one block: the key field is padded to eight columns so the actions line up, and
# at twelve columns each the block centres as a unit instead of raggedly.
#
# One blank row between every pair, heading included: a capital fills its whole
# 8x8 cell, so lines on ADJACENT rows touch and two of them read as one garbled
# line. Rows 1,3,5,7 then 9,11,13,15 leaves the bottom two clear.
SCORE_INSTR = [
    (1,  "INSTRUCTIONS"),
    (3,  "COLLECT THE EGGS"),
    (5,  "FROM THE HEN-HOUSE"),
    (7,  "AVOID THE HENS"),
    (9,  "PAD     MOVE"),
    (11, "A       JUMP"),
    (13, "START   PLAY"),
    (15, "SELECT  BACK"),
]
SCORE_INSTR_END = 0xFF                           # ends the record list
# The title's own hint, and the one line on that screen drawn from THIS run
# rather than the title's: saying SELECT there would grow the title's glyph set
# by three tiles (C, H and L -- it has only the letters its own lines use), and
# every capital is already here, resident in VRAM whatever screen is up.
#
# Row 17 and not 16: 'PRESS START' is on row 15, and two lines of full-height
# capitals on ADJACENT rows touch, so the pair reads as one garbled line. Every
# other pair on the screen has a blank row between them.
SCORE_TITLE_HELP = (17, "SELECT HELP")


def asm_score(gfx):
    """The high-score screen's tiles and its layout.

    One contiguous run, so Start copies the lot with a single MemCopy:

        0 .. 53    the glyphs the screen's strings and scores use, in ASCII
                   order -- so a digit d is index SCORE_DIGIT_FIRST+d and a
                   letter L is the index of chr(L). That is what makes a name a
                   plain index: the ROM stores glyph indices, never ASCII, and
                   nothing converts. Space is index 0, which is what lets a
                   blank name byte draw a blank cell.
        54 .. 80   the alphabet INVERTED, in grid order (space first): the
                   grid's cursor cell. The inverted space is a solid block,
                   which is the name field's cursor for no extra tiles.
        81 .. 88   the Z80's default name banner, $8F-$96.

    Returns (text, count) so main() can count the run in the budget.
    """
    # The grid is drawn as SCORE_GRID_ROWS full rows of SCORE_GRID_COLS, so the
    # alphabet has to fill them exactly. A short last row would draw whatever
    # followed ScoreGrid in ROM into the panel.
    assert len(SCORE_ALPHABET) % SCORE_GRID_COLS == 0, \
        "%d cells do not fill rows of %d" % (len(SCORE_ALPHABET), SCORE_GRID_COLS)
    chars = sorted(set(SCORE_HEADING + "".join(SCORE_LEGEND) + SCORE_ALPHABET
                       + "0123456789" + SCORE_NOTICE_LEVEL + SCORE_NOTICE_OVER
                       + SCORE_NOTICE_TIME + "".join(t for _, t in SCORE_INSTR)
                       + SCORE_TITLE_HELP[1]))
    # The asm reads the first of these positions rather than searching for it:
    # index 0 has to be the space glyph, or a blank name byte would draw
    # something. The digit base is emitted as a DEF (SCORE_DIGIT_FIRST), so a
    # character that sorts before '0' -- '!', here -- does not disturb it.
    assert chars[0] == " ", chars[0]
    index = {ch: n for n, ch in enumerate(chars)}
    glyph_count = len(chars)
    inv_first = glyph_count
    logo_first = glyph_count + len(SCORE_ALPHABET)

    tiles = []
    for ch in chars:
        t = to_gb_tile(gfx[ord(ch) * 8:ord(ch) * 8 + 8], HUD_SHADE)
        if ch != " ":
            assert any(t), "glyph %r came out blank -- the ASCII index is wrong" % ch
        tiles.append(t)
    for ch in SCORE_ALPHABET:
        tiles.append(to_gb_inverted(gfx[ord(ch) * 8:ord(ch) * 8 + 8]))
    for c in SCORE_BANNER:
        t = to_gb_tile(gfx[c * 8:c * 8 + 8], HUD_SHADE)
        assert any(t), "banner tile $%02X came out blank" % c
        tiles.append(t)

    def rows(t):
        return "    db " + ",".join("$%02X,$%02X" % (t[i], t[i + 1])
                                    for i in range(0, 16, 2))

    out = ["; Generated by tools/gbdata.py -- do not edit.",
           ";",
           "; The screens that share one glyph run: the high-score table, the",
           "; instructions, and the three announcements. ScoreTiles is the run",
           "; -- the glyphs those screens' strings and scores use (ASCII order),",
           "; then the alphabet inverted for the grid cursor, then the Z80's own",
           "; default-name banner. ScoreGlyphsAscii names the first group so a",
           "; check can find the run in VRAM by its pixels.",
           ";",
           "; Every string here is FIXED WIDTH, so there are no terminators and",
           "; index 0 is the space glyph rather than an end marker -- which is",
           "; what lets a blank name byte render as a blank.",
           'SECTION "Score", ROM0', "",
           "ScoreTiles:"]
    for ch, t in zip(chars, tiles):
        out.append("    ; %r (ASCII $%02X)" % (ch, ord(ch)))
        out.append(rows(t))
    out += ["ScoreGlyphsEnd:", "",
            "; The same alphabet inverted, in grid order (space first), so the",
            "; grid cursor tile for cell n is SCORE_TILE_BASE + SCORE_INV_FIRST + n.",
            "ScoreInvTiles:"]
    for n, ch in enumerate(SCORE_ALPHABET):
        out.append("    ; %r inverted" % ch)
        out.append(rows(tiles[inv_first + n]))
    out += ["",
            "; The Z80's $8F-$96 block: the ten entries' default name, and the",
            "; only place a name holds tiles that are not characters.",
            "ScoreBannerTiles:"]
    for n, c in enumerate(SCORE_BANNER):
        out.append("    ; the source's tile $%02X" % c)
        out.append(rows(tiles[logo_first + n]))
    # ScoreGlyphsAscii goes AFTER the run it names: it is a lookup for a check,
    # not part of the tile block, and 54 stray bytes inside ScoreTiles would be
    # copied into VRAM as three and a bit tiles of rubbish.
    out += ["ScoreTilesEnd:", "",
            "ScoreGlyphsAscii:",
            "    db " + ",".join("$%02X" % ord(ch) for ch in chars),
            "",
            "ScoreHeading:",
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_HEADING),
            "ScoreLegend1:",
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_LEGEND[0]),
            "ScoreLegend2:",
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_LEGEND[1]),
            "",
            "; The alphabet grid, cell by cell in reading order. Each entry is a",
            "; glyph index into the run above, so the grid IS the alphabet.",
            "ScoreGrid:",
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_ALPHABET),
            "",
            "; A seeded entry: 10 name bytes then the 5 score digits, digits",
            "; most significant first and units last (wScore's own layout). The",
            "; name is already glyph indices -- index 0 is the space glyph, and",
            "; the banner's tiles are indices in their own right because they",
            "; live in the same run.",
            "DefaultEntry:",
            "    db " + ",".join("$%02X" % v for v in
                                [index[" "]]
                                + [logo_first + n for n in range(len(SCORE_BANNER))]
                                + [index[" "]]
                                + SCORE_DEFAULT_SCORE),
            "",
            "; The three announcements, as records ShowNotice reads: a map row,",
            "; a map column (centred the way the score screen's lines are), a",
            "; cell count, then that many glyph indices. LEVEL's last TWO cells are",
            "; NOTICE_TENS and NOTICE_DIGIT, which ShowNotice fills with the level's",
            "; number -- two cells, as the Z80's own text has them, so the line is",
            "; \"level  9\" under ten and \"level 12\" above it.",
            "NoticeLevel:",
            "    db %d,%d,%d" % (SCORE_NOTICE_ROW,
                                (20 - len(SCORE_NOTICE_LEVEL) - 2) // 2,
                                len(SCORE_NOTICE_LEVEL) + 2),
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_NOTICE_LEVEL)
            + ",$%02X" % SCORE_NOTICE_TENS + ",$%02X" % SCORE_NOTICE_MARK,
            "NoticeGameOver:",
            "    db %d,%d,%d" % (SCORE_NOTICE_ROW,
                                (20 - len(SCORE_NOTICE_OVER)) // 2,
                                len(SCORE_NOTICE_OVER)),
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_NOTICE_OVER),
            "NoticeTimeUp:",
            "    db %d,%d,%d" % (SCORE_NOTICE_ROW,
                                (20 - len(SCORE_NOTICE_TIME)) // 2,
                                len(SCORE_NOTICE_TIME)),
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_NOTICE_TIME),
            "",
            "; The instructions screen: (row, col, cell count) then that many",
            "; glyph indices, one record a line, ended by a row byte of $FF --",
            "; the layout DrawScoreLines walks. Unlike the table's lines these",
            "; are a table rather than one stanza of asm each, because there is",
            "; nothing interleaved between them.",
            "InstructionsLines:"]
    for row, text in SCORE_INSTR:
        out += ["    db %d,%d,%d" % (row, (20 - len(text)) // 2, len(text)),
                "    db " + ",".join("$%02X" % index[c] for c in text)]
    out += ["    db $%02X" % SCORE_INSTR_END, "",
            "; The title's SELECT hint -- same record shape, drawn by the same",
            "; walker, but it lands on a screen of its own.",
            "TitleHelpLine:",
            "    db %d,%d,%d" % (SCORE_TITLE_HELP[0],
                                (20 - len(SCORE_TITLE_HELP[1])) // 2,
                                len(SCORE_TITLE_HELP[1])),
            "    db " + ",".join("$%02X" % index[c] for c in SCORE_TITLE_HELP[1]),
            "    db $%02X" % SCORE_INSTR_END, ""]

    out += ["DEF SCORE_TILE_COUNT   EQU %d" % len(tiles),
            "DEF SCORE_GLYPH_COUNT  EQU %d" % glyph_count,
            "DEF SCORE_INV_FIRST    EQU %d" % inv_first,
            "DEF SCORE_LOGO_FIRST   EQU %d" % logo_first,
            "DEF SCORE_DIGIT_FIRST  EQU %d" % index["0"],
            # Two markers, both past every real glyph index: the level's units
            # digit and, before it, the tens.
            "DEF NOTICE_TENS        EQU %d" % SCORE_NOTICE_TENS,
            "DEF NOTICE_DIGIT       EQU %d" % SCORE_NOTICE_MARK,
            "DEF SCORE_COUNT        EQU %d" % SCORE_COUNT,
            "DEF SCORE_NAME_LEN     EQU %d" % SCORE_NAME_LEN,
            "DEF SCORE_SCORE_LEN    EQU %d" % SCORE_SCORE_LEN,
            "DEF SCORE_ENTRY_BYTES  EQU %d" % (SCORE_NAME_LEN + SCORE_SCORE_LEN),
            "DEF SCORE_GRID_COLS    EQU %d" % SCORE_GRID_COLS,
            "DEF SCORE_GRID_ROWS    EQU %d" % (len(SCORE_ALPHABET) // SCORE_GRID_COLS),
            "DEF SCORE_PANEL_STEP EQU %d" % SCORE_PANEL_STEP,
            "DEF SCORE_HEADING_ROW  EQU %d" % SCORE_HEADING_ROW,
            "DEF SCORE_HEADING_COL  EQU %d" % ((20 - len(SCORE_HEADING)) // 2),
            "DEF SCORE_HEADING_LEN  EQU %d" % len(SCORE_HEADING),
            "DEF SCORE_ENTRY_ROW0   EQU %d" % SCORE_ENTRY_ROW0,
            "DEF SCORE_ENTRY_COL    EQU %d" % ((20 - SCORE_NAME_LEN
                                                - SCORE_SCORE_LEN) // 2),
            "DEF SCORE_GRID_ROW     EQU %d" % SCORE_GRID_ROW,
            "DEF SCORE_GRID_COL     EQU %d" % ((20 - SCORE_GRID_COLS) // 2)]
    for n, line in enumerate(SCORE_LEGEND):
        out += ["DEF SCORE_LEGEND%d_ROW EQU %d" % (n + 1, SCORE_LEGEND_ROW0 + n * SCORE_PANEL_STEP),
                "DEF SCORE_LEGEND%d_COL EQU %d" % (n + 1, (20 - len(line)) // 2),
                "DEF SCORE_LEGEND%d_LEN EQU %d" % (n + 1, len(line))]
    out.append("")
    return "\n".join(out), len(tiles)


# --- Hen (ostrich) sprites -------------------------------------------------
# NOT at paulie's `gfx_HenLeft` ($900E) -- that label is two bytes early, which
# shifts every block by one pixel row and pairs each row's right byte with the
# next row's left byte. mrcook's address table names the blocks individually and
# puts the first one at $9010, and the bytes there match mrcook's disassembly
# byte for byte, so that is the base.
#
#   0 left       1 right            standing
#   2 climb0     3 climb1           two-frame climb cycle
#   4 left_walk  5 right_walk       walking
#   6 eat_left   7 eat_right        pecking -- NOT usable art
#
# Blocks 6 and 7 are a merged composite rather than a sprite: rendered, each is
# a hen body overlapped with a dithered copy of the other direction's. They are
# what the original ROM holds at those addresses, so they are extracted as-is
# for completeness, but DrawOneHen does not use them -- a pecking hen keeps its
# standing pose.
#
# The Z80 pre-shifts these by 4px because a Spectrum screen write is byte-aligned
# (`GetScreenAddress` is `x >> 3`, so the picture lands on a byte whatever x is).
# It compensates by choosing the +4 copy whenever the hen's x is at the half
# cell: `BIT 2,E; ADD A,$04` picks 4/5 for a walk and the climb pair 2/3 --
# whose art is drawn 4px right too -- is only ever reached from a climb, which
# its own `BIT 2,E` gate limits to `x&4` set. The two always cancel, so the
# original's hen stands at its record's x and only its legs move.
#
# A GB OBJ takes a pixel X, so the port keeps the draw address exact (DrawOneHen
# adds the OAM column to x, not to x&$F8) and the shift has to come off the art
# instead. Leaving it in put every walk and climb frame 4px right of the
# original -- a wander jittering as the cycle alternated, since only the +4 half
# of it was displaced, and a climbing hen parked 4px off its ladder for the
# whole climb, which is how it was found.
HEN_BASE = 0x9010
HEN_FRAMES = 8
# The frames the Z80's `+$04` selects, i.e. the ones carrying its shift. 6/7 are
# the pecking pair, drawn without the compensation and left exactly as the ROM
# holds them; DrawOneHen does not use them (see below).
HEN_SHIFTED = {2, 3, 4, 5}
# The directions a hen record can hold. 1-4 are the HEN_* equates; pecking is
# dir+HEN_PECKING, so a hen that has found birdseed ahead of it carries 7 or 8,
# not 6 -- 6 is only the threshold the FSM tests against.
HEN_DIRS = {1, 2, 3, 4, 7, 8}

# Where each frame's 4 tiles live in the frame. Order matters: OAM is filled
# as TL, TR, BL, BR.
def sprite_tiles(sprite):
    """16x16 1bpp sprite (32 bytes) -> 4 GB 2bpp tiles, TL TR BL BR."""
    out = []
    for half in range(2):
        for col in range(2):
            rows = [sprite[(half * 8 + r) * 2 + col] for r in range(8)]
            out.append(to_gb_tile(rows, SPRITE_SHADE))
    return out


def deshift(sprite):
    """A 16x16 1bpp sprite (32 bytes, 2 a row, MSB first) moved 4px left.

    The Z80's sprite writes are byte-aligned, so its art for a hen at the half
    cell is drawn 4px right to cancel that; ours is not, so the shift comes back
    off. Nothing is lost: only the ink in the rightmost 4px would be, and the
    frames this applies to end their ink at column 11.
    """
    out = bytearray(SPRITE_BYTES)
    for r in range(16):
        row = ((sprite[r * 2] << 8) | sprite[r * 2 + 1]) << 4 & 0xFFFF
        out[r * 2], out[r * 2 + 1] = row >> 8, row & 0xFF
    return bytes(out)


def build(asm_path):
    mem, labels = parse_asm(asm_path)

    # $84F0 is authoritative from mrcook's address table; cross-check it
    # against the other repo's label so the two references agree.
    assert labels.get("gfx_CharacterSet") == GFX_BASE, \
        "gfx_CharacterSet is at $%04X, expected $%04X" % \
        (labels.get("gfx_CharacterSet"), GFX_BASE)

    # The levels are NOT at the org address: `org $b200` is followed by
    # `ds 256, $9c` and then code. Take the address from the label, and require
    # all eight to be contiguous at exactly 672 bytes apart.
    lvl_base = labels["Level1"]
    for i in range(2, LEVEL_COUNT + 1):
        want = lvl_base + (i - 1) * LEVEL_SIZE
        got = labels.get("Level%d" % i)
        assert got == want, "Level%d at $%04X, expected $%04X (levels not contiguous)" \
            % (i, got, want)

    gfx = extract(mem, GFX_BASE, GFX_LEN, "graphics")
    lvls = extract(mem, lvl_base, LEVEL_COUNT * LEVEL_SIZE, "levels")
    levels = [lvls[i * LEVEL_SIZE:(i + 1) * LEVEL_SIZE] for i in range(LEVEL_COUNT)]

    sprite_base = labels.get(SPRITE_LABEL)
    assert sprite_base, "%s not found -- sprite table moved?" % SPRITE_LABEL
    harry = [extract(mem, sprite_base + n * SPRITE_BYTES, SPRITE_BYTES,
                     "sprite %d" % n) for n in HARRY_FRAMES]
    hens = [extract(mem, HEN_BASE + n * SPRITE_BYTES, SPRITE_BYTES,
                    "hen %d" % n) for n in range(HEN_FRAMES)]
    hens = [deshift(h) if n in HEN_SHIFTED else h for n, h in enumerate(hens)]
    for n, h in enumerate(hens):
        ink = [c for c in range(16) if any(row >> (15 - c) & 1 for row in
                                           ((h[r * 2] << 8) | h[r * 2 + 1]
                                            for r in range(16)))]
        # DrawOneHen puts the whole 16px sprite at the hen's own x, so a frame
        # that starts its ink past column 0 is one the Z80 shifted and we did
        # not. 6/7 are the untouched pecking composites; nothing draws them.
        if n not in (6, 7) and ink[0]:
            raise SystemExit(
                "hen frame %d starts its ink at column %d -- the Z80's x&4 "
                "shift is still in the art (HEN_SHIFTED)" % (n, ink[0]))

    # 8 levels x 21 bytes: [byte count][x,y,dir,frame] x n. The count is a BYTE
    # count, not a hen count -- 8 = 2 hens, 12 = 3, 16 = 4.
    hs = db_after_label(asm_path, "HenStarts", LEVEL_COUNT * 21)
    hentable = []
    for i in range(LEVEL_COUNT):
        rec = hs[i * 21:(i + 1) * 21]
        n = rec[0]
        assert n % 4 == 0 and 4 <= n <= 20, \
            "level %d hen byte count is %d, expected 4..20 in steps of 4" % (i + 1, n)
        hentable.append([tuple(rec[1 + 4 * k:5 + 4 * k]) for k in range(n // 4)])
        for x, y, d, _ in hentable[-1]:
            assert d in HEN_DIRS, "level %d hen direction %d is not a HEN_* value" % (i + 1, d)
            assert x % 4 == 0, "level %d hen x %d is not a multiple of 4" % (i + 1, x)

    # --- self-checks: fail loudly rather than emit plausible-looking garbage ---
    assert gfx[0:8] == bytes(8), "tile 0 should be the blank graphic"
    assert gfx[3 * 8:4 * 8] == bytes((0x38, 0x7E, 0xFF, 0xFF, 0xFF, 0x7E, 0x38, 0x00)), \
        "tile 3 should be the egg graphic"
    used = set()
    for lv in levels:
        used |= set(lv)
    unexpected = used - ALLOWED
    assert not unexpected, "level data references unexpected tile ids: %s" % \
        sorted(hex(v) for v in unexpected)
    for i, lv in enumerate(levels):
        assert len(lv) == LEVEL_SIZE, "level %d is %d bytes" % (i + 1, len(lv))

    # Harry's frames must be real sprites, not the padding after the table.
    for n, sp in zip(HARRY_FRAMES, harry):
        assert any(sp), "sprite %d is blank -- the frame list is wrong" % n
    for n, sp in enumerate(hens):
        assert any(sp), "hen frame %d is blank -- HEN_BASE is wrong" % n

    # --- compaction: 20 ids are used, 182 slots are burned ---------------------
    # Level data only ever references 20 of the 182 tile graphics, but a BG map
    # entry is an index, so an id of $b5 forces a 182-entry table to exist.
    # Levels (182) + Harry (48) + hens (32) = 262 > the 256 the one VRAM tile
    # bank holds, so the run is compacted to what is used and the level bytes
    # are remapped with it. The order is by original id, so the remap is stable
    # and the `TILE_*` equates stay in the same relative order.
    ids = sorted(used)
    remap = {orig: i for i, orig in enumerate(ids)}
    levels = [bytearray(remap[b] for b in lv) for lv in levels]

    return gfx, ids, levels, harry, hens, hentable


def mirror_sprite(sp):
    """A 32-byte 1bpp 16x16 sprite, flipped left to right.

    Row by row, left half and right half: reverse all 16 bits and swap the
    bytes. This is what OAM's X-flip does on hardware, at no tile cost -- which
    is why the duck's left facing needs no art of its own.
    """
    out = bytearray()
    for r in range(16):
        hi, lo = sp[r * 2], sp[r * 2 + 1]
        bits = [(hi >> (7 - i)) & 1 for i in range(8)] + \
               [(lo >> (7 - i)) & 1 for i in range(8)]
        bits.reverse()
        out += bytes((sum(bits[i] << (7 - i) for i in range(8)),
                      sum(bits[8 + i] << (7 - i) for i in range(8))))
    return bytes(out)


def duck_frames(asm_path):
    """The mother duck's emitted frames, as the 32-byte 1bpp sprites they are.

    Out of the same table Harry's frames come from, at the indices the Z80
    draws them by. Its own function rather than a seventh value out of build()
    because the duck is the one thing here nothing else needs -- and because a
    sixth return value would have had to be threaded through every verifier
    that unpacks five.

    All four source poses are read even though two are emitted: 10/11 being 8/9
    mirrored is the *reason* the port can draw the left facing with OAM's flip
    bit and stay inside the tile budget, so it is asserted here rather than
    trusted.
    """
    mem, labels = parse_asm(asm_path)
    base = labels.get(SPRITE_LABEL)
    assert base, "%s not found -- sprite table moved?" % SPRITE_LABEL
    poses = [extract(mem, base + n * SPRITE_BYTES, SPRITE_BYTES, "duck %d" % n)
             for n in DUCK_SOURCE_FRAMES]
    for n, sp in zip(DUCK_SOURCE_FRAMES, poses):
        assert any(sp), "duck frame %d is blank -- the frame list is wrong" % n

    rest, flap, rest_m, flap_m = poses
    assert rest != flap, \
        "duck frames %d and %d are identical -- there is no flap" % tuple(DUCK_FRAMES)
    assert mirror_sprite(rest) == rest_m and mirror_sprite(flap) == flap_m, \
        "the duck's left-facing poses are not its right-facing ones mirrored, " \
        "so the X-flip draw is not a mirror"
    return [rest, flap]


def asm_duck(frames):
    """The mother duck's two poses as GB 2bpp tiles, 4 a frame, TL TR BL BR."""
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; Mother duck 16x16 frames, 4 GB 8x8 tiles each, TL TR BL BR order.",
           "; Frame n starts at tile DUCK_TILE_BASE + n*4.",
           "; 0 wings down  1 wings up -- both right-facing, the source's 8 and 9.",
           "; The left facing is these drawn with OAM's X-flip and the columns",
           "; swapped; the source's 10/11 are 8/9 mirrored, which gbdata asserts.",
           'SECTION "Duck", ROM0', "", "DuckTiles:"]
    for n, sp in enumerate(frames):
        out.append("    ; frame %d -- %s" % (n, "wings down" if n == 0 else "wings up"))
        for tile in sprite_tiles(sp):
            rows = ["$%02X,$%02X" % (tile[i], tile[i + 1]) for i in range(0, 16, 2)]
            out.append("    db " + ",".join(rows))
    out += ["DuckTilesEnd:",
            "DEF DUCK_FRAMES EQU %d" % len(frames),
            "DEF DUCK_FRAME_TILES EQU 4",
            ""]
    return "\n".join(out)


def asm_tiles(gfx, ids):
    """Only the tile graphics the levels actually reference, compacted.

    `ids` is by original Spectrum id, so the low six keep their identity and
    the birdcage block lands immediately after them.
    """
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; GB 2bpp tiles. Compacted: only the %d graphics the level data" % len(ids),
           "; references are emitted, remapped to 0..%d in original-id order." % (len(ids) - 1),
           "; Spectrum tile id %s -> GB tile index 0..%d." % (ids[0], len(ids) - 1),
           "; Background (index 0) is black; 1/2/3 are ink, dark -> light.",
           'SECTION "Tiles", ROM0', "", "Tiles:"]
    for tid in ids:
        t = to_gb_tile(gfx[tid * 8:tid * 8 + 8], shade_for(tid))
        rows = ["$%02X,$%02X" % (t[i], t[i + 1]) for i in range(0, 16, 2)]
        body = ",".join(rows)
        note = "birdcage" if 0xA8 <= tid <= 0xB5 else ("tile" if tid <= 5 else "?")
        out.append("    ; Spectrum $%02X  %s" % (tid, note))
        out.append("    db " + body)
    out += ["TilesEnd:", "DEF TILE_COUNT EQU %d" % len(ids),
            "",
            "; Tile ids, from the Z80 source's own equates (lines 36-42).",
            "; These keep their values because ids $00-$05 sort first, so the",
            "; compaction is the identity on the base set -- the level bytes",
            "; below are remapped, and these are the indices they now hold.",
            "DEF TILE_BLANK      EQU $00",
            "DEF TILE_LADDERLEFT EQU $01",
            "DEF TILE_LADDERRIGHT EQU $02",
            "DEF TILE_EGG        EQU $03",
            "DEF TILE_BIRDSEED   EQU $04",
            "DEF TILE_PLATFORM   EQU $05",
            "; TILE_LAST is the first id that is NOT a playfield tile. In the Z80",
            "; that is $09 (ids 6-8 are graphics the level data never uses); after",
            "; compaction ids 6-8 are gone and the birdcage starts immediately, so",
            "; the boundary moves down to it. Callers use `cp TILE_LAST / ret nc`",
            "; to reject non-playfield cells, so this must stay the boundary.",
            "DEF TILE_CAGE_FIRST EQU %d" % ids.index(0xA8),
            "DEF TILE_CAGE_LAST  EQU %d" % ids.index(0xB5),
            "DEF TILE_LAST       EQU TILE_CAGE_FIRST",
            ""]
    return "\n".join(out)


def asm_levels(levels):
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; Level maps, one byte per 8x8 cell, 32 wide x 21 tall, exactly as in",
           "; the Z80 source: row 0 of the data is row 20 of the screen (bottom).",
           'SECTION "Levels", ROM0', "",
           "DEF LEVEL_WIDTH  EQU 32", "DEF LEVEL_HEIGHT EQU 21",
           "DEF LEVEL_COUNT  EQU %d" % len(levels), "", "Levels:"]
    for i, lv in enumerate(levels):
        out.append("Level%d:" % (i + 1))
        for r in range(21):
            row = lv[r * 32:(r + 1) * 32]
            out.append("    db " + ",".join("$%02X" % b for b in row))
    out += ["", "LevelTable:"]
    out += ["    dw Level%d" % (i + 1) for i in range(len(levels))]
    out += ["", "LevelsEnd:", ""]
    return "\n".join(out)


# --- music -----------------------------------------------------------------
# Both tunes, exactly as the source has them: (duration, pitch) pairs, with a
# first byte of 0 ending the stream. The pair counts include that terminator.
#
# PlayMusic's own comment calls the pair's FIRST byte "pitch", and it cannot be
# right: the title's first byte is only ever 1 or 2 across all 47 pairs, and the
# death tune's is a constant 2 while its second byte walks 8, 6, 4, 3, 1 -- two
# pitches is not a tune, and a constant pitch over a descending "duration" is
# not a death jingle. Read the other way the title has a melody and the death
# tune has a falling contour, which is what those two pieces are. The calc in
# PlayMusic (`db $A4 / db $05`, i.e. `10 / x`) takes the first byte, so the
# first byte is the duration in the ZX ROM's BEEP units and the second is the
# pitch: a semitone index from middle C, which is BEEP's own unit.
MUSIC = [("TitleMusic", 47), ("LoseLifeMusic", 25)]

# Pitch 0 is middle C; the GB's channel 1/2 period register P plays
# f = 131072 / (2048 - P), so P = 2048 - 131072 / f.
SEMITONE0_HZ = 261.63


def note_period(pitch):
    return 2048 - round(131072 / (SEMITONE0_HZ * 2 ** (pitch / 12)))


def music_streams(path):
    """The two tunes as byte lists, with the pair counts asserted."""
    out = []
    for label, pairs in MUSIC:
        vals = db_after_label(path, label, pairs * 2)
        assert vals[-2] == 0, "%s does not end with a 0 duration byte" % label
        out.append((label, vals))
    return out


def asm_music(streams):
    """The two tunes byte for byte, and the period table their pitches index."""
    top = max(p for _, vals in streams for p in vals[1::2])
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           ";",
           "; The two tunes from the Z80 source, byte for byte: (duration, pitch)",
           "; pairs, a first byte of 0 ending the stream. The duration is in BEEP",
           "; units and the pitch is a semitone index from middle C -- see",
           "; gbdata.py for why the first byte is the duration and not the pitch,",
           "; which is what the source's own comment says.",
           "",
           'SECTION "Music", ROM0', "",
           "; Channel 1/2 period per semitone, P = 2048 - 131072 / f. Every pitch",
           "; either tune uses is inside it.",
           "MusicPeriods:"]
    for i in range(top + 1):
        out.append("    dw %d" % note_period(i))
    out += ["DEF MUSIC_PITCH_MAX EQU %d" % top, ""]
    for label, vals in streams:
        out.append("%s:" % label)
        for i in range(0, len(vals), 8):
            out.append("    db " + ",".join("$%02X" % b for b in vals[i:i + 8]))
        out.append("%sEnd:" % label)
        out.append("")
    return "\n".join(out)


def asm_sprites(harry):
    """Harry's frames as GB 2bpp tiles, 4 per frame in TL TR BL BR order."""
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; Harry's 16x16 sprite frames, 4 GB 8x8 tiles each, in TL TR BL BR",
           "; order. Frame n starts at tile HARRY_TILE_BASE + n*4.",
           "; Frame order: 0-3 walk right, 4-7 walk left, 8-11 climbing.",
           'SECTION "Sprites", ROM0', "", "HarryTiles:"]
    for n, sp in enumerate(harry):
        out.append("    ; frame %d" % n)
        for q, tile in enumerate(sprite_tiles(sp)):
            rows = ["$%02X,$%02X" % (tile[i], tile[i + 1]) for i in range(0, 16, 2)]
            out.append("    db " + ",".join(rows))
    out += ["HarryTilesEnd:",
            "DEF HARRY_FRAMES EQU %d" % len(harry),
            "DEF HARRY_FRAME_TILES EQU 4",
            ""]
    return "\n".join(out)


def asm_hens(hens):
    """The hen (ostrich) frames as GB 2bpp tiles, 4 per frame, TL TR BL BR."""
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; Hen 16x16 frames, 4 GB 8x8 tiles each, TL TR BL BR order.",
           "; Frame n starts at tile HEN_TILE_BASE + n*4.",
           "; 0 left  1 right  2/3 climb  4 left-walk  5 right-walk  6/7 pecking.",
           "; The Z80 keeps its +4px copies of 2/3 and 4/5, because its sprite",
           "; writes are byte-aligned; an OBJ takes a pixel X, so the shift is",
           "; taken off the art and every frame stands at the hen's own x.",
           'SECTION "Hens", ROM0', "", "HenTiles:"]
    for n, sp in enumerate(hens):
        out.append("    ; frame %d" % n)
        for tile in sprite_tiles(sp):
            rows = ["$%02X,$%02X" % (tile[i], tile[i + 1]) for i in range(0, 16, 2)]
            out.append("    db " + ",".join(rows))
    out += ["HenTilesEnd:",
            "DEF HEN_FRAMES      EQU %d" % len(hens),
            "DEF HEN_FRAME_TILES EQU 4",
            ""]
    return "\n".join(out)


def asm_henstarts(hs):
    """Per-level hen spawns: a live count, then the source's own five records.

    Fixed-size records so the runtime index is `base + (level-1)*21` with no
    offset table. Byte 0 is the hen count; the Z80 stores a BYTE count here
    (8/12/16), which is a distinction with no purpose once the GB loop is a
    plain DJNZ over hens.

    All five slots go in, not just the count's worth, and they are the source's
    bytes rather than filler: from the twenty-fifth level the Z80 overwrites the
    count with $14 -- twenty bytes, i.e. every slot (`CP $18`,
    Chuckie.asm:5974-5978) -- so those levels run the whole table, the records
    the count leaves idle included. The spares are therefore asserted as real
    hen records: on the fifth lap they are live birds, not padding.
    """
    out = ["; Generated by tools/gbdata.py -- do not edit.",
           "; Per-level hen spawns. Record = [count][x,y,dir,frame] x 5. Levels",
           "; 1..24 spawn `count` of them; 25 and up spawn all five (the Z80's",
           "; `CP $18`), so the spare records are live data, not padding.",
           'SECTION "HenStarts", ROM0', "", "HenStarts:"]
    for i in range(LEVEL_COUNT):
        rec = hs[i * 21:(i + 1) * 21]
        n = rec[0] // 4
        out.append("    db %d   ; level %d -- %d hens, %d spare in the table"
                   % (n, i + 1, n, 5 - n))
        for k in range(5):
            x, y, d, f = rec[1 + 4 * k:5 + 4 * k]
            assert d in HEN_DIRS and x % 4 == 0, \
                "level %d hen slot %d is not a hen record: (%d,%d,%d,%d)" % (
                    i + 1, k + 1, x, y, d, f)
            out.append("    db $%02X,$%02X,$%02X,$%02X" % (x, y, d, f))
    out += ["HenStartsEnd:",
            "DEF HEN_MAX         EQU 5",
            "DEF HEN_RECORD      EQU 21",
            ""]
    return "\n".join(out)


def main():
    asm = "reference/paulie/Chuckie.asm"
    if "--asm" in sys.argv:
        asm = sys.argv[sys.argv.index("--asm") + 1]
    gfx, ids, levels, harry, hens, hentable = build(asm)
    music = music_streams(asm)
    print("tiles:    %d extracted, %d used and emitted" % (len(gfx) // 8, len(ids)))
    print("levels:   %d levels x %d bytes" % (len(levels), len(levels[0])))
    print("sprites:  %d Harry frames x 4 tiles" % len(harry))
    print("hens:     %d frames x 4 tiles, %s" %
          (len(hens), "/".join(str(len(h)) for h in hentable)))
    print("font:     %d glyphs (%s)" % (len(HUD_CHARS), HUD_CHARS))
    print("music:    %s" % ", ".join("%s %d notes (%d bytes)"
                                     % (n, len(v) // 2 - 1, len(v)) for n, v in music))
    title, nglyphs, nlogo = asm_title(gfx, title_logo(asm))
    print("title:    %d glyphs + %d logo tiles, %d lines"
          % (nglyphs, nlogo, len(TITLE_LINES)))
    score, nscore = asm_score(gfx)
    print("score:    %d tiles (%d glyphs + %d inverted + %d banner), %d entries, "
          "%d instruction lines"
          % (nscore, len(set(SCORE_HEADING + "".join(SCORE_LEGEND)
                             + SCORE_ALPHABET + "0123456789"
                             + "".join(t for _, t in SCORE_INSTR))),
             len(SCORE_ALPHABET), len(SCORE_BANNER), SCORE_COUNT, len(SCORE_INSTR)))
    ducks = duck_frames(asm)
    duck = asm_duck(ducks)
    print("duck:     %d frames x 4 tiles (source frames %s)"
          % (len(ducks), ", ".join(str(n) for n in DUCK_FRAMES)))
    # The two lift tiles are the ROM's own source (main.asm's LiftTiles), not
    # extracted here -- counted anyway so the budget is the real one.
    total = (len(ids) + len(harry) * 4 + len(hens) * 4 + 2 + len(HUD_CHARS)
             + nglyphs + nlogo + nscore + len(ducks) * 4)
    print("VRAM:     %d/%d tiles used by the level + sprites + HUD + title + "
          "score + duck" % (total, 256))
    assert total <= 256, "over the 256-tile VRAM budget"

    if "--write" in sys.argv:
        outdir = sys.argv[sys.argv.index("--write") + 1]
        open(outdir + "/tiles.asm", "w").write(asm_tiles(gfx, ids))
        open(outdir + "/levels.asm", "w").write(asm_levels(levels))
        open(outdir + "/sprites.asm", "w").write(asm_sprites(harry))
        open(outdir + "/hens.asm", "w").write(asm_hens(hens))
        open(outdir + "/henstarts.asm", "w").write(
            asm_henstarts(db_after_label(asm, "HenStarts", LEVEL_COUNT * 21)))
        open(outdir + "/font.asm", "w").write(asm_font(gfx))
        open(outdir + "/music.asm", "w").write(asm_music(music))
        open(outdir + "/title.asm", "w").write(title)
        open(outdir + "/score.asm", "w").write(score)
        open(outdir + "/duck.asm", "w").write(duck)
        print("wrote %s/{tiles,levels,sprites,hens,henstarts,font,music,"
              "title,score,duck}.asm" % outdir)


if __name__ == "__main__":
    main()
