#!/usr/bin/env python3
"""Assert the memory the ROM reads before writing is harmless, not power-on noise.

Two bugs, both reported off real Game Boy hardware, and they are one bug twice:
a byte the ROM reads before it writes. An emulator powers OAM and WRAM up as
zeros, so the read returns 0 and nothing shows; a DMG powers them up with
whatever the cells held, and the read returns that.

  1. OAM entries nothing writes. `BlitOam` copies OAM_BYTES out of
     `wOamShadow` every VBlank and OAM_BYTES stops at the duck's last entry, so
     entries 32..39 are never written on any level; `DrawHens` skips the entries
     of a hen a level does not spawn (its HEN_NONE test) and `DrawLifts` the two
     platforms of a level with none, so 12..27 are left alone on level 1 as
     well. OAM is in SCREEN coordinates and nothing scrolls it, so a leftover
     entry is a sprite pinned to the screen while the level moves under it --
     which is how it was found: two small glyphs that did not scroll.

  2. `wOnNotice`, which the VBlank handler tests alongside the front-end flags
     and which skips the whole draw pass while it is set. Only `ShowNotice`
     writes it, and it clears it on the way out -- but the title's START goes
     EnterTitle -> StartGame -> NextLevel.reload, which is no notice at all, so
     the first level is played with the byte the machine powered on with.
     Nonzero there is no camera, no sprites and no status row for that level.

  3. ...and the same thing a level later. The draws skip the slots a level does
     not use, so a level that spawns fewer hens, or has no lift, than the one
     before it keeps that one's birds and platforms. Only `Start` used to clear
     the image, so a game over at level 3 left its third hen and a platform on
     level 1 for good -- the second report. Every level arrives through
     `LoadLevel`, which now clears it; the check stands in with the image as
     good as full of sprites and then loads level 1 over it.

`Start` now zeroes the shadow, all 40 OAM entries and wOnNotice with the LCD
off and interrupts still disabled. This check stands in for hardware -- every
OAM entry on screen, every WRAM byte dirty, before the first tick -- so
removing any of that fails here instead of passing on an emulator's zeros.

    python3 tools/verify_init.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"

OAM = 0xFE00
OAM_ENTRIES = 40
OAM_BYTES = 32 * 4            # src/main.asm: stops at the duck's last entry
WRAM = (0xC000, 0xE000)

# Level 1 is the boot ROM: two hens (of HEN_MAX 5) and no lift, so 12..27 are
# never written -- hens 3..5 and the two platforms -- and 32..39 are left alone
# on every level. The rest is Harry (0..3), the two hens (4..11) and the duck
# (28..31), and a frame that does not carry those has not been composed at all.
LEVEL1_DRAWN = list(range(0, 12)) + list(range(28, 32))
# ...and the rest, as far as the blitter copies. Past that -- 32..39 -- is OAM's
# alone: nothing on any level writes it and no shadow byte maps to it, so those
# are the boot clear's business and no level's.
LEVEL1_SKIPS = list(range(12, 28))
NEVER_WRITTEN = LEVEL1_SKIPS + list(range(32, OAM_ENTRIES))
# What `dirty` leaves in every entry, and what the boot clear leaves: an entry
# the ROM drew is neither.
POWER_ON = (80, 80, 40, 0)
CLEARED = (0, 0, 0, 0)

failed = []
fail = failed.append


def dirty(pb):
    """Put hardware's leftovers in before the ROM runs: not an emulator's 0."""
    for a in range(*WRAM):
        pb.memory[a] = 0xA5
    for i in range(OAM_ENTRIES):
        # Y 80 / X 80 is on screen, tile 40 is real art, attr 0 so nothing hides
        # it -- anything that survives into the frame is a visible stray.
        pb.memory[OAM + i * 4 + 0] = 80
        pb.memory[OAM + i * 4 + 1] = 80
        pb.memory[OAM + i * 4 + 2] = 40
        pb.memory[OAM + i * 4 + 3] = 0x00


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
missing = [n for n in ("wOamShadow", "wOnNotice") if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))


def oam(pb):
    return [tuple(pb.memory[OAM + i * 4:OAM + i * 4 + 4]) for i in range(OAM_ENTRIES)]


# On the title, and only there, the shadow still holds what Start left in it:
# the title draws no sprites at all (EnterTitle clears OBJ), so nothing has
# written it since. A byte left dirty here is a stray sprite from here on,
# because BlitOam copies this image every VBlank from now on.
title = harness.boot(ROM, prefill=dirty, start=False)
left = [i for i, b in enumerate(title.memory[sym["wOamShadow"]:sym["wOamShadow"] + OAM_BYTES]) if b]
if left:
    fail("wOamShadow has %d dirty bytes after Start, first at offset %d -- the "
         "boot clear is gone or BlitOam writes past OAM_BYTES" % (len(left), left[0]))
visible = [i for i, s in enumerate(oam(title)) if 16 <= s[0] <= 152]
if visible:
    fail("OAM entries %s are on screen before the first frame drew; an entry "
         "the ROM never writes is still holding what the machine powered up "
         "with" % visible)
print("on the title, with %d OAM entries and %d B of WRAM pre-dirtied: shadow "
      "clean, no entry on screen" % (OAM_ENTRIES, WRAM[1] - WRAM[0]))
title.stop(save=False)

# ...and it has to stay that way once the draws are running.
pb = harness.boot(ROM, prefill=dirty)
for _ in range(120):
    pb.tick(1, True)
oam_now = oam(pb)

stray = [i for i in NEVER_WRITTEN if oam_now[i][0] != 0]
if stray:
    fail("after 120 frames, entries %s the ROM never writes are not hidden: %s "
         "-- their Y is whatever memory held, and OAM is screen coordinates, so "
         "each is a sprite stuck to the screen" % (stray, [oam_now[i] for i in stray]))

blank = [i for i in LEVEL1_DRAWN if oam_now[i] in (POWER_ON, CLEARED)]
if blank:
    fail("after 120 frames, entries %s of level 1 still hold %s -- what the "
         "machine powered on with, or what the boot clear left. Nothing drew "
         "them, which is the wOnNotice leak: the handler skipped the draw pass"
         % (blank, [oam_now[i] for i in blank]))

print("after 120 frames: entries %s carry a sprite (Harry 0-3, the hens, the "
      "duck), and every entry the ROM leaves alone is hidden" % LEVEL1_DRAWN)
pb.stop(save=False)

# ...and again for a level loaded over one that filled slots this one does not.
# The state to stand in for is the level before's, so this starts on the title,
# where the boot clear has already run and nothing will overwrite the image
# before the load.
pb = harness.boot(ROM, start=False)
for i in range(OAM_BYTES):
    pb.memory[sym["wOamShadow"] + i] = 0xA5
    # into OAM as well, or the blit would put the shadow's own bytes up before
    # the first frame and the entries would be clean whatever LoadLevel did
    pb.memory[OAM + i] = 0xA5
harness.press_start(pb)                  # StartGame -> NextLevel.reload
for _ in range(4):
    pb.tick(1, True)
oam_now = oam(pb)

stale = [i for i in LEVEL1_SKIPS if oam_now[i] != CLEARED]
if stale:
    fail("a level loaded over a full sprite image still holds %s in entries %s "
         "-- the draws skip those slots, so what is there is the level before's, "
         "pinned to the screen" % ([oam_now[i] for i in stale], stale))
blank = [i for i in LEVEL1_DRAWN if oam_now[i] in (POWER_ON, CLEARED)]
if blank:
    fail("entries %s of level 1 are blank after a level load, so the frame was "
         "not composed and the check above proved nothing" % blank)

print("after a level load: entries %s carry a sprite and the %d slots level 1 "
      "does not use are hidden" % (LEVEL1_DRAWN, len(LEVEL1_SKIPS)))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
