#!/usr/bin/env python3
"""Assert the ROM's rendered level matches the Z80 source.

End-to-end check for Phase 1: parse the reference disassembly, derive what the
BG map and tile data SHOULD be, then read them back out of VRAM. Catches a bad
extraction, a bad 1bpp->2bpp conversion, and a bad row flip -- none of which a
screenshot would reliably show.

    python3 tools/verify.py [rom.gb]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbdata  # noqa: E402
import harness  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
ASM = "reference/paulie/Chuckie.asm"
SCRN0, VRAM = 0x9800, 0x8000
CAMERA_Y = 32            # must match the default in src/main.asm
# Phase 6a puts the status band across the top of the SCREEN, which takes 8 px
# off the playfield -- so the level sits one map row lower than its own height
# would put it, and the camera's travel grew from 24 to 32 to match. Data row 0
# is therefore map row 21, not 20, and map rows 0 and 22-31 are not the level.
# (The band itself is drawn in BG map 1, so it never appears here.)
MAP_ROW0 = 21
LEVEL = int(sys.argv[2]) if len(sys.argv) > 2 else 1

gfx, ids, levels, _, _, _ = gbdata.build(ASM)
# The eight maps repeat from the ninth level -- the Z80 masks its counter with
# `AND $07` at every lookup, and this ROM only boots past the eighth through
# LEVEL_NUM. So level 9 draws level 1's map (src/main.asm, GetLevelEntry).
level = levels[(LEVEL - 1) % len(levels)]

pb = harness.boot(ROM)

failed = False

if pb.memory[0xFF42] != CAMERA_Y:
    failed = True
    print("SCY is %d, expected CAMERA_Y=%d" % (pb.memory[0xFF42], CAMERA_Y))

# --- BG map: data row r lands on map row MAP_ROW0-r; the rest of the map is cleared ---
exp = bytearray(1024)
for m in range(21):
    r = m + (MAP_ROW0 - 20)          # the level's own last row is MAP_ROW0
    exp[r * 32:(r + 1) * 32] = level[(20 - m) * 32:(21 - m) * 32]
got = bytes(pb.memory[SCRN0:SCRN0 + 1024])
bad = [i for i in range(1024) if exp[i] != got[i]]
print("BG map 1024 cells: %s" % ("PASS" if not bad else "FAIL (%d differ)" % len(bad)))
if bad:
    failed = True
    for i in bad[:5]:
        print("  map row %2d col %2d: got $%02X want $%02X" % (i // 32, i % 32, got[i], exp[i]))

# --- tile data: every tile id the level actually uses, 1bpp -> 2bpp ---
# The level bytes are compacted ids (0..19); the graphic they name is the
# ORIGINAL Spectrum id, `ids[compacted]`, still in the raw 182-tile run.
used = sorted(set(level))
tidbad = []
for tid in used:
    orig = ids[tid]
    want = gbdata.to_gb_tile(gfx[orig * 8:orig * 8 + 8], gbdata.shade_for(orig))
    if want != bytes(pb.memory[VRAM + tid * 16:VRAM + tid * 16 + 16]):
        tidbad.append(tid)
print("tiles used by level %d (%d of 182, compacted to %d): %s"
      % (LEVEL, len(used), len(ids), "PASS" if not tidbad else
         "FAIL " + ",".join("$%02X" % t for t in tidbad)))
if tidbad:
    failed = True

# --- past the eighth level: the hen house is empty ------------------------
# The Z80's `CP $08`/`CP $10` at Chuckie.asm:5955-5961 skips the hen setup on
# those levels -- they are the freed mother duck's, not the hens'. Read off the
# sprite table rather than wHens: a hen that spawned would be drawn, and both of
# level 1's stand in view at the spawn camera, so the draw is the proof. Harry's
# own four entries are slots 0-3 and the duck's the last four.
if LEVEL > 8:
    live = [(i, tuple(pb.memory[0xFE00 + i * 4:0xFE04 + i * 4]))
            for i in range(4, 4 + 20)
            if 0 < pb.memory[0xFE00 + i * 4] < 160]
    print("past the eighth level: %d hen sprites drawn" % len(live))
    if live:
        failed = True
        print("  FAIL: %s -- the hens should not spawn here" % (live[:4],))

pb.stop(save=False)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
