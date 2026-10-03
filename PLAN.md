# GB Chuckie Egg — Port Plan

Porting ZX Spectrum *Chuckie Egg* (1983, Nigel Alderton / A&F Software) to the
Game Boy (DMG / LR35902-SM83), written in RGBDS assembly.

Plan written 2026-10-02. Status: **Phases 6a/6b/6c-1/6c-2/6c-3/6c-4/7 complete**
— the status row and its two counters, the sound driver, lives with game over,
the title screen the ROM boots to, the high-score table between the two, and the
extra life. **The mother duck is in too** (Phase 4b below) — caged and harmless
through level 8, loose and lethal from 9. **The five laps are modelled**
(recorded below): the Z80's level counter has no bound, and every rule that
changes across a run — the duck's cage, the hens, their count, their speed, the
clock and the egg's score — is a threshold on it, so nothing is gated above
`$20` and level 41 is level 33 again. Three off-by-ones, all from reading the
source's 0-based counter as 1-based, went with it.
**The announcements are in** (Phase 7
below): the Z80's `ScrollTextLine` at its three call sites, holding the word
still where the Spectrum swept it across the screen. **The name-entry panel is
drawn only when the score actually made the table** — it used to appear, with a
legend naming the d-pad, under a game that never qualified, which is the ordinary
first game over (see the section below). **The front end is finished** — the
name-entry cursor starts on `A` rather than on the blank, and the instructions
screen is in off `SELECT` at the title, re-authored rather than ported because
the Z80's is Spectrum key documentation (see the section below; it is a recorded
divergence). With that, `FrontEnd`'s menu is closed: redefinition and input type
have no DMG meaning, and the title already plays its tune. **The duck flaps,
and its pose and facing both step on the duck's own clock** — the facing used to
be re-read off Harry on every drawn frame, which turned the bird on frames that
were not its steps (the jitter); the flap is drawn by flipping the right-facing
frames, so it costs no tiles — **and the 10-sprites-a-line limit is guarded
rather than worked around**, measured and pinned as an OAM-order contract (all
three recorded below).
**Harry starts where the game starts him** — PlayLevel's `$64`/`$17`, on the
level's own floor, rather than the program image's `$AE`/`$37` on a platform five
rows up; the Phase 2 "information asymmetry" was a property of that wrong
position, not of 1:1 geometry, and it goes with it (recorded below).
**The VBlank overrun is fixed** — the draw pass used to end 5724..7504 cycles
into a 4560-cycle window, so every level but the first wrote OAM, VRAM and
`rLCDC` in the visible frame; it now ends at 4120 on all eight, with no tear.
Composing moved to the visible frame and the handler keeps only the copies
(recorded below). **The whole front end has since been read off the screen by
eye**, which found three layouts whose lines sat on adjacent map rows and so
touched — the title's two prompts, the instructions screen, and the name-entry
panel. All three are re-spaced; the score screen's fix cost it two of its ten
entries (recorded below). `make verify` is 16 targets, 31 `RESULT` lines, all
green. Next: the remaining open decisions at the foot of this file.

**Published.** The repo is public at <https://github.com/Zapskii/GB-Chuckie-Egg>:
the port's own code and none of the game's data, the generated files being built
locally per the README. The README also carries the game's history, which is
where the premise belongs — *Chuckie Egg* is 1983 (1984 is the Pick & Choose
re-release), and **no Game Boy version was ever released**: no Nintendo platform
appears in its release records, and the only handheld builds are homebrew made
since. This is a fan port of the ZX Spectrum original, not a port of an existing
Game Boy one.

> **Legal:** Chuckie Egg is under copyright (Nigel Alderton / A&F Software). This
> repo ships none of its data — the ten generated `src/*.asm` files are built
> locally from the reference disassembly, per the README.

## Reference sources

Cloned read-only into `reference/`. Neither is a build base; they are reading
material. Do not treat `reference/` as project source.

| Repo | Local | Format | Use it for |
|---|---|---|---|
| `Paulie68000/ZXSpectrumChuckieEgg` | `reference/paulie` | SJAsmPlus Z80, builds a snap | **Logic.** Real routine names, comments, EQUates |
| `mrcook/chuckie-egg-disassembly` | `reference/mrcook` | SkoolKit-generated, WIP | **Data.** Text, graphics, level data, both tunes |

Take logic from `paulie` (hand-annotated, named) and art/tunes/level semantics
from `mrcook` (fully annotated data blocks). They are complementary; use both.

Primary file: `reference/paulie/Chuckie.asm` (7296 lines).

## Measured facts about the source

Read from `Chuckie.asm`. Line anchors are stable — re-grep if the refs update.

**Build / layout**
- `DEVICE ZXSPECTRUM48` (line 6) — this is the 48K version
- `org $61a8` main game, `$84f0`, `$9c9c` ISR, `$b200` level data (lines 61, 411, 2704, 6301)
- `LEVEL_WIDTH 32`, `LEVEL_HEIGHT 21` (lines 33–34)

**Tile set — small, this is the best news in the file**
- `TILE_BLANK $00`, `TILE_LADDERLEFT $01`, `TILE_LADDERRIGHT $02`, `TILE_EGG $03`,
  `TILE_BIRDSEED $04`, `TILE_PLATFORM $05`, `TILE_LAST $09` (lines 36–42)
- Plus a fixed cage decoration in the bottom-left 4×5 cells using raw tile ids
  `$a8–$b5` (~14 graphics), identical across levels
- **≈20 distinct 8×8 graphics total**, shared by all 8 levels

**Hen AI state machine — the equates hand you the whole FSM**
- `HEN_LEFT 1`, `HEN_RIGHT 2`, `HEN_DOWN 3`, `HEN_UP 4`, `HEN_PECKING 6` (lines 44–48)

**The mother duck** (`MoveMotherDuck` :3364, the plant at the end of it :3475)
- Runs on every `MotherDuckUpdateCounter` expiry (`$0C`, :2093) — in this port,
  one gameplay tick in twelve.
- **x branches on `BIT 7` of the velocity *before* comparing to the edge**; the
  carry out of `ADD A,vel` means "left the level" going right and "did *not*
  wrap below zero" going left. y has no sign test — a bound at each end, so
  `CP $A6` / `CP $14` on the value alone. Bounds `$EE` / `$14` / `$A6`; a
  reflection undoes the step (`SUB vel / SUB vel`) and sets vel to `$FB` or `$05`.
- Below level 8 the whole update is discarded and the position is re-stored as
  `LD HL,$9808` — x 8, y `$98`, the level's own units, so the 16×16 box sits on
  the cage's top two rows.
- The overlap test (:2545) is `duck_x-8 <= player_x <= duck_x+7` and
  `duck_y-9 <= player_y <= duck_y+9` — asymmetric on x, and lethal on every level.

**Dead code we get free**
- `DISABLE_SPEECH equ 1`, `DISABLE_MUSIC equ 1` (lines 56–57) — already set, so the
  Fuller Orator `OUT ($9F)` and the FP-calculator music path are already compiled out
- `DISABLE_COLLISION equ 0`, `ONLY_ONE_EGG equ 0` — debug switches, useful for testing

**Level data — lifts verbatim**
- `Level1:`–`Level8:` at lines 6352, 6375, 6398, 6421, 6444, 6467, 6490, 6513
- Each level = 8 rows × 32 `db` bytes, 1 byte per 8×8 cell
- Stored **upside-down**: data row 0 = screen row 21
- Sprites use Cartesian coords: **y=0 is the bottom**

**Spectrum ROM dependencies** (`reference/paulie/Spectrum.asm`, equates at
`Chuckie.asm` lines 15–24)
- `ROM_FP_CALC $0028` — only `RST` in the file (line 5445), music pitch timing
- `ROM_BEEP $03F8` — music playback
- `ROM_KSTATE $5C04` / `ROM_LASTK $5C08` — high-score keyboard entry
- `SCRNADDR $4000` / `ATTRADDR $5800` — Spectrum screen + colour attributes

## Porting hazards — the real cost

Counted by grep over `Chuckie.asm`. Approximate, but the shape is right.

| Hazard | Sites | Why | Fix |
|---|---|---|---|
| `(IX+d)` indexed | 88 | GB has no IX/IY | → `HL`+offset. **All in drawing routines** |
| `IXH`/`IXL` as scratch bytes | 30 | no index regs, no spare 8-bit reg | → HRAM vars |
| `IN A,($FE)` | 26 | no I/O ports on GB | → joypad read at `$FF00` |
| `SBC HL,rr` | 23 | **not on SM83** | → `ADD`-based borrow macro; mostly screen addressing |
| `OUT ($FE)` / `OUT ($9F)` | 9 | no I/O ports | drop (border / speech) |
| `RST ROM_FP_CALC` | 1 | no Spectrum ROM | own timer (already disabled) |

**Native on SM83 — no translation needed:** `DJNZ` ×74, rotates ×127, `LDIR` ×16,
`LD (HL),n` ×71, `ADD HL,rr`, `NEG` ×2, `DAA` ×1.

**Absent from the source entirely:** `IY`, `EXX`, `EX AF,AF'`, `CPIR`/`CPDR`,
`ADC HL,rr`, `INIR`/`OTIR`/`OTDR`.

**Note the shape of the table:** ~180 of the hazard sites sit in *graphics* code
that gets replaced, not translated. The game logic — jump physics, hen AI,
collision, eggs, scoring — is plain Z80 mapping ~1:1 to SM83. The real
translation burden is far smaller than 7296 lines.

**Subtle gotcha — preserve exactly:** the death routines unwind the call stack
with a **sequence of `POP`s** to return to the game-loop call site rather than
propagating flags. GB's stack behaves identically, so this ports, but **SP must
live in WRAM, not HRAM**, and that code must be translated literally.

## Strategy

Do **not** translate line-by-line. Split into three layers, treat each differently:

1. **Data** — levels, tile art, tunes → lift verbatim, re-encode to GB formats
2. **Logic** — physics, AI, collision, scoring → translate near-mechanically
3. **Platform** — drawing, input, sound, ISR → **rewrite GB-native, do not translate**

## Phases

Each phase ends in something runnable and **machine-checkable**. Never eyeball
what a script can assert.

- [x] **Phase 0 — Scaffold.** RGBDS `Makefile`; `src/`; `tools/shot.sh` wrapper over
      the PyBoy harness. ROM boots, LCD on, VRAM + palette set, main loop with
      VBlank wait, renders a test tile map.
      *Check: `make && make shot` produces a PNG.* — **done, verified below.**
- [x] **Phase 1 — Level renderer.** Lift ≈20 tiles → GB 2bpp; lift Level1–8 → byte
      tables; compositor maps level byte → BG map entry at `$9800`. Render 1:1
      first — 32 cells = 256 px = **exactly the GB BG map width**, zero conversion.
      *Check: screenshot all 8 levels; scripted cell-for-cell diff against the Z80 tables.*
      — **done, verified below.**
- [x] **Phase 2 — Decision point, with real pixels.** Having seen level 1 at 1:1,
      choose camera-scroll vs 4×4 demake vs level redesign. Default: 1:1 + camera
      (~10 lines), revisit only if it genuinely plays badly.
      — **decided: 1:1 + camera, implemented, verified below.**
- [x] **Phase 3 — Harry + movement physics.** Sprite data → 8×16 OAM; translate
      jump/fall/ladder/lift logic from `paulie`.
      *Check: hold right N frames, assert OAM X/Y advanced; assert `InAirCounter` /
      `PlayerJumpDirection` transition on jump.*
      — **done, verified below.** (Lifts are the one part carried into Phase 4.)
- [x] **Phase 4 — Hens + collision + lifts.** FSM from the `HEN_*` equates; the
      lift block carried over from Phase 3.
      *Check: headless run, assert the death path (stack unwind) fires, and that
      Harry rides a platform.*
      — **done, verified below.** (The two timers this bullet used to defer —
      the Z80's `FiftiesCounter`/`TensCounter`, `wBonus`/`wTime` — landed in 6a,
      which is the first phase that can show them.)
- [x] **Phase 4b — The mother duck.** Caged and harmless below the eighth level,
      chasing Harry and lethal on it. *Check: `tools/verify_duck.py`, passing on
      levels 1, 3 and 8.* — **done, verified below.**
- [x] **Phase 5 — Eggs, scoring, level flow.**
      *Check: collect N eggs, assert level advances.* — **`tools/verify_eggs.py`,
      passing on levels 1 and 5.** The level *timer* is deliberately still not
      built: its digits are read only by `AddToScore` at level completion and
      the `FF 09 09` sentinel only by the game-over path, so it belongs with
      Phase 6's HUD, which is the first thing that can show it.
- [x] **Phase 6a — HUD and the level timer.** Window band + STAT/LYC split for
      the status row; the two counters (`Bonus` drained into the score,
      `TimeRemaining` the clock). *Check: `tools/verify_hud.py`, passing on
      levels 1 and 3.* — **done, verified below.**
- [x] **Phase 6b — Sound.** Hand-rolled asm driver; the tunes re-encoded from
      the raw streams in `reference/paulie` (mrcook holds the same bytes, not a
      second representation). *Check: `tools/verify_music.py`.*
      — **done, verified below.**
- [x] **Phase 6c-1 — Lives, game over, the time-up rule.** The life byte and
      its HUD field, the decrement in the death path, replay while lives remain,
      and a new game at zero. *Check: `tools/verify_lives.py`.*
      — **done, verified below.**
- [x] **Phase 6c-2 — Title + press-start.** The text font out of
      `gfx_CharacterSet`, `TitleMusic`'s trigger, and the route back from game
      over. *Check: `tools/verify_title.py`.* — **done, verified below.**
- [x] **Phase 6c-3 — High score.** Table, sort, insert, name entry.
      *Check: `tools/verify_scores.py`.* — **done, verified below.**
- [x] **Phase 6c-4 — The extra life.** One life per 1 000 points, the Z80's
      `LastDigitValue` rule, and the re-sync that stops a level start paying.
      *Check: `tools/verify_lives.py` §8.* — **done, verified below.**
- [x] **Phase 6c-5 — The front end finished.** The name-entry cursor starts on
      `A` rather than on the cell holding the space, and the instructions screen
      is in off `SELECT` at the title — re-authored rather than ported, because
      the Z80's is Spectrum key documentation (a recorded divergence).
      *Check: `tools/verify_title.py` §7, `tools/verify_scores.py` §4.* —
      **done, verified below.**
- [x] **Phase 6c-6 — The high-score screen re-spaced.** The name-entry panel's
      lines were all on adjacent map rows, so the alphabet and the legend read
      as one garbled block; the panel's lines now step by two, which costs the
      table two of its ten entries. *Check: `tools/verify_scores.py`.* —
      **done, verified below.**
- [x] **Phase 7 — The announcements.** `ScrollTextLine`'s three call sites —
      "LEVEL n" as a level closes, "GAME OVER" on the last life, "OUT OF TIME !"
      on a death after the clock ran out — as one record-driven routine on a
      blanked map. *Check: `tools/verify_notice.py`.* — **done, verified below.**

**Ordering rationale:** the boring platform layer goes first because graphics is
the only real risk. If a GB cannot show the level readably, everything downstream
changes — so prove that in Phase 1 before writing a line of game logic.

## Progress

### Phase 4 — hens, collision, the death path, and the lifts

Hens walk, are lethal, and the level restarts after the freeze; the lifts carry
Harry. `tools/verify_hens.py` and `tools/verify_lifts.py` assert both, and
`make verify` runs the lot. All PASS.

**The Z80's lift table is 1-based levels 3–7, not 4–8.** `$9787`, eight records
of one x byte: `FF FF 64 90 C8 78 F0 FF`. Records 1 and 8 are empty, so the
platform levels are 3, 4, 5, 6, 7 and 1, 2, 8 have none. Read as "the byte is
`$FF`", the table needs no index arithmetic at all — the empty case falls out of
the data — so `wLiftX == $FF` *is* the no-lift level, which is also what the
verifier branches on.

Two platforms share each level's column, 64 px apart, and each wraps on its own
at `YPos >= $A6` back to `$A3`. That wrap is what keeps them exactly 64 apart
forever, and it is asserted rather than trusted (`(YPos1-YPos0) % 163 == 64`,
which holds through a wrap and would not if either one lagged).

**Where the platform is drawn is derived from Harry, not from the Spectrum's
screen address.** Harry's OAM row is `OAM_ROW_BASE-y-SCY` and his sprite is 16
tall, so his feet are at `OAM_ROW_BASE-y-SCY+15`; standing on a platform
`y = YPos+17`, so the deck's top row must be `OAM_ROW_BASE-2-YPos-SCY`.
`LIFT_ROW_BASE` shipped as **158** for one commit — a straight arithmetic slip,
and the kind that looks plausible in a constant. What caught it is that
`verify_lifts.py` pins the platform's drawn row to **Harry's own OAM row + 15**
rather than to a row number written in the test: a hand-derived constant in the
test would have been wrong in the same direction and agreed with the bug. A
second platform is `YPos1-YPos0` rows above that, which the test derives from
the platforms' own positions.

**That lesson was then forgotten by 6a, which broke the same coupling the other
way — see the note at the end of the 6a section.** `LIFT_ROW_BASE` is now
`OAM_ROW_BASE - 2` and `OAM_ROW_BASE` is `PLAYFIELD_ROW_BASE + 16`, so the three
numbers can only move together.

**`PlayerOnLift` is cleared only by a jump.** The Z80 leaves it set when he
walks off the end, and the step-off countdown runs on top of it; the port
reproduces that instead of tidying it, because the tidy version changes what
`CheckForFalling` is allowed to do while the flag is up.

**The main loop no longer runs its tick inside VBlank, and that was a real bug,
not a tidy-up.** It was `halt` → whole gameplay tick, so the tick began
immediately after the interrupt and straddled the 70224-cycle frame boundary an
emulator steps on. A state written between two `pb.tick()` calls therefore
landed *part way through* the tick, and the frame that should have acted on it
had already run — which looks exactly like a landing test that never fires, and
moves around when the ROM's size or timing changes. `MainLoop` now waits out
VBlank (`rLY` in 40..143) before doing anything, so the tick sits entirely
inside one visible frame. Cost: nothing. It fixes all four PyBoy verifiers at
once, which is why it went in the ROM and not into four retry loops.

Timing is the Z80's, still not rescaled: a hen steps once per `HEN_SPEED *
HEN_MAX` frames via a round-robin counter, and the platforms rise 1 px per
`LIFT_SPEED = 2` ticks — both asserted by counting steps over a window rather
than by checking that something moved.

**The camera, judged against the hens now that there is something to hide.**
Level 1 spawns its two hens at x=104 and x=72 while the camera sits at SCX=96,
so the second one starts **behind** Harry, at the left edge of a window that
begins at x=96. Over 600 idle frames at spawn it is on screen 5% of the time
against 72% for the first. That is not a crop any more, it is an
information asymmetry: an enemy the level placed in view is now something that
walks in from off-screen, and the player cannot see the two of them at once
long enough to read the gap between them. 160 of 256 px is visible at any
moment — 62.5% — and the hidden 96 px moves with Harry rather than sitting at
one end, so it is not learnable as "the left third is off-limits".

**Judged, and 1:1 kept.** The numbers were put to the user and the demake
rejected: the level keeps its original geometry, the camera keeps sliding, and
the hen-spawn cost is accepted rather than fixed — moving a spawn is the first
change that would break the level data's byte-exactness, and that verification
is worth more than one hen's starting position. Revisit only if it plays badly
in mGBA; the fix is one byte per level, not a rescale.

**The cost has since gone, and it was never a hen's spawn (2026-10-03).** Every
number above is measured at the spawn the port *had*, which was not the game's
(see "Harry's spawn" below): SCX=96 was the right-hand clamp at x=$AE. At the
real spawn — PlayLevel's $64/$17, x=100 — the camera sits at SCX=28 and both
hens are in view from the first frame. The 1:1 decision and the hen data are
untouched; the asymmetry was a property of the wrong starting position, which is
why no carve-out in `verify_hens.py` was ever needed.

### Phase 4b — the mother duck (done 2026-10-02)

The big bird in the cage. Below the ninth level it is planted at `$9808` on
every update and never moves (`CP $08` on the 0-based counter, `:3462`); from the
ninth, `MoveMotherDuck` (`Chuckie.asm:3364`) chases Harry on both axes, and its
overlap test (`:2545`) kills him. So it is caged and harmless on all **eight**
levels the ROM boots into, and the free/loose boundary is level 9 — one level
later than the port first had it (see "The five laps" below). `src/duck.asm` is
the art; `tools/verify_duck.py` asserts all of it, on levels 1, 3 and the 8/9
pair.

**The anchor is Harry's, not the hen's** — `PlayerY` is the TOP of the 16×16
box, a hen's y is her FEET. The Z80 draws the duck through the same
`DrawSpriteNum` as Harry, so the duck takes `OAM_ROW_BASE - y - SCY` unchanged
and only the hens keep `HEN_OAM_ROW_BASE`. (Reading it as a hen's would sink it
15 px into the cage floor.)

**The Z80's x path branches on the velocity's SIGN before it looks at the edge**,
and that is not a detail: `ADD A,vel`'s carry means opposite things the two ways
round. Going right, carry = "left the level"; going left the velocity is
`$FB..$FF`, so carry = "the step did *not* wrap below zero", i.e. it was fine.
The port read the carry as "would have left the level" both ways, which turned a
leftward duck round on **every** update, threw it `2*vel` the wrong way and
pinned its velocity to +5. The y path has no sign test at all — it has a bound at
each end, so the value says which edge was reached. `verify_duck.py` §5 caught
this as "reached (153,190), outside MoveMotherDuck's bounds"; it is the first
thing the port's duck does wrong on level 8.

**The death window is asymmetric on x** (`duck_x-8 <= player_x <= duck_x+7`,
`duck_y±9`), so in the duck's own terms it is x −7..+8 and y ±9 — nine cases are
walked over all four edges in §4, one pixel at a time.

**Four OAM entries, and the duck needs the *fourth* past the lifts.** Each
platform is two 8×8 halves, so the lifts own `LIFT_OAM..+3`; the duck was placed
at `+2` and shared 26/27 with the second platform, which `DrawLifts` writes every
frame — on the five lift levels the bird drew as its bottom half only.
Invisible on level 1, which has no lifts and is where it was last looked at;
level 3 is in the `verify-duck` rule for exactly this. (`DrawLifts.hide`'s old
two-writes-per-entry loop had masked the same overlap on the non-lift levels by
accident.)

**The band has to hide sprites too — the duck exposed it.** OBJ is drawn over
the window on this hardware, and the caged duck's box reaches screen rows −9..6
at `SCY 32`, which is the camera at *every* level's spawn; it was painting seven
rows of bird over the status row. `HandleStat` now drops `LCDCF_OBJON` at
`HUD_SPLIT_LY` (gated on `LCDCF_WINON`, so the front end's all-BG screens keep
their sprites off) and VBlank restores it with `LCDCF_WINON`: the band covers
lines 0–7 for the BG *and* for everything drawn on top of it. `verify_hud.py`'s
"band rows 0–7 identical" section is what found it.

**The wing flap is in, and it costs no tiles.** The Z80 toggles `MotherDuckFrame`
(`XOR $01`, `Chuckie.asm:3481`) inside the *draw* path on the same counter as the
movement, so the duck flaps on every level — the caged one included. The port
toggles `wDuckFrame` in `UpdateDuck` immediately after the tick reload and
**before** the plant's own gate, so the caged duck flaps too; only the movement
below that gate is the loose duck's.

The source's poses are 8 (wings down) and 9 (wings up), both right-facing, with
10 and 11 their pixel-exact 16-wide mirrors. `gbdata.duck_frames` already
*asserted* that mirror, so the port emits 8 and 9 and draws the left facing as
**OAM attribute bit 5 ($20 — X-flip, so attr $30 = OBP1|flip) with the two
columns swapped**: flipped, the tile at column `d` is the frame's top-right one
and `d+8` its top-left, which is exactly the source's frame 10. That is 2 frames
× 4 tiles, the same 8 tiles the old two-facing version emitted, so VRAM is
unchanged at 254/256 (255/256 since the score panel was re-spaced);
emitting 8/9/10/11 would have cost four more.

**The facing is on the duck's clock too, not the frame's (2026-10-03).** The
Z80 decides which way the duck faces inside `MoveMotherDuck` itself — `LD
A,(PlayerX) / CP (IX+$70)` at `:3471-3476` — and only ever draws it from there,
so the turn is one of the duck's own steps. The port read `wPlayerX` in
`DrawDuck`, i.e. on *every drawn frame*, while the duck's x is frozen for
`DUCK_SPEED` of them: walking Harry past a stationary duck turned it on a frame
that was not one of its steps, so the bird moved twice per beat — once for the
wing and once for the turn. That is the jitter. The facing is now computed in
`UpdateDuck`'s `.face` arm, after the plant (so a caged duck faces whichever way
Harry last stood), and `DrawDuck` only reads it. Position, pose and facing all
change together, once per `DUCK_SPEED`, as the Z80's do.

**Verification.** `tools/verify_duck.py`: the four OAM entries and both facings
(against the art located by *pixels* in VRAM); the pose, read from `wDuckFrame`
and drawn as the swapped-column tiles above; the pixels themselves, read off the
screen and compared to the source art — the duck's ink is one shade and every
pixel its art leaves blank is *exactly* the background, which is read from a
second frame with the duck moved off the top of the screen, so no palette
constant is recomputed; the plant, by watching the duck not move for ten real
`DUCK_SPEED` updates; the death window; and level 8's roam — rate, bounds and
facing. Section 1 asks for a turn by forcing one duck update with `wDuckTick=1`
rather than poking Harry and ticking a frame, which only ever reached the turn
while it was read on the draw. Section 3b is the jitter itself: Harry is walked
to the duck's other side and left there, and the four tiles *and* the flip bit
must change on exactly one frame in a `DUCK_SPEED` window — `beat: bird changed
on frame 12 of 12`. Section 6 stopped asserting the facing against Harry's x on
every frame, which is the bug, and asserts what the update settled on and that
it is held until the next one.

It was falsified three times before it was kept: originally against a duck drawn
a tile over (tile base +1, top-right quadrant in the top-left's column); for the
flap against a killed toggle (`xor $00`) and against forcing the right branch on
a left-facing duck — 7 failures, including the pixel-level one; and for the
facing clock by putting the old `wPlayerX` read back at the head of `DrawDuck`
— section 3b then reports `bird changed on frame 1 of 12`, the second step per
beat.

**Seen by eye in mGBA (2026-10-03).** The thing no check can hold: the flap
reads as a wing beat, and it is in step with the duck's motion on the caged duck
and on level 8's.

### The five laps, and three off-by-ones that went with them (2026-10-03)

Asked for first as "can I jump straight into level 9" and then as the shape of a
full run: **1–8 birds only, 9–16 duck only, 17–24 both, 25–32 both with all five
birds, 33–40 the same but faster, and 41+ identical to 33–40.** That is exactly
what the Z80 does, and it is *not* a lap counter: the original's `CurrentLevel`
is unbounded (`INC (HL)`, `Chuckie.asm:4434`) and every rule that changes across
a run is a **threshold on it**. The eight maps repeat because each per-level
table lookup masks with `AND $07`; the rules read the counter itself.

| the rule | the Z80 | threshold |
|---|---|---|
| the duck's cage | `CP $08`, `:3462` | caged below 8; loose from level 9 |
| the hens | `CP $08`/`CP $10`, `:633-641` | gone levels 9–16, back at 17 |
| how many | `CP $18` → `B=$14`, `:5968-5978` | all five from level 25 |
| their speed | `CP $20` → `DEC C`, `:2135-2145` | 3 → 2 from level 33 |
| the bonus | `INC A`/`CP $0A`, `:5864-5872` | `min(counter + 1, 9)` |
| starting time | `SRL` ×4/`CP $05`, `:5874-5886` | `9 − min(counter >> 4, 5)`, floor 4 from level 81 |
| the egg's score | `SRL` ×2/`CP $09`, `:2246-2256` | `10 × (min(counter >> 2, 9) + 1)`, 100 from level 37 |

**Nothing is compared above `$20`**, so level 41 is level 33 and only the two
multipliers keep stepping — arithmetic, not a sixth lap. The last two rows were
already implemented in the port; they were simply unreachable while the counter
wrapped at eight, so most of this change is un-masking the counter plus three
comparisons.

**What changed.** `NextLevel` no longer masks the counter (`inc a / and 7` is
gone); `GetLevelEntry`'s `AND $07` is now the **only** wrap left in the port, and
`ResetLifts` keeps its own copy of it. `DUCK_LAST_LEVEL 7` became
`DUCK_FREE_FROM 8` — the source's operand, not the level number. `HenSpeed` is
new: `HEN_SPEED`, one less from counter 32, and `UpdateHens` reloads through it.

**Three off-by-ones, all the same misreading, all now fixed.** The Z80's counter
is 0-based; the port had read it as 1-based at three sites. None was visible over
eight levels — one was wrong by one, and the other two were unreachable:

| | original | the port had | now |
|---|---|---|---|
| duck loose from | level 9 | level 8 (`DUCK_LAST_LEVEL 7`) | level 9 (`DUCK_FREE_FROM 8`) |
| level 1 bonus | 100 | 200 (`min(wCurrentLevel + 2, 9)`) | 100 (`+ 1`) |
| clock's first step down | level 17 | level 16 (`inc a` before `swap a`) | level 17 |

The evidence that the counter is 0-based is the label itself — `6EEB: Current
level - 1` in ritchie333's memory map, `cleared_levels` `defb $00` in mrcook's —
and paulie's own image, where `P2Level: db $00` sits beside `P2Lives: db $05`,
i.e. 0 is a fresh player's level.

**The `CP $18` gate is not a count, it is a size.** From level 25 the Z80
overwrites the level's own hen count with `$14` — *20 bytes*, i.e. all five
slots — so those levels run every record the table holds, the ones the level's
count leaves idle included. The port's `HenStarts` was zero-padding those spare
slots, which would have spawned hens at (0, 0) the moment the lap was enabled.
`gbdata.py` now emits the source's own five records for every level and asserts
all five are real ones (x a multiple of 4, direction in range) — the same
assertions the four live records always had.

**The level's number is two cells.** The Z80 builds it with its own
subtract-and-`DAA` loop (`:4431-4460`): `CP $C8` then `CP $64`, then repeated
subtraction of ten — and the tens digit is left **blank**, not zero, when it
comes out zero. So the display wraps at a hundred but does not gain a leading
zero with it: **level 100 reads `LEVEL  0`, not `LEVEL 00`.** The announcement
record carries two markers (`NOTICE_TENS`, `NOTICE_DIGIT`) rather than one, and
`SetLevelDigits` fills them when the word goes up.

**The HUD still has no level field.** The status row is twenty columns and
exactly full — `S00000 E12 T900 L05` — so the level's number appears only in
that announcement. On the Spectrum it is scrolled into the playfield; this is a
recorded divergence and it stays.

**The checks.** `tools/verify_laps.py` is new and is the feature's own: one ROM,
thirteen poked counters, and each row asserted against the table above —
including the pair either side of every threshold, the hen count read on two
counters that **share a map** (16 and 24 are both map 0, so the jump from the
table's own 2 to 5 is the gate and not the level data), level 41 pinned equal to
level 33's whole state, and the speed measured as a *rate* (50 beats of
`wHenTick` in 150 frames at 3, 75 at 2) rather than read off a reload value. It
was falsified against a build with the speed gate moved one level late: three
assertions fail. The level-completion path drives the reload rather than a death,
because `wLevelDone` clearing is `LoadLevel`'s last act — reading on the frame it
clears on still holds the values `ResetHens` and `ResetTimer` left, where a
death's reload spans a frame boundary and a poke into it can be read stale.

Around it: `verify-duck` now runs the **l8/l9 pair**, which is the cage's own
boundary (`l8` caged, `l9` chasing) and would have passed vacuously before, since
level 8 used to be the loose one. `verify-eggs` gains level 37 for the 100-an-egg
clamp. `verify-notice` gains "the number is two cells, and it wraps at a
hundred": level 12 and level 100 poked straight in, which is where the
blank-tens rule is checked — falsified by making the tens digit unconditional,
which spells `LEVEL 02` for level 2 as well as `LEVEL 00` for level 100.
`verify_hud`'s `bonus0`, `time0` and `wCurrentLevel` expectations carried the
same two off-by-ones as the ROM and moved with them.

### The 10-sprites-a-line limit, measured, and the guard (2026-10-02)

**The hardware rule.** The DMG shows only the **first ten OAM entries on a line,
in OAM order** (PyBoy enforces it at `pyboy/core/lcd.py`, `if sprite_count ==
10: break`, walking OAM from `$FE00` and never looking at x). A 16×16 sprite
costs **two entries a line whichever OBJ mode is in use** — in 8×8 mode the left
and right halves of one row band — so `LCDCF_OBJ16` halves the *total* entry
count (40, of which the port uses 32), never the per-line one. **There is no
structural fix for the flicker.** The only choice is who is dropped, and that
choice is OAM order: **Harry 0–3, the hens 4–23, the lifts 24–27, the duck
28–31** (`src/main.asm:120,182`).

**Measured, not assumed.** Idle, scripted and 6000-frame randomised runs of all
eight levels peak at **8 of the 10**. The worst case is forced: Harry (2) plus
four hens (2 each) is exactly 10 and drops nothing — and four hens is the most
any *one of the eight* spawns — but add the caged duck and the line wants 12 and
the two that go are the duck's own top halves, slots 28 and 29. Level 8, the only
level whose duck is lethal, has three hens and so peaks at 8.

**Level 25 breaks the comfortable version of that (2026-10-03, and the level was
play-tested the same day).** From counter 24 the hen table's own five records all
run (`CP $18` is a size: `$14` = 20 bytes = every slot — see "The five laps"), so
the ceiling is reachable with no decoration on the line at all: **Harry plus five
hens is 12 entries and the bird that goes is the fifth**, slots 20 and 21. That is
still the right casualty — the order is Harry, the hens in record order, the lifts,
the duck, so the last thing drawn is the first to go — but the earlier claim that
the casualties are only ever the decoration is true of the eight boot levels and
not of the laps above them. Nothing in the draw path could be changed to help it:
six 16×16 sprites cannot fit ten entries.

**Two things in the check had to move with it.** It parked Harry at a fixed
corner (x=72, the camera's own clamp) — which on level 25 is inside a hen's spawn,
so he died on the way in and the whole scene was rebuilt on a level that had
already reloaded, reported as "could not put hen N on Harry's row". It now parks
where the **game** parks him (NewGame's spawn, read back out of the ROM), which is
safe on every level by construction. And the drop is now asserted as a **rule with
a per-level answer** rather than one fixed expectation: nothing at or before the
last hen drawn may go, three or four hens see no hen dropped at all, and five hens
lose exactly the last one's two entries. Level 8 is in the set for the case where
the duck *fits* — three hens plus the duck is exactly ten — so a check that
demanded a drop there would be asserting the wrong thing.

**The decision: guard, don't rotate.** Because the port's slot order is already
the right priority, nothing in the draw path changed; `tools/verify_sprites.py`
pins the order as a contract instead of leaving it a comment. It encodes the
hardware rule directly, reports the worst natural line per level, rebuilds the
pile-up by sliding every live hen and then the duck onto Harry's own drawn row
(reading each row back and applying the difference, never recomputing the
transform), and asserts **who is allowed to be dropped, which depends on the
level**. Falsified twice: by giving level 5 a fifth hen, and by reversing the hen
draw order in `DrawHens` (`ld a, HEN_MAX-1 / sub b`) — the reversed build fails on
level 25, which is the level where the hens are the casualty at all.

**Found while falsifying, pre-existing, and since fixed (2026-10-02).** The
VBlank draw pass **overran the frame boundary**: measured per level, it ended
5724..7504 cycles after VBlank entry against a 4560-cycle window, so on every
level but the first the last writes landed in the visible frame. On level 3 that
showed as a 1 px split across the second platform's two halves in 131 of 300
frames, identically at HEAD before the flap. `verify_lifts.py`'s two-tick read
was passing on where the boundary happened to fall; it read one frame the
platforms had not moved on.

**PyBoy does not model the blocking**, so what the checks saw was the tick
boundary landing mid-routine. On hardware the late writes are mode 2/3 and
simply dropped — the OAM entry lost, and with it the handler's `rLCDC` write
(OBJ off, WIN on for the status band), so the band's setup was unreliable on the
real thing. The handler's cost was not overhead to shave: the per-sprite work —
the camera transform, the pose, four bytes an entry — is 7500 cycles of
translation, and no 4560-cycle window holds it.

**The fix: compose in the visible frame, copy in VBlank.** `DrawFrame` (camera,
Harry, hens, duck, lifts, HUD row) runs from `MainLoop` after the tick, where the
65 000-odd non-VBlank cycles are free; the handler keeps only the writes.
`wOamShadow` holds the OAM image and `BlitOam` copies it flat — unrolled, because
at 24 cycles a byte even a loop's own counter would spend a third of the window
on overhead; `ShowHud` does the same for the 20-byte status row, replacing
`MemCopy`'s 52 cycles a byte. The camera is split in two for the same reason:
`UpdateCamera` computes into `wScrollX`/`wScrollY` in the visible frame and
`CommitCamera` writes `rSCX`/`rSCY` in VBlank, both halves always in one frame.

Measured after: **4120 cycles on every level, 440 inside the window, and no tear
on any of the eight** (300 frames each). `verify_lifts.py` reads a single frame
again, and picks the one the platforms *moved* on — the frame a tear would show
on.

### Phase 5 — eggs, scoring, level flow (done 2026-10-02)

**The source anchors, read before any of it was written.** They all held.

- **`PlayerPickUp` (line 2233) samples exactly one map cell: `(x+8, y-8)`.** It
  loads `HL,(PlayerX)`, which is little-endian over the adjacent `PlayerX`/
  `PlayerY`, so L=x and H=y — then `SUB 8` on H and `ADD 8` on L. One cell, not
  a box. `verify_eggs.py` asserts exactly that: an egg one column away is
  untouched.

**The find of the phase, and it would have bitten a real DMG:** the reload's
"wait for `rLY == 144`, then switch the LCD off" loop never completed on levels
3–7. VBlank is serviced the instant `rLY` reaches 144, and the handler does not
return until `rLY` has moved past it — so with interrupts enabled the loop only
ever wins the race by luck, and the levels whose handler is slowest (the ones
with lifts, because `DrawLifts` runs there) never win it at all. The ROM hung
with the screen on and the level half-loaded. It is now `di` across the reload,
which takes the preemption out of the picture entirely; `rLY` freezes with the
LCD off, so nothing in there may `halt`. Level 1 and 2 hid it for hours.

Two smaller ones, both from doing things the Z80 way:

- **`PlayerPickUp` on the last egg abandons the rest of the tick** (the Z80's
  `POP HL / RET` unwind). In this port that is a flag — `wLevelDone` — checked
  at the top of the next iteration, not a return out of a call. Same shape as
  `DecreaseTimerOrBonus` will need.
- **The level-advance reload runs across a frame boundary** (it writes 1700-odd
  bytes; `LoadLevel` waits for VBlank, blanks the screen, then takes as long as
  it takes). A frame-stepping reader therefore sees it half-done, so
  `wLevelDone` is cleared at the *end* of the load and is the completion signal
  — the same ordering the death path needed in Phase 4.

**Address tables over runtime multiplication** for the non-power-of-two strides
(672 for a level, 21 for a hen record): that multiply happens once, in the
assembler, and `GetLevelEntry` indexes both tables with `wCurrentLevel`.

- **Egg (`TILE_EGG` = `$03`)**: cell → `TILE_BLANK`, `EggsRemaining--`, and
  score `10 * (min(CurrentLevel>>2, 9) + 1)` (the `CalcLp` loop is `x*10` via
  `DJNZ`; the `CP $09 / JR C` is the clamp). At zero the Z80 does `POP HL /
  RET` — the **stack unwind**, the same shape as `DecreaseTimerOrBonus`:
  abandon the rest of the main-loop iteration. In this port that is a flag,
  `wLevelDone`, read at the top of the next iteration.
- **Score is 6 bytes, one decimal digit per byte, units at `wScore+4`** (the
  Z80's `CurrentPlayerScore` layout). `AddToScore` adds by counting in base ten
  with carry, so the digits stay packed for the HUD to read out in Phase 6.
- **Corn (`TILE_BIRDSEED` = `$04`)**: cell → blank, `+5`, and `LD HL,$FFFF /
  LD (FiftiesCounter),HL` pokes `$FF` into both timer counters. Still not
  decoded — read `FiftiesCounter`/`TensCounter`'s real addresses before writing
  it, since the reset code at 6131 addresses them IX-relative.
- **`EggsRemaining` is a constant 12**, not counted from the map (line 4484,
  `LD A,$0C`, or `$01` under `ONLY_ONE_EGG`). No egg census needed.
- **Levels are 672 bytes (`LEVEL_SIZE = $02A0`) and cycle on `CurrentLevel & 7`**
  (line 4471), so level flow is index arithmetic, not a table.
- **Level selection was assemble-time; it is runtime now.** `-DLEVEL_NUM` picks
  what the ROM boots into and `wCurrentLevel` owns it from there (`NextLevel` is
  the Z80's `AND $07` cycle). The death path already restarted the level
  (Phase 4a), so level flow routes through that same reload rather than
  growing a second one — `NextLevel.reload` is the shared entry point.
- **The counters have no screen until Phase 6.** Eggs clear visibly (they are BG
  tiles) but eggs-remaining and score are WRAM-only, asserted headlessly.

Two more root causes, both found by the new check and both latent before it:

- **`ClearCell` — a hen eating corn blanked the level buffer but never the BG
  map.** The buffer is the game's copy, the map is what is on screen, so corn a
  hen ate stayed visible. Both the hen's corn and the player's pickup now go
  through one routine that blanks the buffer cell and queues the BG map write
  (`wPickupAddr`/`wPickupDo`, consumed by the VBlank handler — the tick itself
  runs with the LCD on and cannot write VRAM).
- **`ResetScore` had to be split out of `ResetEggs`.** The Z80 zeroes the score
  once, in `NewGame`, and level completion *adds* to it; zeroing it on every
  level load threw it away at each level change.

### Phase 6a — HUD and the level timer (done 2026-10-02)

The status band and the two counters, in one commit. `make verify` is 16 checks
green (`tools/verify_hud.py` runs on levels 1 and 3).

**Two of the pre-flight's own assumptions were wrong, and the corrections change
the design.** Both are now read off the code rather than the comments:

- **There are two counters, not one.** The pre-flight wrote "its digits are read
  only by `AddToScore` at level completion (the time bonus), and the `FF 09 09`
  sentinel only by the game-over path" as if that were one array. It is two:
  `Bonus` (`+$67`–`+$69`) is drained into the score at level completion, and
  `TimeRemaining` (`+$6A`–`+$6C`) is a clock that is never scored at all — the
  sentinel is *its* underflow residue. They decay at different rates and only
  one of them can kill you.
- **The unwind is only on the time underflow.**
  `DecreaseTimerOrBonus` abandons the rest of the iteration via `POP HL / RET`
  when `TimeRemaining` borrows out (`B=1`); the `Bonus` underflow (`B=0`)
  returns normally and only clears `TimerRunning`.
- **Corn pokes the *dividers*, not the counters.** `LD HL,$FFFF / LD
  (FiftiesCounter),HL` sets both divider bytes to `$FF`, delaying each counter's
  next step by 255 ticks, and awards +5. It does not touch the countdown values.
- **Two comments in the source are swapped.** `FiftiesCounter` is the *Bonus*
  divider and `TensCounter` the *Time* divider, the opposite of what the
  comments at the `DecreaseTimerOrBonus` call sites say. Follow the code:
  `B=$00` takes `HL = Bonus+2`, `B=$01` takes `HL = TimeRemaining+2`.
- **Start values have the off-by-one that mattered.** `CurrentLevel` is 1-based
  where `wCurrentLevel` is 0-based, so `Bonus = min(CurrentLevel + 1, 9)` is
  `min(wCurrentLevel + 2, 9)` — level 1 opens at **200**, not 100. `TimeRemaining
  = 9 - min(CurrentLevel >> 4, 5)`, i.e. **900** on every level, and the `>>4`
  clamp can never fire over eight levels (kept because it is the source's).
- **Cadence**: `TimeRemaining` steps every **10** gameplay ticks and `Bonus`
  every **50**. Both dividers start at **1**, not at their reload value, so the
  first step lands on the level's first tick — 60 frames gives exactly 6 time
  steps and 100 frames exactly 2 bonus steps, which is how `verify_hud.py`
  counts them.

**The band.** A 1-row (8 px) window band across the top, plus a STAT/LYC raster
split. `rWY=0`, `rWX=7` (window's left edge at screen x=0), `rLYC=8`,
`rSTAT=%01000000`, and `LCDCF_WINON` in `rLCDC`; the STAT handler clears that bit
and VBlank sets it back. `rIE` gains `IEF_STAT`. Both band registers are written
once in `Start` **with the LCD off**, which is also what avoids the DMG's
spurious-STAT-interrupt-on-write bug. The window uses BG map 1 (`$9C00`), so the
band needs no room in the level's own map — only the displacement below.

**Consequences, all of them paid for:**
- **The playfield moves one map row down.** `DrawLevel` writes `_SCRN0 + 21*32`
  and `ClearCell`'s `BG_LAST_ROW` is 672, so buffer row 0 is map row 21. Both are
  written as `HUD_ROWS * 32 + …`, so the displacement is one number.
- **The camera's upper clamp goes 24 → 32** (`SCY = clamp(96 - y, 0, 32)`). At
  `SCY=32` the floor row sits at screen rows 136–143 — byte-identical to what
  `SCY=24` gave before, so the bottom framing is unchanged; the camera just pins
  to the bottom from `y=64` instead of 72, because the band eats 8 px of view.
- **`verify.py` and `verify_camera.py` encode the old geometry and moved with
  it**; `verify_eggs.py`'s level-completion score now adds the drained bonus.
- **The list of checks that "need no change" was wrong, and it was wrong in the
  same direction as the bug.** This section originally claimed `verify_player.py`
  and `verify_hens.py` "read `SCY` live as `183 - y - SCY` and need no change" —
  but 183 is exactly the number 6a invalidated. They were updated with the ROM;
  the sprite transform is `OAM_ROW_BASE - y - SCY` and the bases are chained in
  `src/main.asm`. Treat any "needs no change" claim about a derived constant as
  a hypothesis to check, not a fact.

**The write path.** `BuildHud` writes 20 tile indices into `wHudRow`; the VBlank
handler copies all 20 into `$9C00`. Rebuild every frame, copy every VBlank — a
dirty flag would buy back ~150 of a 4560-cycle VBlank in exchange for
bookkeeping at six call sites. `LoadLevel` builds the row and copies it directly
(the LCD is off there). The copy is `ShowHud` since the 2026-10-02 VBlank fix:
flat and unrolled, the same shape as `BlitOam` beside it, because `MemCopy`'s
loop cost 52 cycles a byte against 24 for the three unrolled ones.

**The font.** `gbdata.py`'s `asm_font` emits `src/font.asm`: 14 tiles
(`0`–`9 B E S T`) from `gfx_CharacterSet`, at shade 3, at
`HUD_TILE_BASE = LIFT_TILE_BASE + 2` = **102**. The charset is indexed by ASCII
code directly — confirmed three ways (`PrintCharacter` computing `BC = code*8`
into `gfx_CharacterSet`; the score path reading `gfx_CharacterSetNumbers` at code
48; and codes 48–57/66/69/83/84 rendering as exactly `0`–`9BEST`). Codes 48–57
*are* `gfx_CharacterSetNumbers`, so the score gets the original's own digit font
for free. `verify_hud.py` finds the run in VRAM **by its pixels**, re-encoding
the reference charset at the same shade, so a tile-order or shade drift fails
rather than looking plausible. 116 of 256 tiles now in use.

**The layout**, 20 columns, exactly full — score is five digits because
`AddToScore` carries down from `wScore+4` and provably never touches `wScore+5`:

```
    col 01234567890123456789
        S00000 E12 T899 B199
```

**The root cause the check found — interrupt handlers must save the registers
they touch.** The VBlank and STAT handlers ran with no `push`/`pop`. That is
invisible while the main line only ever idles in `halt` at the start of the
frame, and it is *not* invisible once a main-line routine runs across a frame
boundary: `DrainBonus` iterates ~600 times at level completion, gets interrupted
mid-loop, and resumes with A/BC/DE/HL holding whatever the handler left there.
The symptom was a score digit of `106` — a byte holding the *score's own digit
value* — in `verify_eggs.py` on level 5, and it read as an arithmetic bug in
`AddToScore` for a while. Both handlers now save and restore; the STAT one only
needs `af`, and it touches nothing VBlank does, so they cannot race each other's
state.

Two smaller things the check had to work around, both worth knowing before
reading a verifier's output as a ROM bug:

- **Reads land in a frame, not between frames.** The tick runs in the visible
  part of the frame, after the VBlank that built the row from the counters — so
  a tick that steps a counter leaves WRAM a step ahead of both `wHudRow` and the
  map. That is a one-frame display lag, not a wrong row; the check reads in a
  quiet frame (dividers frozen) rather than chasing it.
- **The reload parks MainLoop for a frame.** It resumes through `halt` at the
  next VBlank and then waits out the rest of that frame, so the tick does not
  run again until the frame after the one the reload returned on. A poke between
  the two lands in a frame where nothing runs — which is what made the corn case
  look like a pickup bug.
- **A verifier that lets Harry fall measures the level, not the ROM.** Level 3
  has corn, and he lands on it: the pickup pokes both dividers and the cadence
  count is out by a whole step. The check now parks him on a cell read out of the
  level buffer, so it is empty on any level.

**And the bug 6a actually shipped: every sprite 8 px above the tiles.** Found by
play-testing, not by a check — `make verify` was 17 green with it in. The band
displaces the playfield down the map by `HUD_ROWS*8` and grows `SCY`'s clamp by
the same 8, which moves everything drawn from `SCY` by −8 (up the screen) *except*
the background, which moved by +8 (down the map): the two cancel, so the
playfield's screen position is unchanged and every sprite is 8 px high. The
sprite transform's constant `183` was the value that cancelled the *old*
geometry and was left alone. 191 is the new one.

The numbers, measured off the framebuffer rather than derived:

| | sprite box | tile he stands on | |
|---|---|---|---|
| pre-6a | rows 88..103 | top edge 104 | feet on the platform |
| post-6a | rows 80..95 | top edge 104 | floating, and the green ruler line ran through the middle of an egg |

Everything is now expressed as a chain instead of three literals, which is the
actual fix — the constants that must move together are one edit apart now:

```
PLAYFIELD_ROW_BASE = 167 + HUD_ROWS * 8     ; level pixel p is drawn on
                                            ; PLAYFIELD_ROW_BASE - p - SCY
OAM_ROW_BASE       = PLAYFIELD_ROW_BASE+16  ; a sprite's OAM row Y draws at
                                            ; lines Y-16..Y-1
HEN_OAM_ROW_BASE   = OAM_ROW_BASE - 15      ; a hen's y is its FEET, not its
                                            ; top -- see the hen anchor below
LIFT_ROW_BASE      = OAM_ROW_BASE - 2
```

Two things made this invisible for so long, and both are worth remembering:

- **The `-16` matters only when you look at the hardware, not at the ROM.** An
  OAM row is *not* a screen line: the DMG draws a sprite whose OAM row is Y at
  lines `Y-16 .. Y-1`. That is why the sprite constant is the playfield's *plus*
  16 and why a measurement that reads OAM and compares it to a derived formula
  agrees with itself no matter how wrong both are.
- **`verify_player.py` and `verify_hens.py` recomputed `183` by hand.** A check
  that recomputes the ROM's arithmetic tests the arithmetic; it cannot see the
  screen. `verify_player.py` section 11 now asserts the property a player
  notices, with **no constant at all**: a standing player's sprite ends at
  `OAM-1`, so the tile under him must have its top edge at exactly his OAM row.
  Falsified against the broken constant before it was kept — it reports `his
  feet are at OAM row 96 but the tile under him starts at row 104`.

**The column had the same offset missing, and it had been missing since Phase
1.** Play-testing found it in the same sitting: on a two-cell ladder Harry hung
off the left rail. An OAM column is a screen column *plus* 8, exactly as an OAM
row is a screen row plus 16 — the row's offset is absorbed inside
`OAM_ROW_BASE` (that is what the `+16` is), and the column's never was, so every
sprite in the game was drawn 8 px left of the map. Measured while climbing level
1's central ladder, `PlayerX=80`, `SCX=8`:

| | screen columns |
|---|---|
| the ladder (level cols 10-11) | 72..87 |
| the sprite, before | 64..79 |
| the sprite, after | 72..87 |

`PlayerX` is a **left edge, not a centre** — settled from the Z80 rather than
from the port, since the port's own collision (`PlayerX >> 3`, and the ladder
alignment `x = c*8`) already assumed it: `DrawSpriteNum` draws its 16x16 buffer
at the screen cell `x >> 3` shifted by `(x & 7)`, which puts the sprite's left
edge on pixel `x`. The fix is `OAM_COL_OFFSET = 8` added at the three sprite
draw sites (Harry, hens, lifts).

Why it survived so long: on an 8 px tile an 8 px shift is subtle — a player
standing at the left edge of his tile instead of centred — and there is no
ladder in the first six phases' screenshots. On a two-cell ladder it is
unmissable. `verify_player.py` section 9 now asserts the climber's sprite covers
exactly the ladder's two cells, read from the level data and the camera rather
than from the sprite transform; falsified against the missing `+8`, it reports
`-8 px off centre on it`.

**The hens were anchored 15 px too low, and the anchor differs by entity.** With
the row and the column both fixed, play-testing still showed the hens sitting
into the platforms they walked on — head at the platform line, body hanging
below it. The row transform was right and the *anchor* was wrong: Harry's
`PlayerY` is the **top** of his sprite, but a hen's record y is the level pixel
its **feet stand on**, so the two need different bases. Drawing a hen with
Harry's formula sinks it 15 px, which is the exact height difference between
`[y, y+15]` and `[y-15, y]`.

The evidence is in the spawn data, and it is not marginal — read `HenStarts`
across the eight levels (26 hen starts) with the standing tile at row `(y-1)/8`:

| reading of the record | standing on a platform | on a platform or ladder |
|---|---|---|
| y is the **feet** (right) | 17/26 | 21/26 |
| y is the head | 0/26 | 3/26 |

All four climbing hens (`dir` 3/4) land exactly on ladder cells under the first
reading. The fix is the chain again, not a new literal:
`HEN_OAM_ROW_BASE = OAM_ROW_BASE - 15`.

Why three checks missed it and one of them could not have caught it:

- `verify_hens.py` section 4 recomputed `OAM_ROW_BASE - y - SCY` by hand, i.e.
  the same transform with the same wrong base — **this is the third time**
  (Phase 4's `LIFT_ROW_BASE`, 6a's row, Phase 1's column) that a check which
  recomputes a derived constant agreed with the bug. Section 4b is now the
  property a player sees: stand a hen on a platform found in the level data and
  assert the platform's top edge is the first drawn screen row below its sprite —
  no transform in the test at all. Falsified against the old base before it was
  kept: `the hen's feet are at OAM row 119 but the platform under it starts at
  row 136`.
- It is invisible on flat ground (a hen 15 px into an 8 px platform still reads
  as a bird near the ground) and obvious the moment a hen walks a platform edge,
  which is why it took play-testing.
- The hen's *column* was already right and stayed right: the records' x is a
  left edge, the same as `PlayerX`.

### Phase 6b — sound (done 2026-10-02)

*Check: `tools/verify_music.py`, passing on `chuckie.gb`.* Hand-rolled driver in
`src/main.asm`, tunes emitted to `src/music.asm` by `gbdata.py`, APU registers
added to `src/hardware.inc`.

**The streams, and the swapped comment.** Both tunes are raw byte streams in
`reference/paulie`, byte-identical in `mrcook`: `TitleMusic` (94 bytes = 47
pairs, 46 notes) and `LoseLifeMusic` (50 bytes = 25 pairs, 24 notes). A pair
whose first byte is 0 ends the stream — it is the pair `(0, 0)`, the terminator
is a whole entry, not just a flag byte. **`PlayMusic`'s comment calls the pair's
first byte "pitch" and that cannot be right** — it is only ever 1 or 2 across the
whole title tune, and the death tune's first byte is a constant 2 while its
second descends 8, 6, 4, 3, 1. Read the other way the title has a melody and the
death tune has a falling contour. **Byte 0 is duration, byte 1 is pitch** — a
third swapped annotation in a file that already has the timer's two.

**The re-encode.** Pitch is the Spectrum's semitone index (0 = middle C):
`f = 261.63 * 2**(i/12)`, `period = 2048 - 131072/f`. `gbdata.py` emits
`MusicPeriods` — 22 words, 1547..1899, covering pitches 0..21 — plus both
streams. **The tune is not 1:1 and cannot be**: the GB has no AY, so this is a
fresh encode and fidelity is an ear test. `NOTE_UNIT = 6` is the one number in
the phase that is a judgement rather than a translation — frames per BEEP unit —
and it is read out of `main.asm` by the verifier rather than repeated there.

**The driver.** One note per frame from the VBlank handler, after `DrawHud`.
`wMusicPtr` (dw) *is* "playing": 0 is not a ROM address, so the terminator stops
the tune by zeroing it. `wMusicTimer` counts the note down. Channel 1 is the
tune, channel 4 the effects, so a pickup never eats the music. SFX are one shot
(`wSfxTimer`, `wSfxFreq`, `SFX_LEN = 8`, `SFX_FREQ = $4A`): an egg, corn, and
the death jingle (`LoseLifeMusic` — both from `CollidePlayerAndHen` and from the
time-up path, since 6a routes a time out into the death path). `StopMusic` is
called from `LoadLevel`, so a death's jingle ends when the level reloads.

**One deliberate divergence.** The Z80 beeps once per point while draining
`Bonus` into the score; the port's drain is a tight loop, not frame-paced, so
one `SfxPickup` goes in at the top of `DrainBonus` and the rest of the drain is
silent. Matching the original would mean pacing the drain a frame per point,
which is a change to the game, not to the sound.

**Traps this phase cost time on, all PyBoy-side:**

- **With `sound_emulated=False` PyBoy does not model the APU at all** — a write
  to it is dropped and reads back 0, including a write made from the host. So
  `verify_music.py` is the one verifier that boots with sound **on**, and it says
  so in a comment. Every other verifier keeps it off; that is not an oversight
  there.
- **`rNR13` and `rNR14`'s period bits are write-only.** There is no register to
  read the playing period back from, on hardware or here (`rNR13` reads `$FF`,
  `rNR14` reads `$BF`). The driver therefore keeps `wMusicPeriod` (dw) beside the
  register write, and the verifier reads the shadow; the channel's readable
  state (`rNR12` volume, `rNR52` power) is what ties that shadow to a channel
  that is really running.
- **A poke made straight after a tick can straddle the frame boundary**, and the
  tick that consumes it then carries an extra VBlank — one extra timer
  decrement, so every later note measured one frame early. Same family as the
  display-lag race: the fix is the settle-then-poke idiom `verify_hud` already
  uses for corn, not a retry loop.
- **The fetch frame counts as one of the note's frames**, so the timer is
  written `T-1`, not `T`; without the `dec a` every note ran one frame long and
  the tune drifted. `T = 0` must not be stored either — `dec [hl]` on 0 gives
  `$FF` and stalls the note for 255 frames, hence the `and a / jr z, .note`.
- **The pointer is two bytes into a stream by the time you can read it** after a
  death, because the same tick fetched the first note. The assertion is "inside
  `[LoseLifeMusic, LoseLifeMusicEnd)`", not "equal to `LoseLifeMusic`".

### Phase 6c — title, high score, game over (decoded 2026-10-02)

*6c-1, 6c-2 and 6c-3 shipped 2026-10-02.*

Decode pass done over `reference/paulie`. Facts below are split into what was
re-read line by line while writing this and what is reported from the decode
pass and still wants a look when it is implemented.

**Address hazard, worth knowing before any of this.** The hex comments scattered
through paulie's source (`; $72D8 - PlayerX`) are the **original game's**
addresses, not this reassembly's. `PlayerX` is `$6F24` here. Trust the labels
and the assembler-computed comments; cross-check against `reference/mrcook`.
Three comments in that file have already been wrong (the timer's two, and
`PlayMusic`'s), so a comment is not evidence.

**There is no level-select menu.** The plan's open question, now answered:
`FrontEndMode` is a *menu screen ID* (mrcook: `03` redefine keys, `05` select
input type, `06` intro music, `0A` instructions), and `ShowInstructions`'s
3-option menu stores `B` ∈ {6, 5, 3} into it. `SetWorkingKeys` (6122–6148, read
directly) then maps it to one of three *key tables* — `$05` → `CursorKeys`,
`< 5` (`$03`) → `UserDefinedKeys`, else → `The2W90Keys`. They are control types,
never levels: every game start copies **Level1**, and `CurrentLevel` advances
only in `LevelCompleted`. So `LEVEL_NUM` is not bypassing anything, it is a
port-only bonus, and keeping it costs no fidelity.

**Lives.** `P1Lives`–`P4Lives` are four consecutive bytes at `$6EF0`; nothing
but the sites below reads them. Set to **5** at game start in two places that
must agree (`LivesSet` 4346 and `PressStart`'s start-up block). Decremented in
`LoseLife` (4547–4550, read directly): `LD HL,P4Level; ADD HL,DE; DEC (HL)`,
i.e. through the `P4Level` alias — which is why a `Lives` grep does not find it.
Zero lives → a scrolled "game over" and, once *every* player is out, the
front-end; with lives left it **replays the level**, not the front-end.
Drawing (5991–6022): hats are tile `$B6` on the Spectrum's *second* HUD row,
7 columns apart from column 5, and the current player's **last hat is blanked** —
the row shows `lives-1` because the last one is the life in play. An extra life
lands at 1 000 points (`AddToScore` 3916–3944), capped so there is never a 7th
— but the cap is a *display* rule (six hats on the row); the counter itself has
no ceiling, and the port, which shows a count, therefore has no cap at all
(6c-4 below).

**Time-up does not kill Harry — the port's 6a stopgap is a divergence.**
`DecreaseTimerOrBonus`'s underflow (3491–3520, read directly) sets
`TimerRunning = 0` and returns; it unwinds the rest of the main-loop iteration
via `POP HL / RET` for the *other* array. Nothing dies. `LoseLife`'s sentinel
test (4502–4516, read directly) is the **only** reader of `$FF,$09,$09`, and it
runs at *death* time: an ordinary death prints nothing extra, a death when the
clock had already run out prints "OUT OF TIME !". So the original's rule is
*the clock stops and the bonus is forfeit; Harry dies of his own fall or a hen,
and that death is then labelled*. 6a routed the underflow into the death path
deliberately, "so a time-out is observable now; the message and the life it
costs are 6c's" — 6c is where that gets settled.

**Title and player count.** `FrontEnd` (4011) is the title: `TitleText` (22 rows
× 14 chars) with the CHUCKIE EGG logo, `PrintHighScoreTable`, `TitleMusic`
played **once** (guarded by `MusicFlag`), and a bottom-line ticker. `TestKeys`
(4096) reads S → `PressStart`, R → redefine keys, I → instructions.
`PressStart` (4257) asks "1,2,3 or 4 players ?" and is where lives/eggs/level are
initialised. `OnePlayer` (4374) is the entry to a game: `PlayLevel`, and
`EggsRemaining == 0` → `LoseLife`.

**High score table** (since re-read and built — `verify_scores.py`; the two
divergences, 8 entries and a 14-wide two-row alphabet, are in "The high-score
screen re-spaced" below). `HighScores` is **160 bytes =
10 entries × 16** (10 name bytes + 6 score digits); all ten initial entries are
identical — an 8-tile "A+F CHUCKIE EGG" logo and `001000`. `PrintHighScoreTable`
(5517) prints a heading plus 10 rows; `CompareScore` / `CheckHighScore` /
`InHighScoreTable` / `InsertScore` (5104–4740) shift entries down and leave the
new one inserted; name entry (4789–4845) is **9 cells on one row**, a cursor tile
`$B7`, ENTER to finish and DELETE to rub out, and it writes **straight into the
entry** — there is no separate commit step.

**What the port is missing for all this, measured:**

- **A real text font.** The port's font is `src/font.asm`, 14 glyphs
  (`HUD_CHARS = "0123456789BEST"`), and the level bank is *compacted* to the 20
  tiles the levels use — so the reference's `gfx_CharacterSet` is **extracted but
  not in the ROM**, and nothing today can draw "A & F SOFTWARE" or a typed name.
  This is the largest piece of new ROM data in 6c. It needs a "keep these extra
  ids" list in `gbdata.py` rather than a bigger compacted run.
- Tiles for the title logo (`$7F`–`$8A`), the lives hat (`$B6`), the high-score
  cursor (`$B7`), and the default-name logo (`$8F`–`$96`). Budget is fine: 116
  of 256 in use, and the whole 6c set is ~81 tiles.
- `TitleMusic` already exists as a stream in `src/music.asm` and nothing triggers
  it; check its length is the Z80's 94 bytes when wiring it.

**Divergences the port must make, decided or forced:** the Z80's 32×24 character
geometry (every H/L coordinate is Spectrum screen math and has to be recomputed);
the attribute plane (`$5800+`, colour pulses, flashing) has no GB analogue —
those become palette or map swaps, or are dropped; the 3-row HUD becomes 1; the
ROM `BEEP`/speech/`IM 2` Orator machinery is dropped wholesale; name entry's
`KSTATE`/`LASTK` keyboard service becomes the port's own scan. No SRAM and no
tape — the original loses its table at power-off and the port should match that;
persistence would be a new feature, not a port.

**Settled decisions (2026-10-02, user):**

- **Lives take the BONUS field.** The row stays one row and every other field
  stays: `S00000 E12 T900 L03` (the `B` glyph is already in the HUD font; `L`
  needs adding, so `HUD_CHARS` grows by one). The cost is that the bonus count
  loses its only display — it is still earned and still becomes score at level
  end, it just is not shown. Only `verify_hud.py`'s content check encodes the
  field list.
- **Time-up matches the Z80.** The clock stopping does not kill Harry and does
  not cost a life; it forfeits the end-of-level bonus, and the death he does
  eventually suffer prints "OUT OF TIME !". `wTimeUp` therefore changes meaning
  from "dead" to "clock stopped" — it gates the bonus drain and is read by the
  death path, not by the death path's trigger. This removes 6a's stopgap.

**Slicing, in the order the pieces depend on each other — three commits, the way
6a/6b were:**

1. **Lives + game over + the time-up rule.** Smallest, and the one that finishes
   the game loop: the life byte and its HUD field, initialised once per *game*
   (not per level — the Z80 sets it in `PressStart` and only ever decrements it),
   the decrement in the death path, replay-the-level while lives remain, and a
   game-over branch at zero. Until 6c-2 gives it a title to return to, game over
   restarts the whole game (lives back to 5, level 1) — a deliberate interim,
   not a design.
2. **Title + press-start.** Needs the text font (which 1 may already need for
   "GAME OVER"); `TitleMusic` gets its trigger.
3. **High score: table, sort, insert, name entry.** The name-entry grid is the
   only part that is genuinely new input handling.

Each ends in its own runnable check wired into `make verify`.

#### 6c-1 — done 2026-10-02

`tools/verify_lives.py`, wired in as `make verify-lives` and run against the
boot ROM (the logic is level-independent). It drives the first death with a real
hen-on-Harry collision and the rest by poking the death flag, checks the status
row's `L` field against `wLives` at every step, and asserts the time-up rule
costs no life.

Two things worth keeping:

- **`wLives` is initialised once per *game*, in `NewGame`** — not per level. The
  Z80 sets it in `PressStart` and only ever decrements it; `LoadLevel` must not
  touch it, or dying would be free. `ResetLives` is `NewGame`'s alone.
- **`ResetHens` clears `wPlayerDead`.** It runs inside `LoadLevel`, part way
  through the death reload, so the flag goes clear *before* the level has
  finished being written. `verify_lives.py` learned this the hard way: a death
  poked into that window is wiped by the same `ResetHens` and silently goes
  missing, which is why the check waits for the flag to stay clear for several
  frames rather than just once. Anything else that watches `wPlayerDead` for the
  reload to be over has the same trap.

**The score is two copies, as the Z80's is.** The live `CurrentPlayerScore`
the game adds to, and the player's `P1Score`. Only the round trip between them
was missing at first, and it matters: `PlayLevel` loads the saved copy at the
start of a level, `LevelCompleted` (4420) writes the live copy back when the
level is won, and `HasLivesRemaining` (4605) loads the saved copy *again* after
a death. So **dying forfeits the points earned on the fatal attempt**, while
winning banks them. The port mirrors all three: `wScoreSaved` beside `wScore`,
`LoadSavedScore` from `LoadLevel` (which both a fresh level and a death reload
come through), and `SaveScore` on the completion path only, after `DrainBonus`
so the bonus is included. `ResetScore` clears both, because a new game has
nothing banked to fall back on. `verify_lives.py` checks a death against a
*non-zero* banked score, so "the score came back" cannot pass as "the score was
zeroed".

**Interim, not design:** at zero lives the port started a new game (lives full,
score zeroed, back to the boot level) because there was no front-end yet. 6c-2
replaced that with the title screen, which is what pressing start there does.

#### 6c-2 — done 2026-10-02

The ROM boots to the title, `PRESS START` begins, and the last life comes back
to it. `tools/verify_title.py`, wired in as `make verify-title`.

**`TitleText` is stored bottom-up, and that is the whole trap.** `FrontEnd`
(`Chuckie.asm:4011`) walks it as 14 columns × 22 rows at Spectrum rows 2–23 —
but `PrintCharacter` picks which third of the screen to write to from `H`, so
`H` counts **up from the bottom**: TitleText row `r` lands on screen row
`21 - r`. Read top-down, the title is upside down, which is not obvious from the
bytes until it is rendered. So `TITLE_LINES` names the rows the source's way
round and `title_logo()` returns the block `[::-1]` — the grid rows reversed,
which is the one place the flip has to be paid for.

The layout the port uses, having dropped the `1 to 4 players / of skill for /
a game` line (settled: it advertises four players this port has not got):

| TitleText row | String | GB screen |
|---|---|---|
| 21 | `A & F SOFTWARE` | row 1, col 3 |
| 19 | `presents` | row 3, col 6 |
| 11–16 | the 14 × 6 logo, `$7F`–`$8A` | rows 5–10, col 3 |
| 2 | `by  n.alderton` (two blanks, the source's own) | row 12, col 3 |
| — | `PRESS START` (the port's) | row 15, col 4 |

Columns are `(20 - len) // 2`, computed in `gbdata.py` so the asm carries only
the column. **The glyph set is derived from those four strings** — 24 glyphs,
re-encoded from the source charset at shade 3 exactly as the HUD font is — plus
the 12 logo tiles the grid references (`$88` is in the range and unused). VRAM
goes 117 → **153/256**; 6c-3 has 103 to play with.

**Indices are 1-based**, and that costs a `dec a` in each drawing routine. A
0-based scheme would need a sentinel that is not the space glyph, and the space
glyph is the set's first — so the line tables use 0 to terminate and a `dec a`
buys the collision away. Worth knowing before adding a fifth line.

`EnterTitle` / `StartGame` / `DrawTitle` / `DrawText` / `DrawLogo` /
`RowColAddr` in `src/main.asm`. `wOnTitle` gates `HandleVBlank` (music and SFX
only — no camera, no draws, no window bit) and `MainLoop` (read the pad, START →
`StartGame` → `NextLevel.reload`). `LoadLevel` now hangs off `StartGame` alone,
so the boot path loads no level at all.

**The `rLY` hang.** `EnterTitle` mirrors `NextLevel.reload`'s wait-for-blanking
before switching the LCD off — but at boot the LCD is *already* off, and a
switched-off LCD holds `rLY` at 0, so the unconditional wait never ends. Guarded
with `ldh a,[rLCDC] / and LCDCF_ON / jr z,.dark`; the symptom was a ROM that
never painted anything.

**Divergence, recorded:** the Z80 guards `TitleMusic` with `MusicFlag` so it
plays once per session. The port starts it every time the title is entered —
which is after every game over, and is the point of a title tune.

**Nine verifiers changed shape.** Every PyBoy check assumed a level was loaded
the moment the screen came up, which stopped being true. The duplicated
readiness block plus the new press-START step is now `tools/harness.py`'s
`boot()` — a net deletion in each file and one place for the boot step.
`verify_music.py` also learned two things: a game opens via `LoadLevel` →
`StopMusic`, so its old "something is playing at boot" assertion was inverted
(now asserted as silence, which is a real check), and the verifier's direct
`wMusicPtr` poke skips `StartMusic`'s volume re-arm, so it performs it by hand.
`verify_lives.py`'s game-over section asserts the front-end screen — the title
then, the high-score table now — before pressing START and asserting the fresh
game behind it.

`verify_title.py` reads the title back out of the running ROM in six parts: the
mode (`wOnTitle`, OBJ **off**, WIN off, `SCY`/`SCX` 0, `rLYC` still 8 so the
band's split survives); the glyph run located **by pixels** against the source
charset re-encoded, exactly as `verify_hud.py` finds the status font, which is
what pins the base, the tile order and the shade independently of the generator;
the screen decoded through that base against the expected strings plus a
logo-shape check (the 6 × 14 block's cells must all be logo tiles and no cell
outside it may be); the tune, `wMusicPtr` inside `TitleMusic`..`TitleMusicEnd`
and moving; START, which checks the level reached the map rather than merely
being claimed in WRAM; and game over, which is the whole route back.

**Falsified twice before committing**, as 6c-1 was: nop'ing the game-over
`call EnterTitle` fails step 6, and forcing the `wOnTitle` branch in
`HandleVBlank` down the game path fails step 1 with "the title is scrolled:
SCY 32 SCX 0, expected 0/0".

#### 6c-3 — done 2026-10-02

Game over → the high-score table (with name entry, if the score qualifies) →
START → the title → START → a new game. `tools/verify_scores.py`, wired in as
`make verify-scores`.

**The route, and the flag that pays for it.** The Z80 goes `LoseLife` →
`CheckPlayersHighScores` → `FrontEnd` (`Chuckie.asm:4493`, `:4624`, `:4664`),
and on the Spectrum the table *is* the title screen (art in columns 0–13,
`PrintHighScoreTable` in 16–31). 20 GB columns cannot hold both, so the table is
its own screen: `wOnScores` beside `wOnTitle`, and the front end is their `or`.
The title keeps `wOnTitle=1, wOnScores=0` exactly as 6c-2 verified it, and the
`MainLoop` gate is `wOnTitle | wOnScores` — it has to be read *before*
`.wait_frame`, not at the dead branch, or a dead Harry's tick runs with no level
loaded. START picks its exit: table → `EnterTitle`, title → `StartGame`.

**It offers the BANKED score, not the live one.** `CheckPlayersHighScores` reads
`P1Score`, and it only runs on the lives-left path — so a player who dies with
points earned on the fatal attempt is offered the total banked at the end of the
last *finished* level, not the one on the HUD. The port's `OfferScore` compares
`wScoreSaved` for the same reason, and `verify_scores.py` makes the two differ
(999 live against 175 banked) so the wrong read cannot pass.

**Two divergences from the source, both simplifications:**

- **Five score digits, not six.** `HighScores` is 16 bytes — a 10-byte name then
  six ASCII digits — but the sixth is a **permanent pad**: `AddToScore` (`:3900`)
  bumps `+4` and carries toward `+0`, and `+5` is never incremented, so
  `"001000"` is internally 100 with a stray `0` printed after it. The HUD already
  shows five real digits, so the table does too: the entry is **15 bytes**.
- **No ASCII.** `CompareScore` (`:5104`) compares ASCII because that is how it
  gets a numeric compare out of a fixed-width zero-padded text field, and
  `CheckPlayersHighScores` converts the live scores with `ADD A,$30` first. The
  port's scores are already one digit per byte in `wScore`'s own layout, and the
  entry's score field is laid out the same way — so `CompareScore` is one loop
  with no conversion, and no byte of ASCII exists on this screen.

**The name field holds glyph indices, not characters.** The alphabet is a fixed
27-cell set, so the emitter pre-encodes it: byte 0 is the space glyph, the grid's
cells are indices into the same run, typing stores what the cursor is on, and
drawing a name is `add a, SCORE_TILE_BASE`. Every string on the screen is
**fixed width, so there are no terminators** — which is what lets index 0 mean
space without colliding, and keeps 6c-2's 1-based-index-plus-`dec a` a
title-only thing.

**The tiles are one contiguous run** (`ScoreTiles`, one `MemCopy` in `Start`):
0–53 the glyphs the heading, legend and scores use, 54–80 the alphabet
**inverted** in grid order (the cursor cell), 81–88 the Z80's `$8F`–`$96`
banner — the ten default names, and the only place a name holds tiles that are
not characters. The run is located in VRAM **by pixels** in the check and
asserted unique, the way the title's and the HUD's are. VRAM 153 → **242/256**,
14 spare; ROM0 14144/16384.

**The legend now names the d-pad, and that cost 3 more glyphs** (`PAD MOVE  A
TYPE` / `B RUB  START DONE` — the font has no lowercase, so it renders as it
reads here). The grid is the whole control scheme and nothing on the screen said
so: a player saw `A type  B rub` / `START  done` and had no way to learn that
the pad moves the cursor, which is what the first play test reported. **The
mechanism was never at fault** — `verify_scores.py` §4 drives the cursor with
real button presses — only the affordance, and the play test that reported it
confirmed the fix. The two lines are centred by `(20 - len) // 2` as before, so
the second sits one column left of the first. **VRAM is now 252/256 — 4 spare,
the tightest in the port**; the next glyph this screen needs means cutting the
inverted run (27 tiles for what one two-column block could do). A hyphen
(`d-pad`) was not used: the emitter asserts `chars[1] == "0"` because the
ASCII-sorted glyph list starts space, digits, uppercase, lowercase, and `-`
sorts before `0`.

**The name-entry controls, recorded because the screen is the only place they
exist:** the d-pad moves the grid cursor — **one step per press, no
auto-repeat**, which is `wPadNew` and not the held `wPad` the game reads — A
types the highlighted cell, B rubs one out, START finishes. The cursor starts on
the grid's **space** cell (cell 0 of `" ABC…Z"`, since index 0 has to be the
space glyph), so the very first A types a blank; the field cursor still moves,
so it is not a dead press, but it is the one odd first move and `wGridCol = 1`
would start it on `A` if it ever grates.

**And the duck check no longer writes down the duck's tile base.** It was 242,
then 244 when this legend grew the run by two — reported as a duck bug for a
change in the score screen. `verify_duck.py` now reads the base out of VRAM
where it already found the art by pixels, and asserts what actually matters:
one contiguous copy of the source frames, and the OAM naming it. A frame copied
short or a draw base disagreeing with the copy's still fails (falsified: `ld bc,
DuckTilesEnd - DuckTiles - 16` fails with "the duck's 8 tiles are nowhere in
VRAM").

**The run was not contiguous, and the screen check could not see it.** `Start`
copied `ScoreTilesEnd - ScoreTiles`; the emitter put `ScoreTilesEnd` at the end
of the *glyph* group and `ScoreGlyphsAscii` — 54 bytes of lookup table, not
tiles — in the middle of the block. So 54 of the 89 tiles shipped: no inverted
alphabet, no banner, and had the copy run to the real end it would have written
three and a bit tiles of the ASCII list as rubbish. **A passing screen check is
not evidence here**, because the BG map holds *indices*: an index into a tile
that never reached VRAM reads back as exactly the right number. `cell_ok` was
comparing map bytes to `BASE + index` all along and agreeing with itself.
Found by the mGBA eye test, which is what the plan said it was for. The emitter
now puts `ScoreGlyphsAscii` after the run it names, `ScoreTilesEnd` means the
end, and the check matches **all 89 tiles** by pixels rather than the glyph
group alone — falsified by restoring the short copy, which now fails with
"found 0 runs of the score tiles in VRAM".

**The insert's arithmetic is the part that needed falsifying.** Both
`HighEntryAddr` (rank → byte offset) and the `LDDR`-equivalent shift were wrong
in ways a rank-1 test cannot see: the first added the slot twice (invisible when
the slot is 0), and the second started its source at a computed offset that was
only right for rank 1 — at rank 8 it copied entries 1–2 up into 2–3. The fix is
the observation that the shift's two ends are **fixed** (from the end of the
second-to-last record to the end of the table) and only its length varies,
because `(rank-1) + (COUNT-rank)` is `COUNT-1` whatever the rank is.

**And the first PASS was a false one**, which is the lesson worth keeping: all
ten seeded entries are identical, so an insert that shifted *nothing* produced a
table byte-identical to one that shifted correctly. The check now pokes ten
**descending** scores before the death and asserts the whole 150-byte table
against the shift done by hand, and only then did the two bugs above surface.
Four falsifications now fail as they should: dropping the shift, shifting from
one record too low, gating A on `wPad` instead of `wPadNew`, and reading
`wScore` instead of `wScoreSaved`, plus `>=` for `>` (equal displace).

**Name entry iterates ~twice per frame.** `halt` also wakes on the LYC STAT
interrupt the HUD band uses, so the loop runs two passes per frame —
`SCORE_BLINK = 20` is therefore a ~10-frame blink. Harmless, because `wPadNew`
is recomputed on each `ReadButtons` call, so one press is still exactly one
step; recorded so the counter is not "fixed" later.

**Both `verify_title.py` §6 and `verify_lives.py` §6 changed shape**: the same
route now runs table → title → game, and each zeroes the banked score first so
no name entry opens between the two STARTs (typing a name is `verify_scores.py`'s
job). `tools/harness.py` gained `tap()` for the d-pad and A/B presses, with
`press_start()` now a call to it.

#### 6c-4 — the extra life, done 2026-10-02
**The rule is a shadow, not a counter.** `AddToScore` (3916–3944, read directly)
finishes by comparing `CurrentPlayerScore+1` — the **thousands** digit, since the
digits run from `+0` with the units at `+4` — against `LastDigitValue`
(Chuckie.asm:308), a single byte that starts at 0. Differ → store it, `INC` the
player's lives, and draw a hat. The digit moves every 1 000 and nothing else, so
the shadow is what makes the life land **once per block rather than once per
point**; there is no modulo and no points counter. `LastDigitValue` keeps its
name as `wLastDigit` in the port. Two consequences worth stating: a `B` of 0
never reaches the branch (the Z80 jumps to `PrintScore`, the port returns), and
`ResetScore` now clears **13** bytes rather than 12 so a new game zeroes the
shadow with the two score copies — correct rather than incidental, since a fresh
score's thousands digit is 0.

**The re-sync is the subtle half.** `PlayLevel` (:5947, read directly) stores the
digit right after it loads the banked score, so a level start owes nothing. The
port puts the same store at the end of `LoadSavedScore`, which both paths that
load a score already go through (`LoadLevel` at a level start and `wait_reload`
after a death), so no caller changes. Without it a death would pay: the live
score drops back to the banked total while the shadow still holds the digit the
fatal attempt reached, and the first point earned then looks like a crossing.
Invisible at the start of a fresh game, because there every digit is 0.

**Divergence, recorded:** the Z80 draws a hat per life on its second HUD row and
stops at six of them, so a seventh life exists in its counter but is never shown.
This HUD shows a **count** (the divergence 6c-1 settled), so a life past the
sixth shows as one — no counterpart to the `CP $06` guard, which is why
`AddToScore` has a plain `inc [hl]` there. No redraw call is needed either:
`DrawHud` rebuilds the lives field from `wLives` every frame.

**Checked in `verify_lives.py` §8**, driven by **real eggs** at a cell
`verify_eggs.py` proved out (so `AddToScore` is reached the way the game reaches
it), each case preceded by a death so the level opens on a known banked score and
a known shadow: (a) a banked 9990 plus one egg crosses to 10 000 and pays exactly
one life; (b) the next egg, inside the new block, pays nothing; (c) a level
opening on a banked 4000 with the shadow **poked stale** (deliberately not the
digit the score has) re-syncs and pays nothing for its first point; (d) a banked
990 plus one egg crosses to 1 000 and pays one. **(d) is the case that pins the
block**: the digit the Z80 reads is the **thousands** one, so the life lands
every 1 000 points — but (a)–(c) all cross 10 000, where a thousands digit turns
over too, and pass under either reading. The port's comments, this file and
`verify_lives.py` all said "10 000" until (d) was added; running the check with
`AddToScore` watching `wScore+0` instead fails (c) and (d) and leaves the first
two green, which is exactly the discrimination (d) exists for. Falsified both
ways before keeping it: deleting the shadow compare fails (b) and (c) with
"a point inside the block paid another life", and deleting the
`LoadSavedScore` sync fails (c) with the shadow assertion and the free life.
Case (a) pokes the shadow stale too — without that its verdict turns on whatever
the previous section happened to leave in it, and a stale 0 agrees with the digit
after the crossing, which is a pass for the wrong reason.

### Phase 7 — the announcements (done 2026-10-02)

**One routine, three call sites.** `ScrollTextLine` (`Chuckie.asm:5051`) is the
whole of it. It sets the attribute line green, scrolls screen line `$4861` one
pixel at a time, prints each character at `LD HL,$0C1E` — Spectrum cell (y=12,
x=30), the middle row of 24, entering from the right — eight pixel-steps per
character, then scrolls the rest off. Its callers pass the word and a count in
`C`:

| where | word | `C` | when |
|---|---|---|---|
| `:4370` | the player's number | `$10` | multiplayer only — **not ported**, there is one player |
| `:4464` | `LevelScrollText` | `$08` | `NextPlayerPlayLevel`: a level **completed** |
| `:4518` | `OutOfTimeScrollText` | `$0D` | `LoseLife`, gated on the `TimeRemaining` sentinel `$FF,$09,$09` |
| `:4559` | `GameOverScrollText` | `$09` | `HasLivesRemaining`: the last life is gone |

The text block is `:5608`–`:5639`. The level's number is **not** stored with the
word: `:4448` patches the digit into the buffer's last cell before the call,
which is why the port's record carries a `NOTICE_DIGIT` placeholder in that same
position.

**The two death paths differ, and that is load-bearing.** `NextPlayerPlayLevel`
prints the level's number; `LoseLife` goes straight to the reload and prints
nothing. So "LEVEL n" belongs on the port's `NextLevel` — the egg-completed path
— and *not* on a death restart. `:4514`'s sentinel is exactly `wTimeUp`, and
`:4559`'s is `wLives == 0`: the same three-way choice `KillPlayer` now makes.

**What the port does instead of scrolling.** A pixel scroll of the BG here is a
camera move (`SCY`/`SCX`), not a print, and the notice would be sliding the whole
level past rather than a cleared screen. So `ShowNotice` does what the Z80 does
*before* it scrolls — `ClearScreen` is called at every site — and holds the word
still in the middle of the blank map: row 8 of 18, centred. The hold is
`NOTICE_HOLD` (25 frames, the Z80's ~0.3 s beat) on the level path, and on a
death `DEATH_DELAY` (90), which is the same beat as the freeze — so the notice
**is** the freeze, not an extra pause. A front-end flag `wOnNotice` joins
`wOnTitle | wOnScores` in `HandleVBlank`'s branch; without it the playing branch
would put the camera, the status band and the sprites back over the top.

**The glyphs come free.** The word is drawn from the score run
(`SCORE_TILE_BASE` = 153), which is resident through a game anyway, and
`SCORE_ALPHABET` already brings A–Z — so the whole phase needed **one** new
glyph, `!`, taking the run 91 → 92 tiles (VRAM 253/256). Because `!` sorts
before `0`, `SCORE_DIGIT_FIRST` moved to 2; `gbdata.py` emits it as a `DEF`
rather than searching for it, and asserts `chars[0] == " "` so a blank name byte
can never draw something. The record is a row, a column, a cell count, then that
many glyph indices — fixed width, no terminator, index 0 being the space glyph.

**`KillPlayer` was extracted** so both collisions (`CollidePlayerAndHen`,
`CollidePlayerAndDuck`) reach one death path; before this each had its own tail.
It picks the word — `wTimeUp` first, then `wLives == 1`, else the silent freeze.

**Two bugs, and the checks saw neither.** Both were found by the eye test, which
is this port's recurring lesson — a check written from the implementation agrees
with the implementation:

1. **`ClearMap` zeroes `D`** (`ld d, 0`, its blank byte) and so destroyed the
   notice record pointer in `DE` before `RowColAddr` read it. The row, column,
   count and every glyph came out of bank-0 ROM at `$004A` — nothing was written
   anywhere, and the screen was blank. **The bug was invisible to every other
   caller because none of them holds anything in `DE` across `ClearMap`.** Fixed
   with a `push de`/`pop de` in `ShowNotice`; `ClearMap` itself is left alone.
2. **`.digit` jumped to `.store`, past the `add a, SCORE_TILE_BASE`.** The
   level's digit was written as a *raw glyph index* — 3, for level 1 — and so
   drew whatever tile happened to live at VRAM 3. For level 1 that looked enough
   like the reference font's `1` (a flag and a stem) that the eye test passed it;
   the check caught it as `'LEVEL ?'` the moment the tile was decoded back to a
   character. Fixed by sharing the store: both paths `add a, SCORE_TILE_BASE`.

Both halves of the fix are now pinned by the check, which is the point.

**Divergence, recorded:** a death that is *both* timed-out and the last life
shows one word, "OUT OF TIME !" — the Z80 scrolls that and then `game over ` in
sequence. One word says what happened, and the table behind it says the rest.

**Checked in `verify_notice.py`**, all read back out of the running ROM. The
score run is located by matching **all 57 glyphs** against the source charset
re-encoded at the HUD's shade (`verify_lives.py`'s identification), so a shifted
index or a wrong base fails rather than spelling something plausible — the run is
found by pixels, never read from `SCORE_TILE_BASE`, which is an expression in
`main.asm`. Each word is checked four ways against the other three: the record
decoded through `ScoreGlyphsAscii`, the screen decoded back through the same
table, the record's row/column against where the cells actually are, and the
screen against "the map holds exactly this one run and nothing else". The
hardware state is read too — `SCY`/`SCX` home, OBJ and the window band off —
which is what falsified the wOnNotice suppression. The announcements are reached
by their **real routes**: a level change driven by `wLevelDone`, and both deaths
by a real hen-on-Harry collision, because `KillPlayer` is where the word is
chosen and poking `wPlayerDead` would test everything except the thing under
test. The digit is checked against `wCurrentLevel + 1` read **live**, so an
off-by-one or an `and 7` slip shows.

**Falsified three ways before keeping it:** the `wOnNotice` suppression removed
(`SCY`/`SCX` and `LCDC` fail — the camera and the band reappear over the word);
the `wTimeUp` branch removed (the time-up death raises nothing); and the original
`.digit` bug, which is how it was found.

**Two checks changed shape.** `verify_eggs.py`'s reload window (30 → 60 frames)
and `verify_lives.py`'s `tick(8)` after a win had both encoded the old, shorter
level transition; the announcement is most of that wait now. `verify_lives.py`
waits for `wLevelDone` to clear instead, which is what it should have done — a
death poked while `ShowNotice` was holding was being wiped by `ResetHens`, the
exact trap that file's own `wait_reload` documents.

### The name-entry panel is drawn only when there is a name to type (2026-10-02)

**A play report, and the bug was on a screen nobody had checked.** "The high
score input looks to have reverted" — legend right, d-pad dead. It reproduced in
one case, and the case is the ordinary first game over.

`DrawScoreTable` drew the alphabet panel and its legend **unconditionally**, and
`EnterScores` calls `NameEntry` unconditionally too — but `NameEntry` returns at
once when `wNameEntry` is 0, i.e. when `OfferScore` found no rank. So a game that
did not qualify put up a grid with **no cursor** under a legend reading `PAD
MOVE  A TYPE`, and neither the pad nor A did anything. The Z80's table is the
table and nothing else (`PrintHighScoreTable`, `:5517`) — the panel is the port's
own, and it belongs to the typing, not to the screen.

And the non-qualifying game is the common one: `DefaultEntry`'s score is **100**
(`$00,$00,$01,$00,$00`), while a death costs the points earned on the fatal
attempt — `HasLivesRemaining` copies `wScoreSaved` back over `wScore` — and the
level's 200-point bonus only drains on a *completed* level. Die on level 1
without finishing it and the score is 0. Nothing qualifies, ever, on a first
game.

Fixed in `DrawScoreTable`, the one place that draws both: `ld a,[wNameEntry] /
and a / ret z` before `DrawGrid`. `verify_scores.py` §5 already asserted
`wBlinkOn` stayed clear for a non-qualifying score; it now asserts the screen
agrees — rows 13–17 hold nothing, and no cursor tile anywhere on the panel —
which is what the old code failed on rows `[13, 14, 15, 16, 17]` when falsified.

**The lesson is the one this port keeps teaching:** the check covered the *data*
(`table() != before`) and the *flag* (`wBlinkOn`), and the wrong thing was what
the screen *promised*. Every other screen in the port is checked cell by cell;
this one is checked only on its qualifying path.

**Found while looking, and left alone:** the grid cursor starts on the **space**
cell (`wGridCol` is 0), so the first `A` types a blank. It is a recorded oddity
from 6c-3 and one line (`wGridCol = 1`) to start on `A` — not changed here,
because it is not what the report was about.

### The front end finished — the space-cell start, and the instructions (2026-10-02)

**Two of `FrontEnd`'s loose ends, and one divergence.**

**The name-entry cursor starts on `A`, not on the blank.** The recorded oddity
from 6c-3: `wGridCol` was 0, so the first `A` typed a leading blank. One line in
`NameEntry` (`inc a` before the store) and the cell under the cursor is cell 1.
The Z80's field starts blank too, but its cursor is an insertion point rather
than a cell, so there is nothing there to sit on. `verify_scores.py` §4 now
starts from `START_COL = 1` and steps right twice to `C`.

**The instructions screen is re-authored, not ported — this is a divergence and
it is deliberate.** The Z80 reaches its own from `I` at the front end
(`TestKeys`, `Chuckie.asm:4113`) and leaves on `S` (`:4177`). That screen is
*Spectrum keyboard documentation*: "keys are user defineable", why the three key
types are preset, a UDG diagram of the cursor keys against the `1/2/3/4` / `9/0/z/m`
columns, four attribute fills, Orator speech and a marquee (`InstructionsScrollText`).
A DMG has a pad, two buttons, and no redefinition — so none of it survives.
What does survive is its purpose and one sentence, and that sentence is the
original's own, buried in the 7-byte records inside `InstructionTextKeys`: **"the
hen-house. objective- to collect eggs from"**. The screen says `COLLECT THE EGGS /
FROM THE HEN-HOUSE`, hyphen and all.

The rest is the port's controls, stated because the port's controls are what a
player needs and what nothing else on screen says:

```
row  1 |    INSTRUCTIONS      row  9 |  PAD     MOVE
row  3 |  COLLECT THE EGGS    row 11 |  A       JUMP
row  5 | FROM THE HEN-HOUSE   row 13 |  START   PLAY
row  7 |   AVOID THE HENS     row 15 |  SELECT  BACK
```

**One blank row between every pair, heading included.** A capital fills its
whole 8x8 cell, so two lines drawn on ADJACENT map rows touch and read as one
garbled line. The first cut of this screen used rows 1,3,4,6,9,10,11,12 and
rendered `COLLECT THE EGGS` and `FROM THE HEN-HOUSE` as a single illegible band
— the same defect, found the same day, in the title's two bottom lines
(`PRESS START` on 15, `SELECT HELP` on 16). Both now step by two.

`AVOID THE HENS`, and not the duck: the mother duck's cage holds through level
8 (`CP $08`), so she is harmless on **every** level the ROM boots into and only
loose from 9 — naming her would be wrong on all eight.

**Entry is SELECT** — the DMG has no `I`, and SELECT is what the pad calls "this
button does something else". **Leaving is SELECT too**, and **START from the
instructions begins the game**, exactly as the Z80's `S` does. The screen is a
screen *off* the title rather than a screen of its own: `EnterInstructions`
deliberately leaves the tune running, and leaving it is the same `EnterTitle` a
game over takes — one route out, no new state.

`wOnInstr` is the third mutually exclusive front-end flag beside `wOnTitle` and
`wOnScores`, and both front-end tests (`HandleVBlank` and `MainLoop`) grew one
`or`. `StartGame` clears **both** flags it can be reached with, which is a bug
this work would otherwise have shipped: with `wOnInstr` left set, `MainLoop`'s
front-end branch fires every frame and the level is drawn but never ticked.

**The budget shaped the screen, not taste.** The score run was at 253/256 tiles
and the run's lowercase is only the letters the table's own strings use, so
"jump", "back" and "from" would each have cost a tile — while `A`–`Z` is all
there already. The instructions and the announcements are capitals for that
reason, and the only new tile spent is the hyphen (254/256 then, 255/256
after the score panel was re-spaced). The title's
`SELECT HELP` hint is drawn from the **score run** through the new
`DrawRunLines` walker rather than from the title's own glyph set, which would
have cost three more tiles (`C`, `H`, `L`) out of a VRAM two from full.

*Check:* `verify_title.py` §7 — SELECT opens the instructions (flags exclusive,
`LCDC` with OBJ and WIN off, no scroll), **every one of the 360 cells** is
compared against lines stated in the verifier rather than read from the
generator, SELECT closes back to a title **byte-identical to the boot map**, and
START from them begins a game whose clock is poked and then has to walk.
*Falsified two ways:* dropping the `wOnInstr` clear from `StartGame` (the flag
and the frozen clock both fail), and dropping the `or` from `HandleVBlank`'s
test (the instructions inherit a level's OBJ palette and its camera — `OBJ`,
`SCY` and `SCX` all fail).

**And a check that was passing by luck.** `verify_lifts.py` §6 failed on the
front-end build and the cause was not the front end: the draw pass runs inside
the VBlank handler and spills past the frame boundary — `rLY` is 0 when
`pb.tick` returns — so a read taken immediately after a tick can land between
the two halves of a platform, the second still holding the previous frame's `x`.
That is invisible while the camera is still and shows up only on a frame where
the camera moved, which is exactly the frame §6 reads (it walks Harry onto the
platform first). Any change in code size re-phases it; this build re-phased it
onto the tear. Fixed with a settling `tick(2)`, not a retry loop — the second
frame holds everything still, so both halves are drawn at the same `x` and a
real one-frame bug still fails.

### The high-score screen re-spaced — eight entries, and a panel that reads (2026-10-02)

**Found by eye, not by a check, and it is the same defect the title and the
instructions screen had: lines drawn on adjacent map rows.** A capital fills its
whole 8x8 cell, so two of them on consecutive rows touch. The name-entry panel
was drawn with its three alphabet rows on 13/14/15 and its two legend lines on
16/17, and the table's entries on 2..11 — every line adjacent to the next. The
measured lit bands were `[(0,0), (2,11), (13,17)]`: three solid blocks, with the
alphabet unreadable and the cursor invisible inside it.

**The Z80 spaces its table rows already, and the port's 18 rows cannot.** Its
`PrintHighScoreTable` (`Chuckie.asm:5517`) starts at `H=$15` and does `DEC H /
DEC H` per entry — ten entries on rows 21,19,...,3 of a 24-row screen, a blank
row between each. This screen has 18 rows and is the only one in the port that
holds two things at once: the table, and the panel a name is typed on.

**The arithmetic, which is why the entry count gives way.** The panel needs its
five lines separated by a blank row each — that is rows 11,13 for the two
alphabet rows and 15,17 for the two legend lines, seven rows for five lines of
content, and no arrangement of five into five rows separates any pair of them.
Ten entries run to row 11 and leave the panel nothing. **`SCORE_COUNT` is 8**,
not the Z80's ten: the table runs rows 2..9, and 10..17 is the panel's.

**The panel now.** `SCORE_GRID_COLS` is 14 and `SCORE_ALPHABET` is 28 cells —
`A`–`Z` plus the blank that rubs a character out, with a spare blank at either
end to square the 14x2. The blank stays at index 0 because nothing searches for
it: the inverted cell 0 *is* the name field's cursor (`DrawEditingRow`).
`SCORE_PANEL_STEP` (2) is the distance between the panel's own lines, used by
the two alphabet rows and the two legend rows alike — so `DrawGrid` had to stop
writing its rows consecutively, and `GridAddr` grew a `GridRowAddr` helper so
the cursor's address and the drawn rows cannot drift apart. The grid is 14 wide
where the cursor used to be 9, so the whole alphabet now reads on two lines
instead of three.

**The cost is one tile.** The 28th inverted cell is a real tile, so VRAM goes
254 → **255/256**. `gbdata.py` asserts the alphabet fills its rows exactly — a
short last row would draw whatever follows `ScoreGrid` in ROM into the panel.

*Check:* `tools/verify_scores.py` — the layout is stated in the verifier rather
than read from the generator, and all 360 cells are compared, so the extra
panel rows and the eight-entry table are both pinned.
*Falsified:* drawing the two alphabet rows consecutively (`add a, 32 - COLS`
instead of `32 * SCORE_PANEL_STEP - COLS`) fails 28 cells; spacing the legend
rows consecutively failed 34 while this was being written.

### Two deaths that were read as stalls (2026-10-03)

**Reported from a level-3 play test: Harry falls through the bottom of the map
and is not killed, and a lift carries him off the top of the playfield with the
controls dead.** Both were the port calling a level exit a skip.

**`MainLoop` is entered by `JP`, not `CALL`** (`Chuckie.asm:6228`, the tail of
`PlayLevel`, which `OnePlayer` reaches at `:4376` as `CALL PlayLevel`). So the
only return address MainLoop ever has is the one `OnePlayer` pushed, and a
`RET` from inside it does not resume the loop — it **leaves the level**. What
waits at `:4378` is `CALL WaitForSpeech`, the score copy, then
`LD A,(EggsRemaining) / AND A / JP NZ,LoseLife`: a player with eggs left is
killed. That is the level's one exit, and every "unwind" in the game is a
variant of it — `CollidePlayerAndHen`'s `RET NZ` (`:2042`), the mother duck's
`ClearStack` unwind to `Start` (`:2579`), and `PlayerPickUp`'s single
`POP HL / RET` on the last egg (`:2270`).

**Falling under the floor** is `POP HL / POP HL / RET` at `:3748`, two pops
because `CollidePlayerToWorld` reached `CollideWithWorld` by `JR`. The port had
it as `ret` — "Harry is standing on the level's bottom row, so we simply stop
moving him" — which soft-locked him: `PlayerInAir` stayed 2, and Jump and
`MovePlayer` are both gated on it, so he could neither jump nor walk and no
death ever came. It is now `jp KillPlayer`.

**Riding the lift past `LIFT_CEILING`** is `RET NC` at `:2115`, straight out of
MainLoop. The port had it as "the tick bails, and Harry rides off the top with
the input dead until his y wraps" — and that is exactly what it did, climbing
past 167 and reappearing at the bottom of the level. It is now `call KillPlayer`
before the `A = 1` that still ends the tick, so the input read keeps being
skipped on the frame he dies.

**Both are the same misreading, and the sweep is now done:** the two `RET`s
inside MainLoop (`:2042` hen, `:2115` lift), the duck's `ClearStack`, the
fall's double pop, and `PlayerPickUp`'s single pop are the whole set. The abort
at `:2077` (`POP HL / JP Start`) is the one deliberately unported — a Spectrum
keyboard has no DMG meaning.

*Check:* `tools/verify_lifts.py` §13 asserts the ceiling kills him as well as
bailing the tick; `tools/verify_player.py` §12 drops him under the floor at
y=8 and asserts `wPlayerDead` goes up.
*Falsified:* reverting either `jp KillPlayer` / `call KillPlayer` fails its
check (`killed nobody: PlayerY=8 PlayerInAir=2`; `riding past the ceiling killed
nobody: PlayerY=165 OnLift=1`).

### Harry's spawn is the game's spawn now (2026-10-03)

**Found while tracing the above, then fixed the same day.** `HARRY_START_X/Y` were
`$AE`/`$37`, taken from the initialisers on the Z80's variable block
(`Chuckie.asm:156,158`). But that block is the program *image*; the values are
live for only as long as it takes `PlayLevel` to run, and `PlayLevel`
**overwrites both** at `:6110`: `LD (IX+$00),$64` and `LD (IX+$01),$17`. It is
`PlayLevel` that runs at every level start, including the first, and no branch
skips it — the routine is `:5812`..`:6228` with no `RET` and no `JP` in between.
So `$AE`/`$37` was never the spawn; `$64`/`$17` is.

Both positions are legal: (100, 23) stands on the level's own floor (row 0,
column 12, tile 5 — solid right across columns 8..20), while (174, 55) stands on
a platform five rows up at column 21. The port was starting Harry on a platform
five rows above the ground.

**It was left as a known divergence first, and the reasoning was wrong twice
over.** The recorded cost — "it would move `verify.py`'s `CAMERA_Y`" — does not
exist: `SCY = clamp(96 - y, 0, 32)`, and y=23 (73) and y=55 (41) both clamp to
`SCY_MAX` = 32. `verify_camera.py` reads the formula and `verify_hens.py`'s
`hen_on_screen` reads SCX out of the ROM, so neither holds a spawn constant. The
real churn was three constants in two files. The second wrong reason was bigger:
the Phase 2 "information asymmetry" — level 1's second hen starting behind Harry
— was not a price of 1:1 geometry at all, it was a property of the wrong starting
position, and moving Harry's spawn removes it without touching a hen's.

**Changed 2026-10-03**, after building both and looking at them side by side in
mGBA (`make ASMFLAGS='-DHARRY_START_X=174 -DHARRY_START_Y=55'` builds the old
one; the constants are `IF !DEF`-guarded for exactly that). Measured on the new
spawn, all eight levels: InAir=0, sprite rows 120..135, the first drawn row below
his sprite is the floor tile at 136 — checked as pixels, on each level, not
derived from the two constants. `SCX` settles at 28.

**The make trap, worth knowing before overriding anything else.** Write the
override in decimal. `make` reads the `$6` in `$64` as its own one-character
variable, drops it, and hands rgbasm `-DHARRY_START_X=4` — which builds a Harry
at the level's bottom-left corner, inside the floor, and reads exactly like a
broken spawn rather than a broken build. The same trap is why a ROM built with
`ASMFLAGS` leaves a stale `build/main.o` behind: `make` sees no newer source, so
the *next* build reuses the wrong object. Delete `build/main.o` between builds.

**What the new spawn puts him next to, asked as "does this introduce bugs".**
Walking right from x=100 and dying on the way is not a port bug on the two levels
where it happens: level 3's ground row is blank at columns 16..17 and level 6's
at column 14, so four cells of walking takes him off the bottom and the Z80's
`CP $10` death does the rest. Re-checked against the level data rather than
inferred from the fall. Level 1's nearest hen is 4 px away in x but 113 in y, so
nothing is adjacent: 600 idle frames kill nobody on levels 1..7, and level 8's
roaming duck is what kills him there at frame 345. He can walk in both directions
from the spawn on all eight levels (no wall, no hole under his feet), and the
camera is written by `UpdateCamera` at :3747 in the level-load path, right after
`ResetPlayer`, so the first frame is never drawn at the previous level's scroll.


### Phase 1 — done 2026-10-02

`tools/gbdata.py` extracts, `tools/verify.py` asserts, `make verify` runs it.
**All 8 levels: BG map 1024 cells PASS, tile data PASS** — byte-exact against
`reference/paulie/Chuckie.asm`, read back out of VRAM through PyBoy.

The lift, and what made it cheap:

- **No tile remapping at all.** mrcook's address table gives
  `tile id n → graphic at $84F0 + n*8`, which both repos agree on
  (`gfx_CharacterSet == $84F0`), so **GB tile index == Spectrum tile id** and
  the level bytes go straight into the BG map. No lookup table exists in the
  project, deliberately.
- **No level geometry conversion.** 32 cells = 256 px = exactly the BG map
  width. Only the row order flips (see below).
- Extraction is **by address, not by label**: the graphics are one contiguous
  182-tile run that the source labels in pieces. `gbdata.py` tracks the address
  from `org` and only advances it on `db`/`dw`/`ds`, then refuses to emit
  anything if any byte in the range is unmapped. The generator also self-checks
  (tile 0 blank, tile 3 == the egg bitmap, level ids ⊆ the allowed set) so it
  fails loudly rather than writing plausible garbage.
- 1bpp → 2bpp is one function: GB colour index is `(high<<1)|low`, so shade 1
  is `low=bmp`, shade 2 is `high=bmp`, shade 3 is `both`. `BGP=$1B` makes index
  0 black, since the Spectrum draws coloured ink on black paper — **the inverse
  of the usual GB convention**, and the thing most likely to be got wrong.

Facts worth keeping:

- **`org $b200` is NOT where the levels start.** Line 6303 is `ds 256, $9c`
  padding before them. Take the base from the `Level1:` label and assert
  Level2–8 are contiguous at exactly 672 bytes; the original address-based
  guess desynced and the gap check caught it doing exactly its job.
- **Row orientation, settled from the game's own code.** `GetCharAddress`
  (line 1646) computes `LevelBuffer + (y/8)*32 + (x/8)`, so level row index
  rises with y, and y=0 is the screen *bottom*. Therefore **data row 20 is the
  top of the screen** — which is why the birdcage (ids `$a8–$b5`, and only ever
  in the top rows) hangs at the top-left, and the floor is at the bottom.
  `DrawLevel` paints bottom-up to flip it.
- **Verifying readiness is the trap in this project.** Twice now the assertion
  has been wrong, not the ROM. Probing a map cell fires mid-draw (the map is
  painted row by row with the LCD off — it caught an 11-row half-finished map);
  probing `LCDC`'s enable bit fires on PyBoy's **boot ROM**, which also enables
  the LCD and turned up a screen of zeros. Readiness now keys on
  **`BGP=$1B` (ours alone; boot leaves `$FC`) *and* LCD-on**, which is written
  after the draw.
- **`ASMFLAGS` changes don't change any timestamp**, so `make shot
  ASMFLAGS=...` silently reused a stale ROM and produced three identical PNGs
  from three different configurations. `shot` now force-rebuilds.
- Levels were chosen at **assemble time** (`ASMFLAGS=-DLEVEL_NUM=5`) through
  Phase 4; `make verify` loops all 8 as separate ROMs (it still does — one ROM
  per level is the cheapest way to check eight byte-exact level blobs, and
  `verify-levels` asserts the ROMs really differ). Phase 5 made the *boot* level
  a flag only: `LEVEL_NUM` picks what the ROM starts on and `wCurrentLevel` owns
  it from there, so level flow is runtime.

Readability, judged on the actual PNGs: platforms (shade 2), ladders (2) and
eggs (3) separate clearly. Corn and platform are the same shade and rely on
bitmap shape alone — acceptable, and the one thing `SHADE` in `gbdata.py` is
there to tune.

### Phase 3 — done 2026-10-02

Harry is drawn as four 8×8 OBJ tiles per frame, walks, jumps, falls, lands and
climbs. `tools/verify_player.py` drives all of it and reads OAM, the camera
registers and WRAM back out of the running ROM; `make verify` runs it with the
level and camera checks. All PASS.

**The Phase 2 camera was wrong on the horizontal axis, and this is the one
thing worth re-deciding.** The plan said "32 cells = 256 px = exactly the GB BG
map width", which is true of the *map* and false of the *screen*: the visible
window is 160 px. So the level needed a horizontal camera as well, and
`SCX = clamp(x - 72, 0, SCX_MAX)` now runs alongside the vertical one, with
`SCX_MAX = 96`. Consequences, plainly:

- Only **20 of the level's 32 columns** are on screen at once. The original
  shows all 32.
- The vertical camera hides 24 px (one band, the birdcage, which Harry reaches
  by ladder anyway). The horizontal one hides **96 px, 37% of the level width**,
  and hides it *continuously* — the level slides under him as he walks.
- The 4×4 demake option was rejected partly because "the crop is 24 px". That
  number was the vertical one only. If a demake of the level is ever back on the
  table, this is the reason to reconsider it.

Harry's spawn is `(x=100, y=23)` in the game's units — PlayLevel's `$64`/`$17`,
which is the Z80's own (it overwrites the image block's `$AE`/`$37`; see "Harry's
spawn"). The camera moved, the coordinates did not. He starts **inside** the
camera's travel rather than against a clamp, so `SCX = x - 72` from the first
frame: 28 at spawn, and no clamp until x=72 or x=168.

**The physics are the Z80's, replayed rather than rescaled.** The original's
main loop is free-running, but its gameplay block is gated on `SoundTimer`,
which reloads to `$82` — so the game advances one gameplay tick per **130 raw
iterations**, while the vertical in-air physics (`CollideWithWorld` →
`NotInAir`) runs on *every* iteration. A GB frame is frame-locked, so a frame
plays the part of a gameplay tick and `AirPhysics` replays the other 130
iterations (`PHYSICS_STEPS = $82`). That keeps every counter in the source —
`$8C`, the `+10`, the `$FA` apex, the `$28` fall floor — meaning what it meant
there, instead of a pile of re-derived constants. It is the one knob to turn if
the jump feels wrong.

Translated, with the details that were not obvious:

- **Landing** is `BounceWhileInAir` → `CheckBelow` → `LandedOnFloor`, and the
  last of those is the odd one: he only comes to rest when `(y+1) % 8 == 0`,
  i.e. when the sprite snaps to the cell grid. Every other pixel of the fall
  continues.
- **The jump apex costs a move.** `InAirCounter` climbs by 10 per step until
  `$FA + 10` wraps to 4; the step that *detects* that sets
  `PlayerAirDirection = 0` and moves him by 0. So the arc rises **11 px, not
  12** — asserted exactly, because it is derived, not tuned.
- **Mid-air Harry is ballistic.** The horizontal half of the airborne collision
  adds `PlayerJumpDirection` to x with a bounce off the two screen edges and
  **no reference to the tile map at all** — which is why a jump reads as
  committed rather than steerable. Faithful, and it looks wrong until you know
  it is on purpose.
- **Hitting a platform edge mid-flight reverses the drift** (`XOR $FE`), which
  is what makes him skitter along a ledge instead of dropping past it.
- **`ResetTileColours` is dropped entirely.** It rewrites Spectrum attribute
  bytes for a 3×3 block; the GB has one BG palette and no per-cell colour, so
  there is nothing to restore. It is called from four places in the Z80 and
  affects no position.
- `SBC HL,$003F` is `-2*LEVEL_WIDTH + 1`: two rows down and one column *right*,
  sampling under his right foot. Subtracting 64 would have been the obvious
  guess and would have been wrong.
- **`ADD A,[nn]` does not exist on the SM83** — only `ADD A,r`/`ADD A,n8`. Two
  sites needed a register staging.
- **The camera's `x + 8 - 80` overflowed a byte** for x ≥ 248. Written as
  `x - 72` it cannot wrap at all, which matters more than it looks: it is one
  instruction shorter *and* it no longer depends on the game's edge checks to
  stay correct.
- **`-DLEVEL_NUM` silently stopped working in the Phase 3 rewrite** — `Start`
  had been left loading `Level1` unconditionally. `make verify` caught it the
  first time it ran afterwards (levels 2–8 all failed); it now indexes
  `Levels + (LEVEL_NUM-1) * LEVEL_WIDTH * LEVEL_HEIGHT`.

`verify_camera.py` needed a fix of its own once the game was real: it drives
`wPlayerY` directly, and `CheckForFalling` would start a ledge countdown that
turned into a fall and drifted y out from under the case. It now pins
`wPlayerInAir` and ticks a single frame. It also covers `SCX` now, 9 cases
including both clamps.

One honest limit: the ledge path (`PlayerInAir == 1` → countdown → fall) is
exercised by the last test, and the countdown/landing it feeds into by the jump
test, but the *bounce-off-edge* branches inside `BounceWhileInAir` are covered
only by the jump arc passing near them, not by a case aimed at each.

### Phase 2 — done 2026-10-02

> **See the Phase 3 note above: the horizontal numbers in this section are
> wrong.** The map is 256 px wide; the screen is 160. A horizontal camera was
> needed too, and it was added in Phase 3.

**Decided: 1:1 with a vertical camera.** The screenshots made this easy — the
deciding number is that the playfield is 21 rows (168 px) and the screen shows
18 (144 px), so the camera's entire travel is **24 px** and the only thing ever
hidden is the birdcage band at the top, which Harry reaches by ladder anyway.
A 4×4 demake would fit everything but resizes every coordinate away from the
Z80 source's units, which is the whole reason Phase 3 is cheap; redesigning the
levels abandons the original layouts. Both costs are permanent, the crop is
24 px.

`UpdateCamera` runs from the VBlank handler and reads `wPlayerY`:

```
SCY = clamp(96 - y, 0, 24)
```

`wPlayerY` is deliberately in the **game's own Cartesian units** — 0 at the
bottom of the playfield, increasing upwards — so Phase 3's translated physics
writes it with no conversion at all. The camera is a pure function of it.

`tools/verify_camera.py` drives `wPlayerY` directly through PyBoy and reads
`SCY` back, over 10 cases including both clamp boundaries (y=72 is the last
value pinned to the bottom, y=96 the first pinned to the top). A camera that
mishandles the clamp only misbehaves at the top and bottom of the playfield,
which is exactly where a screenshot is least likely to catch it.

Also new: `tools/verify_camera.py` reads `chuckie.sym` (`BB:AAAA Name`) for the
`wPlayerY` address. That symbol-map lookup is the general facility the Phase 3+
assertions want — assert against named variables instead of hard-coded WRAM
addresses that silently go stale.

**This is the last phase that could have invalidated the plan.** Everything from
here is game logic in units the Z80 source already uses.

### Phase 0 — done 2026-10-02

Layout: `src/main.asm`, `src/hardware.inc`, `Makefile`, `tools/shot.sh`,
`.gitignore`. Builds a 32 KB ROM-only cart, title `CHUCKIE`.

Verified **byte-exact in VRAM via PyBoy**, not by eye:
- BG map (1024 bytes) matches the intended pattern exactly — 0 differing cells
- single-cell addressing works (4×4 marker of tile 5 painted at map cell 8,6)
- tile data landed at `$8000` (tile 1 = `FF 00` ×8)
- `LCDC=$91` (on | BG at $8000 | BG on), `BGP=$E4`

Facts worth keeping:

- **`rgbfix -v` inserts the Nintendo logo and fixes both checksums.** No logo
  bytes needed in source; the `ds $150 - @, 0` header gap is enough.
- **RGBDS ships no `hardware.inc`** — we define our own in `src/hardware.inc`.
  `INCLUDE` resolves via `rgbasm -I src`.
- **PyBoy's boot ROM takes ~66 frames.** Our own screen is up at **frame 67**,
  so any screenshot or assertion must tick past that. Use `FRAMES=120` or more.
  A 60-frame shot shows PyBoy's own splash, not the game — the first attempt here
  made exactly that mistake. PyBoy does accept `bootrom` / `bootrom_file`, so the
  boot can be skipped later if deterministic frame-0 timing is ever wanted.
- `tools/shot.py` is the headless screenshot tool (language-agnostic — it takes
  any ROM path). It lives in the repo so that a checkout builds and shoots with
  nothing but PyBoy installed; `make shot` runs it as `$(PY) tools/shot.py`.

## Open decisions

**None.** Both are settled — 1 in Phase 2 (1:1 + camera, re-confirmed in Phase 4
with the price measured) and 2 on 2026-10-03. Kept here as the record of what was
asked and answered.
1. ~~**Playfield scale**~~ — **settled in Phase 2: 1:1 + camera**, and
   **re-confirmed in Phase 4 with the price known**: the measured cost (below)
   was put to the user and 1:1 was chosen over the demake. The camera keeps
   sliding and the level keeps its original geometry and its byte-exactness.

   The cost that was accepted with it: at the spawn the port then had (x=$AE),
   the window started at x=96 and level 1's second hen (x=72) began behind Harry
   — on screen 5% of the time against 72% for the other. Judged a *level design*
   wrinkle rather than a reason to change the geometry, and left alone
   deliberately: the level data is verified byte-for-byte against the Z80
   source, and moving a hen's spawn is the first change that would break that
   claim (it needs a carve-out in `verify_hens.py`, which asserts the spawns
   *against the source*). **That cost is gone as of 2026-10-03** — not by moving
   a hen, but because the spawn was the wrong one: at PlayLevel's x=100 the
   camera sits at SCX=28 and both hens are in view. See "Harry's spawn".
2. ~~**Eggs as background tiles, not sprites**~~ — **settled 2026-10-03, and it
   is not a workaround: it is what the Z80 does.** `PlayerPickUp`
   (`Chuckie.asm:2241-2245`) reads the cell under Harry with
   `GetMapAddressAndChar`, compares it to `TILE_EGG` (`$03`) and clears it with
   `LD (HL),TILE_BLANK` (`$00`). An egg *is* a level-map byte — the same `$03`
   the port's level data carries and its Phase 1 self-check asserts as the egg
   bitmap — so eggs were never sprites to begin with, and the flicker limit is
   not something they dodge. Nothing to revisit: there is no egg animation
   counter in the source to miss (`MotherDuckFrame` is the only one).

## Toolchain

Nothing left to install.

| Tool | Where | Role |
|---|---|---|
| RGBDS 1.0.4 | brew, on PATH | assembly toolchain |
| PyBoy 2.7.0 | a venv (not system `python3`) | automated headless loop |
| mGBA 0.10.5 | `/opt/homebrew/bin/mgba` | hands-on play-testing |
| binjgb (WASM) | a local build | in-browser smoke test |

Headless screenshot (language-agnostic — it takes any ROM path):

```
tools/shot.py rom.gb out.png 120 ...RRA
```

One char per frame: `.` none, `R/L/U/D` d-pad, `A B` buttons, `S T` START/SELECT.

**PyBoy is a dev loop, not a verdict.** Do a final accuracy pass in mGBA or on
real hardware before calling anything done.
