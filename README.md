# Chuckie Egg — Game Boy

A port of the ZX Spectrum game (1984, Nigel Alderton / A&F Software) to the DMG,
written in RGBDS assembly. Not affiliated with or endorsed by the original rights
holders.

## Build

Needs [RGBDS](https://rgbds.gbdev.io/) 1.0.4 (`rgbasm`, `rgblink`, `rgbfix`) and
Python 3 with [PyBoy](https://github.com/Baekalfen/PyBoy) 2.7.0 for the checks.

This repository carries none of the game's data: the ten `src/*.asm` files holding
tiles, sprites, level maps, fonts, music and text are generated from a
disassembly of the original, so they are not tracked. Clone the reference,
generate them, build:

    git clone https://github.com/Paulie68000/ZXSpectrumChuckieEgg reference/paulie
    make data        # -> the ten generated src/*.asm files
    make             # -> chuckie.gb, 32K DMG, no mapper
    make verify      # 16 targets, 31 RESULT lines

`make data` refuses to run without the reference clone, and `reference/` is not
tracked. Regeneration is byte-exact: the same source gives the same ten files,
which are then `INCLUDE`d by `main.asm` and never assembled on their own.

    make level N=25  # -> build/l25.gb, boots straight into that level
    make shot        # headless screenshot (FRAMES=200 SCRIPT=...)
    make clean

Point `PY` at the right interpreter if your `python3` is not the one with PyBoy:

    make PY=/path/to/python verify

`make level N=` is how the levels above the reachable ones get looked at: it
names the ROM per level so the assemble-time flag is part of what was asked for,
and can never leave `chuckie.gb` booting somewhere stale. `make shot` writes a
PNG headlessly and takes input one character per frame (`.` none, `R/L/U/D`,
`A B`, `S T`) — see `tools/shot.py`. The ROM runs in any DMG emulator; mGBA is
what the port was play-tested in.

## Layout

- `src/main.asm` — the port. The ten generated files beside it are `INCLUDE`d
  data, not source: regenerate them with `make data`, never edit them.
- `tools/` — `gbdata.py`, the extractor that writes those files from the
  reference disassembly, plus `shot.py`, the shared `harness.py`, and one
  `verify_*.py` per check in `make verify`.
- `reference/` — the Z80 disassembly, cloned not tracked. Read:
  [Paulie68000/ZXSpectrumChuckieEgg](https://github.com/Paulie68000/ZXSpectrumChuckieEgg)
  for routine semantics and EQUates (`ecefdf2`, 2024-11-16); during development
  [mrcook/chuckie-egg-disassembly](https://github.com/mrcook/chuckie-egg-disassembly)
  (`bdd62fd`, 2021-10-24) was read alongside it for data, graphics and text, and
  is worth cloning for the same reasons.
- `PLAN.md` — the authoritative record: the goal, the per-phase findings, the
  traps that cost time, and the current status header. Read it before the code.
