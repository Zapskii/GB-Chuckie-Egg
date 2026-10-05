#!/usr/bin/env python3
"""Find every WRAM byte the ROM reads before it writes.

An emulator powers WRAM up as zeros; a DMG powers it up with whatever the cells
held. So a variable the ROM reads before writing is invisible in every PyBoy
check and shows up on hardware as whatever the garbage happened to mean. Two
bugs of that class reached a real Game Boy before this existed -- OAM entries
nothing writes, and wOnNotice left up, which the VBlank handler reads with the
front-end flags and which skips the whole draw pass while it is set. See
PLAN.md, "The bytes nothing writes", and tools/verify_init.py, which is the
same idea for the two that are known.

The sweep: boot a clean run, then boot again for each WRAM variable with only
that byte dirtied, and compare the frame. A variable the ROM writes before it
reads comes out identical whatever it was seeded with; one it reads first
changes the picture. Slow -- it is a baseline plus 78 boots and the value list
-- so it is a tool and not part of `make verify`.

    python3 tools/sweep_wram.py            # every variable, one value
    python3 tools/sweep_wram.py chuckie.gb 0xA5 0x01 0xFF
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
VALUES = [int(v, 0) for v in sys.argv[2:]] or [0xA5]
SYM = os.path.splitext(ROM)[0] + ".sym"
FRAMES = 150
OAM, OAM_BYTES = 0xFE00, 160


def symbols(path):
    return {m.group(2): int(m.group(1), 16) for m in
            (re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", l) for l in open(path)) if m}


sym = symbols(SYM)
# The ROM's variables, as the assembler laid them out. A label ending in End
# marks the end of a block rather than a variable of its own.
vars_ = sorted((a, n) for n, a in sym.items()
               if n.startswith("w") and 0xC000 <= a < 0xE000 and not n.endswith("End"))


def frame(pb):
    """What the screen says. Anything the ROM drew, and no internals: a
    variable it reads first and uses as a counter may still land on the same
    picture, and that is a miss the sweep accepts -- it is a net, not a proof."""
    return (bytes(pb.screen.ndarray.tobytes()), pb.memory[0xFF40],
            pb.memory[0xFF42], pb.memory[0xFF43], bytes(pb.memory[OAM:OAM + OAM_BYTES]))


def seed(addr, value):
    def prefill(pb):
        pb.memory[addr] = value
    return prefill


def run(dirt):
    pb = harness.boot(ROM, prefill=seed(*dirt) if dirt else None)
    for _ in range(FRAMES):
        pb.tick(1, True)
    out = frame(pb)
    pb.stop(save=False)
    return out


base = run(None)
print("%d variables x %d values, %d frames a run" % (len(vars_), len(VALUES), FRAMES))
hits = []
for v in VALUES:
    for a, n in vars_:
        if run((a, v)) != base:
            hits.append((n, v))
            print("  %-20s $%04X seeded $%02X -- the frame differs" % (n, a, v))
    print("  seeded $%02X: done" % v)

print("\n%d hits: %s" % (len(hits), sorted({n for n, _ in hits})))
