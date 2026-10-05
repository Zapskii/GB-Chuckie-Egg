# Chuckie Egg — Game Boy

A port of the ZX Spectrum game (1983, Nigel Alderton / A&F Software) to the DMG,
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
    make verify      # 17 targets, 32 RESULT lines

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

## History

*Chuckie Egg* was released by A&F Software in **1983** for the ZX Spectrum 48K, at
£6.90. Nigel Alderton wrote it as a teenager — he worked Saturdays in A&F's
Rochdale shop — after showing the company a game he had been writing himself,
under the working title *Eggy Kong*. It was built on the arcade games he was
playing at the time, *Donkey Kong* and above all *Space Panic*: he described the
result as "really Space Panic 2". Doug Anderson wrote the BBC Micro version
alongside it and Mike Webb the Dragon port. It reached #12 in the multiple-formats
chart in late 1983 and the BBC version topped the BBC charts for a week in 1984; a
1984 re-release by Pick & Choose kept it on shelves, and reportedly over a million
copies sold across its ports. A sequel, *Chuckie Egg 2 (Choccy Egg)*, followed in
1985.

The port list is long and covers most of the machines of the period — ZX Spectrum,
BBC Micro and Dragon 32/64 in 1983; Commodore 64 (May 1984), Acorn Electron and
MSX in 1984; Tatung Einstein, Amstrad CPC and Atari 8-bit in 1985; Amiga and Atari
ST in 1988; IBM PC in 1989; and a VIC-20 version as late as 2021.

**There was never a released Game Boy version.** No Nintendo platform appears in
any of the game's release records — not the DMG, not the Game Boy Color, neither
officially licensed nor first-party. What exists is homebrew, and only since: the
Game Boy Color beta *Chuckie DX GB* (Chris Bailey / The HiVE, last updated 2001,
shipped without music, pause or a high-score table), and
[DrAndyArmstrong/chuckie-egg-gb](https://github.com/DrAndyArmstrong/chuckie-egg-gb),
a recent Color port built from the **BBC Micro** original rather than the Spectrum
one.

This repository is another of those: the ZX Spectrum version, ported to the
original DMG rather than the Color, in RGBDS assembly.

Sources: [Wikipedia](https://en.wikipedia.org/wiki/Chuckie_Egg),
[World of Spectrum](https://worldofspectrum.net/item/0000958/),
[Spectrum Computing](https://spectrumcomputing.co.uk/entry/0000958),
[GameBrew](https://www.gamebrew.org/wiki/Chuckie_DX_GB), and
[The Guardian](https://www.theguardian.com/games/2026/apr/21/in-my-mind-it-was-just-tall-birds-wandering-around-on-platforms-the-making-of-chuckie-egg).
