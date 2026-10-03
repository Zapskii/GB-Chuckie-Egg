#!/usr/bin/env python3
"""Assert UpdateCamera's clamping, by driving wPlayerY and reading SCY.

The camera is a pure function of Harry's y: SCY = clamp(96 - y, 0, 32). It is
easy to get the clamp wrong in a way that only shows up as a jitter at the top
or bottom of the playfield, which no screenshot would catch. So poke the
variable directly and check the whole range, boundaries included.

The upper bound is 32, not the 24 the level's own 21 rows against 18 visible
would give: Phase 6a's status band takes 8 px off the top of the playfield, and
the camera's travel grows by exactly that.

    python3 tools/verify_camera.py [rom.gb] [rom.sym]
"""
import os
import re
import sys

import harness


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(ROM)[0] + ".sym"


def symbols(path):
    """RGBDS .sym is 'BB:AAAA Name'."""
    syms = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return syms


syms = symbols(SYM)
for name in ("wPlayerY", "wPlayerInAir", "wInAirCounter"):
    if name not in syms:
        raise SystemExit("FAIL: %s not in %s -- is main.asm still declaring it?" % (name, SYM))
wPlayerY = syms["wPlayerY"]
wPlayerInAir = syms["wPlayerInAir"]
wInAirCounter = syms["wInAirCounter"]

# y -> expected SCY. Boundaries: 64 is the last y pinned to the bottom (96-32),
# 96 the first pinned to the top, so 65 and 95 are the ones that actually move.
CASES = [(0, 32), (1, 32), (63, 32), (64, 32), (65, 31),
         (84, 12), (95, 1), (96, 0), (120, 0), (167, 0)]

pb = harness.boot(ROM)

bad = 0
for y, want in CASES:
    pb.memory[wPlayerY] = y
    # Pin him to the ground and tick ONE frame. This is a test of UpdateCamera,
    # and since Phase 3 the game moves Harry for real: CheckForFalling starts a
    # ledge countdown on any y the level has no floor under, which turns into a
    # fall and drifts y out from under the case. One frame is less than the
    # countdown, and the pin keeps it from ever accumulating.
    pb.memory[wPlayerInAir] = 0
    pb.memory[wInAirCounter] = 4
    pb.tick(1, True)                     # let a VBlank fire
    got = pb.memory[0xFF42]
    if got != want:
        bad += 1
        print("  y=%3d: SCY $%02X want $%02X" % (y, got, want))

print("UpdateCamera %d cases: %s" % (len(CASES), "PASS" if not bad else "FAIL"))

# --- horizontal. Same shape, but the range is much wider: the playfield is
# 256 px and the screen only 160, so SCX travels 0..96. The level's right-hand
# 96 px are unreachable without it, which is why it exists.
wPlayerX = syms["wPlayerX"]
XCASES = [(0, 0), (71, 0), (72, 0), (73, 1), (100, 28),
          (152, 80), (167, 95), (168, 96), (255, 96)]
xbad = 0
for x, want in XCASES:
    pb.memory[wPlayerX] = x
    pb.memory[wPlayerInAir] = 0
    pb.memory[wInAirCounter] = 4
    pb.tick(1, True)
    got = pb.memory[0xFF43]
    if got != want:
        xbad += 1
        print("  x=%3d: SCX $%02X want $%02X" % (x, got, want))

print("UpdateCamera %d horizontal cases: %s"
      % (len(XCASES), "PASS" if not xbad else "FAIL"))
bad += xbad

pb.stop(save=False)
sys.exit(1 if bad else 0)
