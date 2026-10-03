#!/usr/bin/env python3
"""Bring a ROM up to a running game, for the verifiers.

Every check boots the same way and every one of them wants the same thing at the
end: the ROM has finished painting and a game is under way. Two steps, and the
second is 6c-2's -- the ROM now boots to the title, as the Z80's does, so a
level has to be asked for.

The readiness test keys on something only this ROM produces. Probing a map cell
fires mid-draw (the map is painted row by row with the LCD off); probing LCDC's
enable bit fires on the boot ROM, which also enables the LCD. BGP=$1B is ours
alone -- the boot ROM leaves $FC -- and it is written before the draw while the
LCD is turned on after it, so the pair means "fully painted".

`sound=True` is for verify_music.py, the one check that reads the APU registers
back: with sound_emulated=False PyBoy does not model them, so a write to one is
dropped and reads as 0.

`start=False` is for the checks that want the title itself rather than a game.
"""
import sys

from pyboy import PyBoy

# Held down for a few frames either side of the release. MainLoop reads the pad
# once a frame, so one frame would be enough -- but a pressed-then-released-in-
# the-same-tick edge is exactly the kind of thing an emulator's input model can
# swallow, and frames here are free.
START_FRAMES = 2


def boot(rom, sound=False, start=True):
    """The ROM up and running: screen painted, then START unless told not to."""
    pb = PyBoy(rom, window="null", sound_emulated=sound)
    for _ in range(1, 400):
        pb.tick(1, True)
        if pb.memory[0xFF40] & 0x80 and pb.memory[0xFF47] == 0x1B:
            break
    else:
        raise SystemExit("FAIL: ROM never finished setting up the screen")
    pb.tick(2)
    if start:
        press_start(pb)
    return pb


def tap(pb, button, frames=START_FRAMES):
    """Press a button long enough for the ROM to see it, then let go."""
    pb.button_press(button)
    pb.tick(frames, True)
    pb.button_release(button)
    pb.tick(frames, True)


def press_start(pb):
    """Press START until the ROM acts on it, then let go."""
    tap(pb, "start")


if __name__ == "__main__":
    # Self-check: everything else stands on this, so a silent change in what
    # "booted" means would be the worst failure to find later. The two modes are
    # told apart by the LCDC bits EnterTitle deliberately clears -- OBJ (bit 1),
    # which the title must not have, and WIN, which a game must.
    import os
    import re

    rom = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
    sym = {m.group(2): int(m.group(1), 16) for m in
           (re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", l)
            for l in open(os.path.splitext(rom)[0] + ".sym")) if m}

    title = boot(rom, start=False)
    lcdc, scy = title.memory[0xFF40], title.memory[0xFF42]
    print("title: LCDC $%02X OBJ %d WIN %d SCY %d wOnTitle %d"
          % (lcdc, lcdc >> 1 & 1, lcdc >> 5 & 1, scy, title.memory[sym["wOnTitle"]]))
    failed = False
    if not lcdc & 0x80:
        failed = True; print("FAIL: the LCD is off on the title")
    if lcdc & 0x02:
        failed = True; print("FAIL: the title draws OBJ, which holds boot noise")
    if lcdc & 0x20:
        failed = True; print("FAIL: the title draws the window band")
    if scy:
        failed = True; print("FAIL: the title is scrolled (SCY %d)" % scy)
    if title.memory[sym["wOnTitle"]] != 1:
        failed = True; print("FAIL: boot did not land on the title")
    title.stop(save=False)

    game = boot(rom, start=True)
    lcdc, scy = game.memory[0xFF40], game.memory[0xFF42]
    print("game:  LCDC $%02X OBJ %d WIN %d SCY %d wOnTitle %d"
          % (lcdc, lcdc >> 1 & 1, lcdc >> 5 & 1, scy, game.memory[sym["wOnTitle"]]))
    # WIN is the one asserted, not OBJ: the status band is a raster split, and
    # a tick leaves the frame at LY 0, inside it -- so a game reads WIN on with
    # OBJ off (the band may not be drawn over) and the title reads neither.
    # OBJ comes back at LY=8 for the playfield and so cannot be sampled here.
    if not lcdc & 0x20:
        failed = True; print("FAIL: a game does not put the status band up")
    if game.memory[sym["wOnTitle"]]:
        failed = True; print("FAIL: START did not leave the title")
    game.stop(save=False)

    print("RESULT:", "FAIL" if failed else "PASS")
    sys.exit(1 if failed else 0)
