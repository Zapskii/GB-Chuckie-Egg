#!/usr/bin/env python3
"""Headless screenshot with scripted input.

    tools/shot.py rom.gb out.png [frames] [script]

`script` is one character per frame, so input can be scripted across a run:
    .       no input          R/L/U/D   d-pad
    A B     A / B             S T       START / SELECT
e.g. the 200th frame of "flying right while holding fire" is
    tools/shot.py chuckie.gb out.png 200 ...(197 dots)...RRA

This is a dev tool; nothing in the build depends on it. PyBoy has no window and
needs no permissions, which is the point -- mGBA cannot be driven from a script
here.

Two timing traps, both in PLAN.md: PyBoy's own boot ROM holds the screen until
about frame 66, and this ROM boots to the title, so a shot of the game itself
wants FRAMES=200 or more with an `S` early in the script to leave the title.
"""
import sys

from pyboy import PyBoy

KEYS = {"R": "right", "L": "left", "U": "up", "D": "down",
        "A": "a", "B": "b", "S": "start", "T": "select"}


def main():
    rom, out = sys.argv[1], sys.argv[2]
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    script = sys.argv[4] if len(sys.argv) > 4 else ""

    pyboy = PyBoy(rom, window="null", sound_emulated=False)
    for i in range(frames):
        ch = script[i] if i < len(script) else "."
        key = KEYS.get(ch)
        if key:
            pyboy.button_press(key)
        pyboy.tick(1, True)
        if key:
            pyboy.button_release(key)

    pyboy.screen.image.save(out)
    pyboy.stop(save=False)
    print("wrote %s after %d frames" % (out, frames))


if __name__ == "__main__":
    main()
