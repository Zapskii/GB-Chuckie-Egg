; Chuckie Egg (Game Boy) -- Phase 6a: the status row and the level timer.
;
; Renders a level at 1:1 with a camera that follows Harry on both axes, moves
; him through it with the rules translated from the Z80 source, runs the hens
; that kill him, and shows score, eggs, time and bonus across the top. See
; PLAN.md.
;
; Geometry, all of it settled from the Z80 source rather than guessed:
;
;   * The level is 32 cells wide x 21 tall. Tile ids drop in with no
;     conversion: Spectrum tile id == GB tile index.
;   * That is the width of the GB BG MAP, but NOT of the screen: the map is
;     256 px and the visible window is 160, so 96 px of the level is off screen
;     and a horizontal camera is required, not optional. Vertically 21 rows
;     (168 px) against a 144 px window leaves only 24 px to scroll.
;   * Level data row 0 is the FLOOR, row 20 the ceiling: the buffer is stored
;     bottom-up. GetCharAddress (Chuckie.asm:1646) computes
;     LevelBuffer + (y/8)*32 + (x/8), so map index rises with the game's y.
;   * The game's y is Cartesian: 0 at the bottom of the playfield, 168 px tall.
;     Screen row from the top of the playfield is therefore 167 - y.
;   * PlayerY is the TOP of Harry's 16x16 sprite, so he spans rows y/8 and
;     y/8-1, and the floor he stands on is row y/8-2 (CheckForFalling:6310
;     subtracts 63 from (row y/8, col x/8) to land on exactly that cell).
;   * He is 16x16, drawn from a table at gfx_PlayerRight indexed n*32.

INCLUDE "hardware.inc"

; Generated data. Included up here so every DEF below is already available.
INCLUDE "tiles.asm"
INCLUDE "levels.asm"
INCLUDE "sprites.asm"
INCLUDE "hens.asm"
INCLUDE "henstarts.asm"
INCLUDE "font.asm"
INCLUDE "music.asm"
INCLUDE "title.asm"
INCLUDE "score.asm"
INCLUDE "duck.asm"

; SCY the camera settles on at Harry's spawn, which is where tools/verify.py
; samples it. UpdateCamera computes it; this is the expected value.
IF !DEF(CAMERA_Y)
DEF CAMERA_Y EQU 32
ENDC
; Which level the ROM boots into, i.e. the counter's starting value. Only the
; boot: everything downstream reads wCurrentLevel, which level flow moves at
; runtime, so this is how you look at another level from a cold start:
;   make level N=25
; Any N works, the levels past the eighth included: the counter has no bound
; (the Z80's `INC (HL)`, Chuckie.asm:4434) and only the per-level table lookups
; mask it with `AND $07` (PLAN.md, "The five laps").
; Not `make ASMFLAGS=-DLEVEL_NUM=5`: that builds $(ROM) itself, and the flag
; is not in any timestamp, so a later plain `make` relinks nothing and leaves
; the default ROM booting into level 5.
IF !DEF(LEVEL_NUM)
DEF LEVEL_NUM EQU 1
ENDC

; PlayerDirection values, straight from the Z80.
DEF DIR_RIGHT EQU $00
DEF DIR_LEFT  EQU $04
DEF DIR_CLIMB EQU $0D

; The Z80's main loop is free-running, but the gameplay block is gated on
; SoundTimer, which reloads to $82 (Chuckie.asm:2052). So the game advances one
; gameplay tick every 130 raw iterations, while the in-air vertical physics
; (CollideWithWorld's NotInAir path) runs on EVERY iteration. Our loop is
; frame-locked instead, so a frame plays the part of a gameplay tick and
; AirPhysics replays the other 130 iterations.
;
; This is the one number to turn if the jump does not feel right: it is the
; original's own constant, not a guess, but it assumes a Spectrum iteration
; costs what an average one did, and ours are cheaper because we never draw
; from here.
DEF PHYSICS_STEPS EQU $82

; The horizontal camera's full travel: the playfield is 32 cells = 256 px and
; the visible screen is 160, so SCX runs 0..96.
DEF SCX_MAX EQU 256 - 160

; Eggs to collect. The Z80 loads this as a constant, it does not count the eggs
; it drew. `ONLY_ONE_EGG` is in the source as a cheat; neither is needed here.
DEF EGGS_PER_LEVEL EQU $0C

; Sprite tiles live above the level tiles, which the level never references.
DEF HARRY_TILE_BASE EQU TILE_COUNT
DEF HEN_TILE_BASE   EQU HARRY_TILE_BASE + HARRY_FRAMES * HARRY_FRAME_TILES
DEF LIFT_TILE_BASE  EQU HEN_TILE_BASE + HEN_FRAMES * HEN_FRAME_TILES
; The status row's glyphs, generated to src/font.asm. Two tiles are left
; between the lifts (which use one) and the font so the bases are not adjacent
; -- nothing depends on the gap, it just leaves room to breathe.
DEF HUD_TILE_BASE   EQU LIFT_TILE_BASE + 2

; The title screen's two runs, after the status row's glyphs. The glyphs are
; only the characters the title's own lines use, in ASCII order (src/title.asm
; emits the count), and the logo is the Z80's $7F-$8A block out of TitleText.
DEF TEXT_TILE_BASE  EQU HUD_TILE_BASE + HUD_TILE_COUNT
DEF LOGO_TILE_BASE  EQU TEXT_TILE_BASE + TITLE_GLYPH_COUNT

; The high-score screen's run, last: the glyphs its own strings and scores use,
; the alphabet inverted for the grid cursor, and the Z80's default-name banner.
; One contiguous run, so Start copies it with one MemCopy.
DEF SCORE_TILE_BASE EQU LOGO_TILE_BASE + TITLE_LOGO_COUNT

; The mother duck, after everything else: two 16x16 frames, one a facing. It is
; the last thing in VRAM, 8 tiles off the end of the score run.
DEF DUCK_TILE_BASE  EQU SCORE_TILE_BASE + SCORE_TILE_COUNT

; The nine characters the Z80 lets a name be (`CP $19` against an L running
; $10..$18) and how long a cursor phase lasts, in frames.
DEF SCORE_MAX_NAME EQU 9
DEF SCORE_BLINK    EQU 20

; The lifts (the Z80 calls them elevators -- Chuckie.asm:1985). A countdown
; reloads to 2, so a platform rises one pixel every 2 gameplay ticks; two of
; them share a column, 64 px apart, and each wraps back to YPos 3 on its own
; when it passes 165, which keeps the spacing at 64 for good.
DEF LIFT_SPEED   EQU 2
DEF LIFT_HOME    EQU 3           ; YPos after a wrap
DEF LIFT_TOP     EQU $A6         ; YPos at or above this wraps
DEF LIFT_OFFSET  EQU 64          ; the second platform's head start
DEF LIFT_STAND   EQU 17          ; PlayerY = YPos + this, on landing
DEF LIFT_HALF    EQU 9           ; the x band is lift_x-9 .. lift_x+9
DEF LIFT_NONE    EQU $FF         ; a level with no lifts
DEF LIFT_CEILING EQU $A5         ; PlayerY at or above this ends the tick
DEF LIFT_OAM     EQU 4 + HEN_MAX * 4   ; platform OAM entries come after the hens
DEF LIFT_OBP     EQU $10         ; attribute bit 4: drawn with OBP1, like the hens

; Hen directions, from the Z80's own equates (Chuckie.asm:40-48). Pecking is
; dir + HEN_PECK, so a hen carrying birdseed has 7 (left) or 8 (right); 6 is
; only the threshold the state machine tests against.
DEF HEN_LEFT  EQU 1
DEF HEN_RIGHT EQU 2
DEF HEN_DOWN  EQU 3
DEF HEN_UP    EQU 4
DEF HEN_PECK  EQU 6
DEF HEN_NONE  EQU $FF            ; an empty slot's x

; HenUpdateSpeed (Chuckie.asm:2130). It is a countdown inside the same gameplay
; tick everything else here runs on: it reloads to 3, and each expiry calls
; MoveAndDrawHens once, which advances exactly ONE hen of the five slots. So a
; given hen moves 4px every 3 * 5 = 15 frames -- much slower than it looks in
; the source, and the number to change if the hens feel wrong.
DEF HEN_SPEED EQU 3

; How long to freeze after a hen kills Harry, before the level restarts. The
; Z80 unwinds its call stack here; lives and a proper respawn are Phase 5.
; It is also how long an announcement on a death stays up -- the Z80's
; ScrollTextLine is the same pause, spent on a cleared screen instead of the
; frozen level.
DEF DEATH_DELAY EQU 90

; How long a level's own announcement ("LEVEL n") stays up as the next one is
; loaded. The Z80 sweeps the word in a pixel at a time, 8 pixels a character
; over 8 characters, which is a beat and not a wait.
DEF NOTICE_HOLD EQU 25

; --- the mother duck -------------------------------------------------------
; The big bird in the cage. The Z80 runs MotherDuckUpdateCounter (Chuckie.asm:
; :2093) down from $0C and then calls MoveMotherDuck, so the duck moves on every
; twelfth gameplay tick -- a GB frame here, as everything else's rate is.
DEF DUCK_SPEED EQU $0C

; MoveMotherDuck's own bounds (:3439) and ceiling. x is refused at $EE and at
; the bottom of the byte, y at $14 and $A6; the test is on the RESULT, so the
; duck turns on the update that would have left the range rather than the one
; after. Velocity steps one per update toward the player, saturating at ±5.
DEF DUCK_X_MAX   EQU $EE
DEF DUCK_Y_MIN   EQU $14
DEF DUCK_Y_MAX   EQU $A6
DEF DUCK_VEL_MAX EQU 5

; Where the Z80 plants it on any level below the eighth (:3466: `LD HL,$9808`,
; re-stored every single update), and the level index that ends the planting.
; $9808 is x 8, y $98 -- the level's own coordinates, so the duck sits in the
; cage with its 16x16 box (x 8..23, y 152..167) on the cage's top two rows.
DEF DUCK_CAGE_X     EQU 8
DEF DUCK_CAGE_Y     EQU $98
; The plant ends here: caged while the counter is BELOW this, loose from it.
; It is the Z80's own operand (`CP $08`, :3462-3466) on a 0-based counter, so
; this is level 9 -- not 8. The port had 7, i.e. she was loose a level early,
; which only the unbounded counter could fix (PLAN.md, "The five laps").
DEF DUCK_FREE_FROM  EQU 8

; The duck's OAM entries, after Harry's four and the hens' twenty. Leave FOUR
; for the lifts, not two: each of the two platforms is two 8x8 halves, so the
; lift entries are LIFT_OAM..LIFT_OAM+3 and the duck starts past all of them.
; At LIFT_OAM+2 the duck's top half shared entries 26/27 with the second
; platform, which DrawLifts writes every frame -- so on the five lift levels the
; bird was drawn as its bottom half only. Invisible on level 1, which has no
; lifts, which is where it was last looked at.
DEF DUCK_OAM EQU LIFT_OAM + 4

; Harry's starting position. y is Cartesian, x is the sprite's left edge.
;
; $64/$17 is not the Z80's initial variable block (Chuckie.asm:155-158, which
; says $AE/$37) -- it is what PlayLevel OVERWRITES that block with at :6110, and
; PlayLevel runs at every level start including the first, with no branch that
; skips it. So it is the game's spawn, and $AE/$37 was the program image's.
; The two are both legal ground: $37 stands on a platform five rows up, this
; stands on the level's own floor. Checked as pixels, not assumed -- at (100,23)
; the first drawn row below his sprite is the floor tile, on every level.
;
; Overridable, so the other pair can be compared:
;   make ASMFLAGS='-DHARRY_START_X=174 -DHARRY_START_Y=55'
; Decimal, not $AE/$37: make reads the $A in $AE as its own variable and drops
; it, so the hex form builds 4/7 -- the bottom corner of the level.
IF !DEF(HARRY_START_X)
DEF HARRY_START_X EQU 100
ENDC
IF !DEF(HARRY_START_Y)
DEF HARRY_START_Y EQU 23
ENDC

; --- the status row --------------------------------------------------------
; One 8px band pinned to the top of the SCREEN, drawn with the window layer --
; the only thing on the DMG that does not scroll. The window shares the BG map
; unless LCDCF_WIN9C00 is set, so it is set and the HUD lives alone in map 1 at
; $9C00; BG map 0 keeps the level exactly where it was, at map rows 0..20.
;
; The window covers the band and nothing below it: switched ON in VBlank, OFF
; again by the STAT handler the moment LY reaches HUD_ROWS*8, which also
; switches OBJ off for those lines -- sprites are drawn over the window, so the
; band has to hide them too or they poke out of the status row. The window's
; tilemap row for scanline LY is LY - WY, so the band is map 1's rows 0..HUD_ROWS-1.
;
; The band takes HUD_ROWS*8 px off the top of the playfield, which is why the
; playfield moves down the map by the same amount (PLAYFIELD_ROW0) and the
; camera's travel grows to match (SCY_MAX): level pixel p is now at map pixel
; p + HUD_ROWS*8, so it lands on screen line p + HUD_ROWS*8 - SCY, and SCY 0
; shows the level's first pixel at line 8. Without the shift the level's top
; row could never be reached, because SCY cannot go negative. See PLAN.md.
DEF HUD_ROWS      EQU 1
DEF HUD_WY        EQU 0
DEF HUD_WX        EQU 7          ; the window's left edge at screen x = 0
DEF HUD_SPLIT_LY  EQU HUD_ROWS * 8
DEF HUD_MAP       EQU $9C00      ; BG map 1, reserved for the HUD
DEF PLAYFIELD_ROW0 EQU (LEVEL_HEIGHT - 1 + HUD_ROWS) * LEVEL_WIDTH
; The camera's vertical travel: the level's 168 px less the 144 - HUD_ROWS*8
; the band leaves visible.
DEF SCY_MAX EQU LEVEL_HEIGHT * 8 - (144 - HUD_ROWS * 8)

; --- where a level pixel lands on a screen line ----------------------------
; Level pixel p, counted from the level's bottom, is drawn on screen line
; PLAYFIELD_ROW_BASE - p - SCY. The BG path realises this through PLAYFIELD_ROW0's
; map arithmetic rather than by computing it; the number is named here because
; everything drawn as a sprite has to agree with it. 167 is the pre-band value:
; the camera pins to the bottom at SCY 24, where the level's bottom pixel (p=0)
; must land on line 143, so the base is 143 + 24. The band displaces the
; playfield by HUD_ROWS*8, and the base grows by the same amount.
DEF PLAYFIELD_ROW_BASE EQU 167 + HUD_ROWS * 8

; An OAM row is NOT a screen line: the hardware draws a sprite whose OAM row is
; Y at lines Y-16 .. Y-1. So a sprite's top edge lands on screen line
; OAM_ROW_BASE - y - SCY, and to share the playfield's geometry that base is
; the playfield's own plus the offset's 16 lines. Harry's y is the top of his
; 16x16 sprite, so his top edge lands on the line level pixel y is drawn on --
; which is what "standing on a tile" means here, and why y is not the tile's own
; coordinate.
;
; THIS COUPLING IS THE BUG 6a SHIPPED. The band moved PLAYFIELD_ROW_BASE by 8
; and left the sprite literal at its old value, so Harry, the hens and the lifts
; all floated exactly 8 px above the tiles -- visible in a second, invisible in
; every check, because they all recomputed the same wrong constant. If the band
; ever changes size, both bases move together or neither does.
DEF OAM_ROW_BASE EQU PLAYFIELD_ROW_BASE + 16

; A hen's record is anchored at its FEET, not at its head. HenStarts' y is the
; level pixel the hen stands on, so its sprite occupies y .. y+15 and its top
; edge is 15 lines above where Harry's formula would put it for the same number.
; Harry's PlayerY is his sprite's TOP, which is why the two need different bases
; -- and using his here sank every hen 15 px into the platform it was walking on,
; with its head where its body should be. Play-testing found it (it is invisible
; on flat ground and obvious on a platform); the spawn data proves it: read as
; the feet, 21 of the 26 hen starts across the eight levels stand exactly on a
; platform or a ladder cell at row (y-1)/8, and read as the head none of them do.
DEF HEN_OAM_ROW_BASE EQU OAM_ROW_BASE - 15

; The same offset, one axis over. A sprite whose OAM column is X draws at screen
; columns X-8 .. X+7, and level pixel x is drawn at screen column x - SCX (with
; no column base constant -- the map's column 0 is the level's column 0). So a
; sprite whose LEFT EDGE is at level pixel x needs OAM column x - SCX + 8.
;
; PlayerX is a left edge, not a centre: the Z80's DrawSpriteNum draws its 16x16
; buffer at the screen cell x>>3 shifted by (x & 7), which puts the sprite's
; left edge on pixel x. A row gets its offset for free inside OAM_ROW_BASE; a
; column has to be added, and for a long time it was not -- every sprite sat
; 8 px left of the map. It showed on a two-cell ladder, where Harry should
; cover both cells and instead hung off the left one.
DEF OAM_COL_OFFSET EQU 8

; The OAM the port uses: the duck's slot is the last one it writes, so the
; shadow only has to cover that far.
DEF OAM_BYTES EQU (DUCK_OAM + 4) * 4

; A platform's deck (a lift is an elevator -- Chuckie.asm:1985). Standing on one
; puts PlayerY at YPos + LIFT_STAND, so his feet sit 15 lines below his top; the
; deck must be drawn on that line, which is two rows above where a player
; sprite with the same y would put its own OAM row (LIFT_STAND - 15 = 2).
DEF LIFT_ROW_BASE EQU OAM_ROW_BASE - 2

; LCDC as the ROM wants it everywhere the LCD is switched on. WIN9C00 chooses
; map 1 for the window; WINON is what the STAT handler clears each frame.
DEF LCDC_BASE EQU LCDCF_ON | LCDCF_BG8000 | LCDCF_BGON | LCDCF_OBJON | LCDCF_WIN9C00 | LCDCF_WINON

; --- the timer -------------------------------------------------------------
; Two counters, not one, and they are easy to conflate. DecreaseTimerOrBonus
; (Chuckie.asm:3491) is called with B=0 and B=1; B=0 takes HL = Bonus+2 and
; B=1 takes Bonus+5 = TimeRemaining+2, so B=0 steps the BONUS and B=1 the
; TIME. The two call-site comments say the opposite -- they are swapped, and
; so is the one on the level-completion drain. The code is the truth.
;
;   Bonus          drained into the score at level completion
;   TimeRemaining  a clock, never scored
;
; Cadence: FiftiesCounter reloads to 50 and steps Bonus, TensCounter to 10 and
; steps TimeRemaining. Both are reset to 1, not to their reload value, so the
; first step lands on the first tick of a level.
DEF TIMER_BONUS_STEP EQU 50
DEF TIMER_TIME_STEP  EQU 10
DEF TIMER_UNDERFLOW  EQU $FF     ; what a digit holds after borrowing out

; Lives at the start of a game. The Z80 sets 5 in two places that must agree
; (LivesSet and PressStart's start-up block, Chuckie.asm:4346 and 4257); this is
; the one place, and NewGame is the only caller.
DEF LIVES_START EQU 5

; --- sound -----------------------------------------------------------------
; The tunes are the source's own byte streams (src/music.asm) and the driver is
; ours: the Spectrum's BEEP blocks for a note's whole length, which a Game Boy
; cannot do without stopping the game, so the note is started and the frame
; count is carried in wMusicTimer instead.
;
; A duration byte is in BEEP units and means `10 / duration` of them (PlayMusic
; divides by it); NOTE_UNIT turns one of those units into frames. This is the
; one number in 6b that is a judgement rather than a translation -- the source
; says nothing about how long a beep unit is in wall-clock terms -- so it is
; named, in one place, and the ear test in mGBA is what tunes it. At 6 the
; title tune's quarter notes are 60 frames and its eighths 30, i.e. a note or
; two a second.
DEF NOTE_UNIT EQU 6

; The effects: one noise blip on channel 4, so a pickup never eats the tune on
; channel 1. SFX_LEN frames long, sliding up from SFX_FREQ while the channel's
; own envelope takes the volume down.
DEF SFX_LEN  EQU 8
DEF SFX_FREQ EQU $4A

; ---------------------------------------------------------------------------
; Header. rgbfix fills in the logo and checksums.
; ---------------------------------------------------------------------------
SECTION "Header", ROM0[$100]
    nop
    jp Start
    ds $150 - @, 0

; ---------------------------------------------------------------------------
; Variables. Harry's y is the game's own Cartesian coordinate, in the same
; units as the Z80 physics, so the translated movement code needs no scaling.
; ---------------------------------------------------------------------------
SECTION "Variables", WRAM0
wPlayerX:             db
wPlayerY:             db
wPlayerAnimFrame:     db
wPlayerDirection:     db
wInAirCounter:        db
wFallingCounter:      db
wPlayerAirDirection:  db
wPlayerInAir:         db       ; 0 = on the ground, 2 = in the air
wPlayerJumpDirection: db       ; $01 right, $FF left
wPad:                 db       ; this frame's buttons, see ReadButtons
wPadNew:              db       ; ...and the ones that went down on this frame

; The level is copied here rather than read from ROM, because picking up eggs
; and corn mutates it. Addressing is then identical to the Z80's LevelBuffer.
SECTION "LevelRAM", WRAM0
wLevelBuffer:         ds LEVEL_WIDTH * LEVEL_HEIGHT

; The hens. Four bytes a slot, exactly the Z80's Hen1..Hen5 record layout
; (x, y, direction, frame), so the translated state machine indexes it the way
; the original does. A slot is unused when its x is HEN_NONE.
wHens:                ds HEN_MAX * 4
wCurrentHen:          db          ; round-robin slot, 0..HEN_MAX-1
wHenTick:             db          ; counts down to the next hen update
wHenFrameCtr:         db          ; low byte of the Z80's FrameCounter
wHenGate:             db          ; the Z80's mem[Counter] byte -- see UpdateHens

; The hen the update is currently working on, unpacked. The Z80 keeps these in
; registers; we keep them here because GetMapAddr wants D and E.
wHenX:                db
wHenY:                db
wHenDir:              db
wHenAnim:             db          ; the record's 4th byte; our walk-cycle toggle
wHenProbe:            db          ; scratch: the row a side probe should look at
wHenSlot:             dw          ; address of that hen's record

; The drawing's own copy of the unpacked hen. DrawHens runs from the VBlank
; handler and UpdateHens from the main loop, and VBlank can fire part way
; through an update -- sharing the scratch above would then draw one hen from
; another's values, intermittently. Four bytes is the whole cost of not doing
; that.
wDrawX:               db
wDrawY:               db
wDrawDir:             db
wDrawAnim:            db

wPlayerDead:          db          ; set by CollidePlayerAndHen
wDeathTimer:          db          ; counts the freeze out

; The mother duck. It is one entity, so it needs none of the hen block's
; unpacked scratch: the draw reads these two bytes and VBlank catching an
; update part way through costs one frame of a 5px diagonal, once every
; DUCK_SPEED. (The hens needed wDrawX.. above because five of them share the
; unpacking, and a torn read there drew one hen from another's values.)
wDuckX:               db          ; left edge, as Harry's x is
wDuckY:               db          ; top of the sprite, as Harry's y is
wDuckVelX:            db          ; signed, -5..5
wDuckVelY:            db
wDuckFace:            db          ; 0 facing right, 1 facing left
wDuckFrame:           db          ; 0 wings down, 1 wings up -- toggled an update
wDuckTick:            db          ; counts down to the next duck update

; Lives left, counting the one being played -- unlike the Z80, which draws
; lives-1 hats because its last hat stays blank. Set once per GAME (the Z80
; sets it in PressStart and only ever decrements it), so it is reset by NewGame
; and by nothing that runs per level.
wLives:               db

; The title screen is up. The ROM boots into it, a START press leaves it, and
; the last life spent returns to it -- the Z80's FrontEnd. While it is set
; there is no level loaded: the VBlank handler draws nothing, the tick does not
; run, SCY and SCX stay at 0, and OBJ is switched off.
wOnTitle:             db

; The high-score table is up. Its own flag rather than another value of
; wOnTitle's, so 6c-2's meaning of that one does not move: the two screens are
; mutually exclusive, and "a front end is up" is either of them.
wOnScores:            db

; The instructions are up -- the Z80's `I` at the front end (TestKeys,
; Chuckie.asm:4113), on SELECT here because a DMG has no I key. A third flag on
; the same principle as wOnScores: the three front-end screens are mutually
; exclusive and nothing else reads wOnTitle's meaning.
wOnInstr:             db

; An announcement is on screen -- ShowNotice's blank screen with one line of
; text on it. Not a front end: nothing waits on input, and it is up for a fixed
; number of frames inside the routine that raised it. What it does for the
; VBlank handler is stop the game's draw pass, which would otherwise put the
; camera, the status row and the sprites back over the top of it.
wOnNotice:            db

; The level's number as the notice's two digit cells hold it, glyph indices in
; the score run, written by SetLevelDigits when a notice goes up. The Z80 keeps
; the same pair in its own text buffer (`LevelDig1`/`LevelDig2`,
; Chuckie.asm:5633-5636) and patches them in place; the record here is ROM, so
; they live in WRAM and the fill reads them. The tens byte is the blank glyph
; below level ten.
wLevelTens:           db
wLevelUnits:          db

; The table itself: SCORE_COUNT entries of a 10-byte name field and five score
; digits. The name bytes are indices into this screen's glyph run -- index 0 is
; the space glyph and the Z80's banner is indices in its own right, because it
; lives in the same run -- so nothing here is ASCII and nothing is converted.
; The digits are wScore's own layout, most significant first.
wHighScores:          ds SCORE_COUNT * SCORE_ENTRY_BYTES

; The name entry. wNameEntry is the rank being typed, 1..10, or 0 when the
; score did not make the table at all; wNamePos is how many characters are in
; it; (wGridRow, wGridCol) is the cursor in the alphabet panel.
wNameEntry:           db
wNamePos:             db
wGridRow:             db
wGridCol:             db
wBlinkCtr:            db          ; counts down to the next cursor phase
wBlinkOn:             db          ; ...which is what it toggles
wScoreDirty:          db          ; set by a change, cleared by the redraw
wNameDone:            db          ; START has been pressed; leave the typing

; The Z80's CurrentLevel (Chuckie.asm:120), 0-based -- level 1 is 0 -- and with
; no bound: every lap past the eighth is a higher value, not a wrap. Only the
; per-level table lookups mask it to `AND $07`; the rules that change per lap
; (the duck's cage, the hens, their speed) read the counter itself. LEVEL_NUM
; only chooses the value the ROM boots with.
wCurrentLevel:          db
wLevelDone:           db          ; set when the last egg goes; the loop advances

; Eggs and score. Twelve a level, a constant in the Z80 rather than a count of
; what is drawn (Chuckie.asm:4484, `LD A,$0C`).
wEggsRemaining:       db

; Six digits, one per byte, units at wScore+4 -- the Z80's CurrentPlayerScore
; layout, which AddToScore carries through. Only five are ever shown.
wScore:               ds 6

; The score as it stood when the level began -- the Z80's per-player P1Score.
; PlayLevel copies it into the live score at the start of a level,
; LevelCompleted copies it back out when the level is won, and
; HasLivesRemaining copies it in again on a death. That last one is the rule
; that dying costs the points earned on the fatal attempt. One player here, so
; one copy, and it sits next to wScore so ResetScore zeroes both -- and
; wLastDigit after them -- in one loop.
wScoreSaved:          ds 6

; The score's thousands digit as it stood when a life was last granted, the
; Z80's LastDigitValue (Chuckie.asm:308). AddToScore compares the digit against
; it and pays a life only when they differ, which is what makes the extra life
; fire once per 1 000 points rather than once per point. LoadSavedScore re-syncs
; it, so a level start never pays.
wLastDigit:           db

; A map cell blanked this tick, waiting to be written to the BG map. The tick
; runs in the visible part of the frame (see MainLoop), where VRAM is not
; addressable, so the write is handed to the VBlank handler.
wPickupAddr:          dw
wPickupDo:            db

; The lifts. wLiftX is the level's platform column, or LIFT_NONE; both
; platforms are on it, one LIFT_OFFSET above the other, so one byte holds it.
wLiftX:               db
wLiftYPos:            ds 2        ; the two platforms' height, in pixels risen
wLiftTick:            db          ; counts down to the next lift update
wPlayerOnLift:        db          ; $01 while Harry is riding one

; The status row, as tile indices, mirrored into the window's map row every
; VBlank. Built in the visible part of the frame, not in the handler: the whole
; row is rewritten each frame, so there is no dirty flag to get wrong, and it
; is only the copy to VRAM that has to happen in VBlank.
wHudRow:              ds HUD_ROW_LEN

; The OAM image, built and copied the same way and for a stronger reason: the
; per-sprite work -- the camera transform, the pose, four bytes an entry -- is
; far more than a VBlank holds once a level has four hens (measured: the draw
; pass ran 2900 cycles past the window on level 6, so the last entries written
; were a frame late). The copy is not. Everything the tick changes reaches the
; screen through here, so nothing in the draw path has to know it is early.
wOamShadow:           ds OAM_BYTES

; The camera, as UpdateCamera worked it out on the frame's own Harry. rSCX and
; rSCY can only be written in VBlank -- a write partway down the visible frame
; shifts the rest of that frame sideways -- but the sprites are drawn from the
; camera in the visible part, so it is computed there and committed here. Both
; halves in one frame, or Harry would sit a pixel off his own background.
wScrollX:             db
wScrollY:             db

; The two counters, one decimal digit per byte, hundreds first -- the Z80's
; own layout. wBonus is the one drained into the score when the level ends;
; wTime is a clock and is never scored.
wBonus:               ds 3
wTime:                ds 3
wBonusTick:           db          ; divider for wBonus; reloads to TIMER_BONUS_STEP
wTimeTick:            db          ; divider for wTime; reloads to TIMER_TIME_STEP
wTimerRunning:        db          ; gates the bonus countdown, as the Z80's does
wTimeUp:              db          ; set when wTime borrows out; 6c reads it

; The tune. The stream pointer is the whole of "is it playing": a ROM address
; while it is, zero once the terminator is read, since no stream lives at 0.
wMusicPtr:            dw          ; the next (duration, pitch) pair
wMusicTimer:          db          ; frames left before the next note
wMusicPeriod:         dw          ; the period last written, for the check: the
                                  ; APU's own period bits are write-only

; The one-shot effect. Channel 4, so it never eats the tune.
wSfxTimer:            db          ; frames left in the blip
wSfxFreq:             db          ; the blip's starting rNR43 value

; ---------------------------------------------------------------------------
; The interrupt vectors. Each is eight bytes wide, which the handlers have long
; since outgrown, so each vector is a jump and the body lives with the rest of
; the code.
; ---------------------------------------------------------------------------
SECTION "VBlankVector", ROM0[$40]
VBlank:
    jp HandleVBlank

SECTION "StatVector", ROM0[$48]
Stat:
    jp HandleStat

; ---------------------------------------------------------------------------
; STAT handler. Fires once a frame, when LY reaches HUD_SPLIT_LY, and all it
; does is switch the window off -- so the status row covers scanline 0 and the
; playfield gets the rest. VBlank switches it back on.
;
; rLYC and rSTAT are written once in Start, with the LCD off: writing either
; with the LCD on can raise a spurious STAT interrupt on the DMG.
;
; It touches nothing the VBlank handler also touches, so the two cannot race
; each other's state -- but like that one it does not run to completion before
; the main line resumes around it, so it saves what it uses.
; ---------------------------------------------------------------------------
SECTION "Handlers", ROM0

HandleStat:
    push af
    ldh a, [rLCDC]
    bit 5, a                 ; LCDCF_WINON: is the band up at all this frame?
    jr z, .done              ; no -- the front end is all BG and has no sprites
    and ~LCDCF_WINON
    or LCDCF_OBJON           ; sprites come back with the playfield
    ldh [rLCDC], a
.done
    pop af
    reti

; ---------------------------------------------------------------------------
; VBlank handler. Everything that touches VRAM or OAM has to happen here.
;
; It saves the registers it uses and the main line's too, because it does not
; only interrupt the main loop's idle wait: the tick runs from the start of the
; visible frame, and a long stretch of main-line work -- DrainBonus at level
; completion is one -- runs straight through a frame boundary and is resumed
; with whatever this left in AF, BC, DE and HL. Without the saves, a drain that
; crosses a VBlank comes out with its digit registers scrambled.
; ---------------------------------------------------------------------------
HandleVBlank:
    push af
    push bc
    push de
    push hl

    ; The front end -- the title, the high-score table and the instructions: the
    ; tune, and nothing else. Everything below describes a level -- the camera
    ; follows a Harry who is not there, and the status row belongs to a game that
    ; has not started. The window bit is left alone too, so the screen stays
    ; entirely BG. An announcement is the same case for the same reason: it is a
    ; screen of its own, and none of the draw pass belongs on it.
    ld a, [wOnTitle]
    ld hl, wOnScores
    or [hl]
    ld hl, wOnInstr
    or [hl]
    ld hl, wOnNotice
    or [hl]
    jr z, .playing
    call UpdateMusic
    call UpdateSfx
    jr .done

.playing
    ; A cell blanked during the tick, if there is one. It has to be written
    ; here: VRAM is not addressable in the visible part of the frame, which is
    ; where the tick deliberately runs.
    ld a, [wPickupDo]
    and a
    jr z, .draw
    xor a
    ld [wPickupDo], a
    ld a, [wPickupAddr + 1]
    ld h, a
    ld a, [wPickupAddr]
    ld l, a
    xor a
    ld [hl], a
.draw
    ; Nothing is composed here. What has to be in VBlank is the writes -- OAM,
    ; VRAM and the scroll registers -- and the visible part of the frame has
    ; already worked out what they should say (DrawFrame, called from MainLoop).
    ; What is left is the two images, the tune, and the window bit, and that is
    ; under the 4560 cycles this window is.
    call CommitCamera
    call BlitOam
    call ShowHud

    ; One frame of the tune, and of the effect if one is running. The APU does
    ; not care that this is VBlank, but a frame is what the note lengths are
    ; counted in and this is the ROM's only per-frame hook.
    call UpdateMusic
    call UpdateSfx

    ; Switch the window back on for the frame that starts in a moment. The STAT
    ; handler turns it off again when LY reaches HUD_SPLIT_LY. This is what
    ; gives the band its position: LY 144..153 draw nothing, so the bit being
    ; set here is only ever observed at scanline 0.
    ;
    ; OBJ goes off with it. Sprites beat the window on this hardware, so a
    ; sprite in the band's eight lines would draw over the status row -- and one
    ; is: the caged duck's box reaches screen rows -9..6 whenever the camera is
    ; down at SCY 32, which is where it sits at every level's spawn. The band
    ; covers lines 0..7 for the BG; this makes it cover them for everything.
    ldh a, [rLCDC]
    and ~LCDCF_OBJON
    or LCDCF_WINON
    ldh [rLCDC], a

.done
    pop hl
    pop de
    pop bc
    pop af
    reti

; ---------------------------------------------------------------------------
; Entry point.
; ---------------------------------------------------------------------------
SECTION "Entry", ROM0[$150]

Start:
    di

    ; VRAM is only writable with the LCD off. Wait for VBlank first, so we do
    ; not switch it off mid-frame.
.wait_vblank
    ldh a, [rLY]
    cp 144
    jr nz, .wait_vblank

    xor a
    ldh [rLCDC], a           ; LCD off
    ldh [rSCY], a
    ldh [rSCX], a

    ; The sprite image, and the hardware's OAM with it. The shadow is
    ; ClearOamShadow's -- its own comment has the why -- and every level load
    ; clears it again; this is the power-on one, for the title and the first
    ; frame after START. What it does not cover is entries 32..39: OAM_BYTES
    ; stops at the duck, so the blitter never copies that far and nothing on any
    ; level ever writes them. They are OAM's alone, and an emulator's zeros hide
    ; that too -- a real DMG shows whatever those cells powered on with, in the
    ; playfield, for as long as OBJ is on. Zero all forty here, once, with the
    ; LCD off. A comes back 0 from the call and stays 0 through the loop, which
    ; is also what the band's registers below want.
    call ClearOamShadow
    ld hl, _OAMRAM
    ld b, 40 * 4
.zero_oam
    ld [hl+], a
    dec b
    jr nz, .zero_oam

    ; The status band's split. Both registers go in with the LCD off, which is
    ; also what keeps the DMG's spurious-STAT-interrupt-on-write bug away.
    ldh [rWY], a                     ; window at the top of the screen
    ld a, HUD_WX
    ldh [rWX], a
    ld a, HUD_SPLIT_LY
    ldh [rLYC], a
    ld a, STATF_LYC                  ; interrupt on LY = LYC, nothing else
    ldh [rSTAT], a

    ; The Spectrum draws the level as coloured ink on BLACK paper, so index 0
    ; must be black rather than the usual white. Shade for colour index c is
    ; bits (2c+1:2c): 0 -> black, 1 -> dark, 2 -> light, 3 -> white.
    ld a, PALETTE_INK_ON_BLACK
    ldh [rBGP], a
    ldh [rOBP0], a           ; Harry is drawn with the same mapping

    ; Hens get their own OBJ palette so they read as a different thing from
    ; Harry: his ink is colour index 3, and OBP1 maps that index to light grey
    ; where OBP0 maps it to white. Nothing else differs -- all sprite ink here
    ; is index 3, so only the top two bits of each palette matter.
    ld a, %01000000
    ldh [rOBP1], a

    ; Level tiles -> $8000.
    ld de, Tiles
    ld hl, _VRAM
    ld bc, TilesEnd - Tiles
    call MemCopy

    ; Harry's tiles go directly after them; OBJ tiles are always addressed
    ; unsigned from $8000, so there is no alignment to worry about.
    ld hl, _VRAM + HARRY_TILE_BASE * TILE_BYTES
    ld de, HarryTiles
    ld bc, HarryTilesEnd - HarryTiles
    call MemCopy

    ld hl, _VRAM + HEN_TILE_BASE * TILE_BYTES
    ld de, HenTiles
    ld bc, HenTilesEnd - HenTiles
    call MemCopy

    ld hl, _VRAM + LIFT_TILE_BASE * TILE_BYTES
    ld de, LiftTiles
    ld bc, LiftTilesEnd - LiftTiles
    call MemCopy

    ld hl, _VRAM + HUD_TILE_BASE * TILE_BYTES
    ld de, FontTiles
    ld bc, FontTilesEnd - FontTiles
    call MemCopy

    ; The title screen's glyphs and logo, which nothing else in the ROM uses --
    ; they are loaded with the rest because Start is the one place VRAM is
    ; written with the LCD off outside the level reload.
    ld hl, _VRAM + TEXT_TILE_BASE * TILE_BYTES
    ld de, TitleGlyphs
    ld bc, TitleGlyphsEnd - TitleGlyphs
    call MemCopy

    ld hl, _VRAM + LOGO_TILE_BASE * TILE_BYTES
    ld de, TitleLogoTiles
    ld bc, TitleLogoEnd - TitleLogoTiles
    call MemCopy

    ; ...and the high-score screen's run, same reason. It goes in as one block
    ; because it is one: the glyphs, the inverted alphabet and the banner are
    ; all addressed from SCORE_TILE_BASE by offset.
    ld hl, _VRAM + SCORE_TILE_BASE * TILE_BYTES
    ld de, ScoreTiles
    ld bc, ScoreTilesEnd - ScoreTiles
    call MemCopy

    ; ...and the duck's two frames, the last tiles in the bank. Nothing but a
    ; level draws it, but Start is still the only place with the LCD already off.
    ld hl, _VRAM + DUCK_TILE_BASE * TILE_BYTES
    ld de, DuckTiles
    ld bc, DuckTilesEnd - DuckTiles
    call MemCopy

    ; The table's starting ten entries. Seeded once, here, so it survives
    ; across games in a session and dies at power-off, as the original's does
    ; (the Z80's HighScores is a plain data block with no save behind it).
    ; NewGame deliberately does not touch it: EnterTitle runs NewGame on every
    ; game over.
    call SeedHighScores

    ; The window's whole map is only ever one row, so bank 1 gets cleared once
    ; here and never touched again -- LoadLevel and ClearMap both work on map 0.
    ld hl, HUD_MAP
    ld bc, SCRN_BYTES
    ld d, 0
.clear_hud
    ld [hl], d
    inc hl
    dec bc
    ld a, b
    or c
    jr nz, .clear_hud

    ; The APU. rNR52's top bit powers it and gates every other register here,
    ; so it goes in first -- writes before it are dropped silently. Channel 1
    ; is the tune (50% duty, full volume) and channel 4 the effects, silent
    ; until one is asked for.
    ld a, AUDENA_ON
    ldh [rNR52], a
    ld a, $FF
    ldh [rNR51], a                   ; every channel to both outputs
    ld a, $77
    ldh [rNR50], a                   ; and both outputs at full volume
    ld a, AUDDUTY_50
    ldh [rNR11], a
    ld a, AUDVOL_MAX
    ldh [rNR12], a
    xor a
    ldh [rNR13], a
    ldh [rNR14], a
    ldh [rNR42], a                   ; channel 4 silent
    ldh [rNR43], a
    ldh [rNR44], a
    ld hl, wMusicPtr
    ld [hl+], a
    ld [hl], a                       ; nothing playing yet
    ld [wSfxTimer], a                ; nor an effect. Nothing else zeroes these,
    ld [wSfxFreq], a                 ; and the title has no draw pass running
                                     ; over the top of a stray one

    ; And no announcement is up. This one is not a park like the three above --
    ; it is the same bug as the OAM clear: the VBlank handler tests wOnNotice
    ; with the front-end flags and skips the whole draw pass when it is set, and
    ; the only thing that ever writes it is ShowNotice. A level that arrives
    ; through ShowNotice is fine -- the routine clears it on the way out -- but
    ; the title's START goes EnterTitle -> StartGame -> NextLevel.reload, which
    ; is no notice at all, so the first level is played with whatever the byte
    ; powered on with. Nonzero there means no camera, no sprites and no status
    ; row for that level: on an emulator it is 0 and nothing shows, on a DMG it
    ; is whatever the cell held. (EnterTitle clears wOnTitle/wOnScores/wOnInstr
    ; and deliberately not this one -- the flag is not a front end -- so it is
    ; cleared here, at power-on, before any handler can read it: interrupts are
    ; still off.)
    ld [wOnNotice], a

    ld a, IEF_VBLANK | IEF_STAT
    ldh [rIE], a

    ; The ROM boots to the title, as the Z80's does (FrontEnd). No level is
    ; loaded until START: EnterTitle does its own NewGame and screen, and
    ; StartGame is what reaches LoadLevel. The LCD is already off, which both
    ; of them need.
    ;
    ; After the APU and after the park above, not before: EnterTitle starts the
    ; tune, which needs the APU powered, and StartMusic writes wMusicPtr, so
    ; parking the pointer afterwards would stop the tune dead.
    call EnterTitle
    ei

MainLoop:
    halt                     ; the handler draws; this does the thinking
    nop

    ; The front end -- the title, the high-score table behind it, or the
    ; instructions. Nothing to tick and no frame to stay out of, because there is
    ; no level: just the two buttons, and the handler has already drawn. It has
    ; to be tested here rather than down at .wait_frame's dead branch, or a dead
    ; Harry's tick would run with no level loaded.
    ld a, [wOnTitle]
    ld hl, wOnScores
    or [hl]
    ld hl, wOnInstr
    or [hl]
    jr z, .wait_frame
    call ReadButtons
    ; The edge, not the level: a player who is still holding START when the name
    ; entry or a death ends would otherwise blow straight through the screen in
    ; front of them. It also means a START held from play is not a press here.
    ; B keeps the whole edge set -- the routine below calls, and A does not
    ; survive a call.
    ld a, [wPadNew]
    ld b, a
    and PAD_SELECT
    jr z, .start
    ; SELECT is the instructions, and only ever the title's: the table's legend
    ; names all four of its controls and it is a screen you are sent to, not a
    ; menu. On the title it opens them; on them it closes.
    ld a, [wOnScores]
    and a
    jr nz, MainLoop
    ld a, [wOnInstr]
    and a
    jr nz, .to_title
    call EnterInstructions
    jr MainLoop
.start
    ld a, b
    and PAD_START
    jr z, MainLoop
    ; One route out of each screen: the table goes back to the title, while the
    ; title and the instructions both begin the next game -- the Z80 starts one
    ; from its instructions screen on the same key that starts it at the front
    ; end, and leaves on `S` (Chuckie.asm:4177).
    ld a, [wOnScores]
    and a
    jr nz, .to_title
    call StartGame
    jr MainLoop
.to_title
    call EnterTitle
    jr MainLoop

    ; Let the visible part of the frame start before running the tick. The tick
    ; is timing independent, but starting it inside VBlank runs it across the
    ; frame boundary -- so an emulator stepping a frame at a time returns in the
    ; middle of it, and a state written between frames lands part way through the
    ; tick rather than before it. Waiting costs nothing; the tick still happens
    ; once a frame, just later in one.
.wait_frame
    ldh a, [rLY]
    cp 40
    jr c, .wait_frame        ; still in the last frame's visible part
    cp 144
    jr nc, .wait_frame       ; 144..153: VBlank, the handler has not drawn yet

    ; Dead: hold everything still for a moment, then restart the level. The Z80
    ; unwinds its call stack to leave the game loop here and comes back through
    ; PlayLevel, which reloads the level -- eaten eggs and all, which is why the
    ; restart goes the whole way rather than just resetting Harry and the hens.
    ld a, [wPlayerDead]
    and a
    jr z, .level_done
    ld hl, wDeathTimer
    dec [hl]
    jr nz, MainLoop
    ; The freeze is over, so this death costs a life -- the Z80's `DEC (HL)` on
    ; the player's life byte (Chuckie.asm:4547). At zero every player is out and
    ; the Z80 goes to CheckPlayersHighScores and then FrontEnd; so does this.
    ; START on the table goes to the title, and START there begins the next one.
    ld hl, wLives
    dec [hl]
    jr nz, .restart
    call EnterScores
    jr MainLoop
.restart
    ; The reload comes first and the flag second, so that anything watching
    ; wPlayerDead for the restart to be over sees it finished -- LoadLevel
    ; writes 1700-odd bytes and cannot fit inside the VBlank it opens with, so
    ; it runs across a frame boundary either way.
    call NextLevel.reload
    xor a
    ld [wPlayerDead], a
    ; The level has been reloaded under the shadow, and the handler copies it
    ; out whatever the main line did, so the first frame of the new level would
    ; otherwise show the last frame of the old one.
    call DrawFrame
    jr MainLoop

    ; The last egg: on to the next level.
.level_done
    ld a, [wLevelDone]
    and a
    jr z, .alive
    call NextLevel
    call DrawFrame            ; as above: the shadow is a frame of the last level
    jr MainLoop

.alive
    call UpdatePlayer
    call UpdateHens
    call UpdateDuck
    call CollidePlayerAndHen
    ; The duck is tested in the same breath as the hens, and for the same
    ; reason: the Z80 walks it in the same level-column pass that tests the
    ; hens' overlap, and it unwinds the stack on either.
    call CollidePlayerAndDuck
    ; Last, and only if he is still alive: the Z80 returns out of the tick on a
    ; collision, so a dead Harry does not collect the egg he died on.
    ld a, [wPlayerDead]
    and a
    jr nz, .drawn
    call PlayerPickUp
    ; The counters, last, so they stop while he is dead and during a
    ; transition -- the Z80's timer block sits after PlayerPickUp too.
    call UpdateTimer
    ; Everything this frame changed reaches the screen through the shadow, and
    ; the handler copies it out on the next VBlank -- so the compose has to be
    ; after the tick and, since it is the visible part of the frame, it is the
    ; last thing the frame does. A death jumps here too: the world has stopped,
    ; but the frame he died on still has to be built.
.drawn
    call DrawFrame
    jp MainLoop

; ---------------------------------------------------------------------------
; ResetPlayer: Harry's starting state, from the Z80's initial variable block.
; ---------------------------------------------------------------------------
ResetPlayer:
    ld a, HARRY_START_X
    ld [wPlayerX], a
    ld a, HARRY_START_Y
    ld [wPlayerY], a
    xor a
    ld [wPlayerAnimFrame], a
    ld [wPlayerInAir], a
    ld a, DIR_LEFT
    ld [wPlayerDirection], a
    ld a, $FF
    ld [wPlayerAirDirection], a
    ld a, 1
    ld [wPlayerJumpDirection], a
    ld a, $96
    ld [wInAirCounter], a
    ld [wFallingCounter], a
    xor a
    ld [wPad], a
    ret

; ---------------------------------------------------------------------------
; UpdatePlayer: one gameplay tick for Harry.
;
; Runs OUTSIDE VBlank -- it only reads the level and writes WRAM. The drawing
; that follows from it happens in the VBlank handler.
;
; The order is the Z80's MainLoop: CollidePlayerToWorld first (it does nothing
; while Harry is on the ground), then the jump key, then the ground movement.
; ---------------------------------------------------------------------------
UpdatePlayer:
    call UpdateLifts
    and a
    ret nz                   ; rode past the top: he is dead, and the tick ends

    call ReadButtons                ; leaves wPad and wPadNew

    call CollidePlayerToWorld
    call AirPhysics
    ld a, [wPlayerDead]
    and a
    ret nz                   ; fell under the floor: the Z80 leaves the level,
                             ; so nothing after the physics runs this tick

    ld a, [wPlayerInAir]
    and a
    jr nz, .climbing

    ; Not in the air, so the jump key applies.
    ld a, [wPad]
    and PAD_A
    jr nz, .jump

    ; On the ground: pick a facing, then move, then look for a hole underfoot.
    call TryMoveLeftRight
    ld a, [wPlayerDirection]
    cp DIR_CLIMB
    jr z, .climbing          ; climbing this frame, so no horizontal move
    call MovePlayer
    ld a, [wPlayerOnLift]
    and a
    call z, CheckForFalling  ; standing on a platform is not standing on a ledge
.climbing
    call TryClimbLadder
    jp CheckLiftFalling      ; the Z80's tail: still over the platform?
.jump
    call DoJump
    ret

; ---------------------------------------------------------------------------
; CollidePlayerToWorld: the horizontal half of the in-air collision, which the
; Z80 gates on SoundTimer == 1 -- i.e. once per gameplay tick, so once here.
; (Chuckie.asm:3581 InAirChecks, then the PlayerInAir == 1 arm of 3671.)
;
; Mid-air Harry is ballistic: x just follows PlayerJumpDirection with a bounce
; off the two screen edges and no reference to the tile map at all. That is the
; original's behaviour, and it is why a jump reads as committed rather than
; steerable.
; ---------------------------------------------------------------------------
CollidePlayerToWorld:
    ld a, [wPlayerInAir]
    and a
    ret z

    ld a, [wPlayerJumpDirection]
    ld b, a
    ld a, [wPlayerX]
    add a, b
    ld [wPlayerX], a
    and a
    jr nz, .not_left_edge
    ld a, 1
    ld [wPlayerJumpDirection], a
    jr .edges_done
.not_left_edge
    cp $EE
    jr c, .edges_done
    ld a, $FF
    ld [wPlayerJumpDirection], a
.edges_done

    ; Stepping off a ledge drops through the lift test first: the Z80 only
    ; looks for a platform to land on inside this four-tick window
    ; (Chuckie.asm:3298), which is what makes a lift something you walk onto.
    call CheckLiftLanding
    ld a, [wPlayerInAir]
    and a
    ret z                    ; landed on a lift: no countdown, no fall

    ; Walking off a ledge is a short countdown, then it becomes a real fall.
    ld a, [wPlayerInAir]
    cp 1
    ret nz
    ld hl, wInAirCounter
    dec [hl]
    jp nz, BounceWhileInAir
    ld a, 2
    ld [wPlayerInAir], a
    xor a
    ld [wPlayerJumpDirection], a
    ld a, $FA
    ld [wInAirCounter], a
    ld a, $FF
    ld [wPlayerAirDirection], a
    ret

; ---------------------------------------------------------------------------
; AirPhysics: replay the main-loop iterations a single GB frame is standing in
; for. The Z80 calls this path on every iteration, so the counters inside
; AirStep are in Spectrum loop units, not frames. See PHYSICS_STEPS.
;
; A landing ends the replay. AirStep's CheckBelow clears PlayerInAir part-way
; through the 130 iterations, and the Z80 would take the ground path from the
; next iteration on; replaying the fall regardless carried him up to 3px past
; the tile he had already landed on -- and left PlayerInAir clear at a y that
; is not y+1 % 8 == 0, so nothing put him back. On screen it is Harry sunk into
; the platform he just dropped onto, and a jump is what shakes him out of it.
; ---------------------------------------------------------------------------
AirPhysics:
    ld a, [wPlayerInAir]
    cp 2
    ret nz                   ; only the jump arc, not the ledge countdown
    ld b, PHYSICS_STEPS
.loop
    push bc
    call AirStep
    pop bc
    ld a, [wPlayerInAir]
    cp 2
    ret nz                   ; he landed: the rest of the frame is the ground
    ld a, [wPlayerDead]
    and a
    ret nz                   ; he fell under the floor: the level is over
    dec b
    jr nz, .loop
    ret

; ---------------------------------------------------------------------------
; AirStep: one iteration of the vertical arc. The Z80's NotInAir
; (Chuckie.asm:3690).
;
; FallingCounter divides the loop down to one pixel of movement, and the move
; is always a single pixel in PlayerAirDirection. The counters are the original
; ones: $8C start, +10 per step up until $FA+10 wraps to 4 (the apex), then
; -10 per step down with a floor of $28.
; ---------------------------------------------------------------------------
AirStep:
    ld hl, wFallingCounter
    dec [hl]
    ret nz

    ld a, [wPlayerAirDirection]
    dec a
    jr z, .going_up
    inc a
    and a
    jr nz, .is_falling
    ; PlayerAirDirection == 0: just past the apex, so start coming down.

.set_to_fall
    ld a, $FF
    ld [wPlayerAirDirection], a
    ld a, $FA
    jr .not_apex

.is_falling
    ld a, [wInAirCounter]
    sub $0A
    cp $28
    jr nc, .not_apex         ; the delay bottoms out at 40 iterations
    ld a, $28
    jr .not_apex

.going_up
    ld a, [wPlayerY]
    cp $A7                   ; 167: the top of the playfield
    jr c, .test_apex
    ld hl, wPlayerY
    inc [hl]
    jr .set_to_fall          ; the +1 above is cancelled by the fall step

.test_apex
    ld a, [wInAirCounter]
    add a, $0A               ; $FA + 10 wraps to 4, which is the apex
    cp $04
    jr nz, .not_apex
    xor a
    ld [wPlayerAirDirection], a
.not_apex
    ld [wInAirCounter], a
    ld [wFallingCounter], a
    ld a, [wPlayerAirDirection]
    ld b, a
    ld a, [wPlayerY]
    add a, b
    cp $10
    jr nc, .set_y
    ; Under the floor: the Z80 leaves the level here. `POP HL / POP HL / RET`
    ; unwinds past MainLoop -- which was entered by JP and so has no return
    ; address of its own -- back to the frame after `CALL PlayLevel`, the same
    ; door the last egg goes out of (PlayerPickUp's single `POP HL / RET`).
    ; What waits there sends a player with eggs left to LoseLife, so falling
    ; through a hole in the floor is a DEATH, not a stall. It was read as
    ; "stop moving him", which soft-locked Harry at the bottom of the level.
    jp KillPlayer
.set_y
    ld [wPlayerY], a
    jp BounceWhileInAir

; ---------------------------------------------------------------------------
; BounceWhileInAir: what the jump or fall runs into. The Z80's tail of
; CollideWithWorld (Chuckie.asm:3761); called once per pixel of vertical travel
; and once per gameplay tick while walking off a ledge.
; ---------------------------------------------------------------------------
BounceWhileInAir:
    call HarryMapAddr        ; the cell at Harry's own (y, x)...
    ld bc, -2 * LEVEL_WIDTH + 1
    add hl, bc               ; ...and the one under his right foot

    ; Rising, or jumping straight up, only ever tests straight below.
    ld a, [wPlayerAirDirection]
    dec a
    jr z, CheckBelow
    ld a, [wPlayerJumpDirection]
    and a
    jr z, CheckBelow
    dec a
    jr z, .going_right

    ; Falling while drifting left: the floor is caught by his left-hand side.
    ; Harry covers columns x/8 and x/8+1, so a column within 4px of the sprite
    ; edge is over the neighbouring cell.
    ld a, [wPlayerX]
    and $07
    cp $04
    jr nc, CheckBelow
    dec hl
    ld a, [hl]
    inc hl
    cp TILE_PLATFORM
    jr nz, CheckBelow
    jr BounceOffFloor

.going_right
    ld a, [wPlayerX]
    and $07
    cp $03
    jr c, CheckBelow
    inc hl
    ld a, [hl]
    dec hl
    cp TILE_PLATFORM
    jr nz, CheckBelow

; Clipping the edge of a platform mid-flight reverses the drift, which is what
; makes Harry skitter along a ledge instead of dropping straight past it.
BounceOffFloor:
    ld a, [wPlayerJumpDirection]
    xor $FE                  ; toggles between $01 and $FF
    ld [wPlayerJumpDirection], a

CheckBelow:
    ld a, [hl]
    and a
    ret z                    ; nothing down there
    cp TILE_PLATFORM
    jr z, .landed
    cp TILE_EGG
    ret nc                   ; egg and birdseed do not hold him up
    dec hl
    dec a                    ; was that TILE_LADDERLEFT?
    jr z, .was_ladder
    inc hl
    inc hl
.was_ladder
    ; A ladder only holds him up when the level beside it is solid -- which is
    ; how the ladder tops work out as landings without a tile for them.
    ld a, [hl]
    cp TILE_PLATFORM
    ret nz
.landed
    ; He only comes to rest when the sprite snaps to the cell grid, i.e. when
    ; y+1 is a multiple of 8. Otherwise the fall continues to the next pixel.
    ld a, [wPlayerY]
    inc a
    and $07
    ret nz
    xor a
    ld [wPlayerInAir], a
    ld hl, wPlayerDirection
    ld a, [hl]
    cp DIR_CLIMB
    ret nz
    ld [hl], DIR_RIGHT       ; a landing cannot also be a climb
    ret

; ---------------------------------------------------------------------------
; ReadButtons: A = this frame's buttons, active HIGH, and wPad/wPadNew with it.
;   bit 0 right, 1 left, 2 up, 3 down, 4 A, 5 B, 6 select, 7 start
; The d-pad and the buttons are two separate rows of the joypad matrix, so this
; has to select each in turn; four reads is the documented settle time.
;
; wPad is the level's view of the pad: held, so a direction repeats. wPadNew is
; the buttons that went down THIS frame, which is what a menu wants -- the
; Z80's name entry debounces on KSTATE/LASTK to get the same thing, so one
; keypress is one letter rather than one a frame.
; ---------------------------------------------------------------------------
ReadButtons:
    ld a, P14_DPAD
    ldh [rP1], a
    ldh a, [rP1]
    ldh a, [rP1]
    ldh a, [rP1]
    cpl
    and $0F
    ld b, a
    ld a, P15_BUTTONS
    ldh [rP1], a
    ldh a, [rP1]
    ldh a, [rP1]
    ldh a, [rP1]
    cpl
    and $0F
    swap a
    or b
    ld b, a
    ld a, P14_DPAD | P15_BUTTONS   ; deselect, or the next read is wrong
    ldh [rP1], a
    ; The edge: down this frame and not last. wPad still holds last frame's
    ; value here -- this routine is the only thing that writes it, once a frame.
    ld a, [wPad]
    cpl
    and b
    ld [wPadNew], a
    ld a, b
    ld [wPad], a
    ret

; ---------------------------------------------------------------------------
; GetMapAddr: HL = wLevelBuffer + (d/8)*32 + (e/8), i.e. the cell at y=d, x=e.
; This is the Z80's (LevelBuffer + (y&$F8)*4 + (x>>3)), which appears inline
; about twenty times over there. Clobbers A and BC.
; ---------------------------------------------------------------------------
GetMapAddr:
    ld a, d
    and $F8
    ld l, a
    ld h, 0
    add hl, hl               ; (y & $F8) * 2
    add hl, hl               ; ... * 4 == (y/8)*32
    ld a, e
    srl a
    srl a
    srl a
    ld c, a
    ld b, 0
    add hl, bc
    ld bc, wLevelBuffer
    add hl, bc
    ret

; ---------------------------------------------------------------------------
; TryMoveLeftRight: choose which way Harry faces.
;
; Only runs when y is on a cell boundary -- y+1 a multiple of 8, which is
; exactly when a 16px-tall sprite lines up with the cell grid. A direction key
; only takes effect if the two cells Harry would occupy are clear AND there is
; still something solid underfoot, so he cannot walk out over a hole.
;
; The Z80 checks one column to the left but two to the right, because x is the
; sprite's left edge: he covers columns x/8 and x/8+1, so the next free column
; is x/8-1 on the left and x/8+2 on the right.
; ---------------------------------------------------------------------------
TryMoveLeftRight:
    ld a, [wPlayerY]
    inc a
    and $07
    ret nz
    call HarryMapAddr        ; HL = cell at Harry's (y, x)
    ld a, [wPad]
    and PAD_LEFT
    jr z, .right

    dec hl
    ld a, [hl]
    cp TILE_PLATFORM
    ret nc
    call DownOneRow
    ld a, [hl]
    cp TILE_PLATFORM
    ret nc
    call DownOneRow
    ld a, [hl]
    and a
    ret z                    ; nothing underfoot at all
    cp TILE_LAST
    ret nc                   ; that is the score line, not the playfield
    ld a, DIR_LEFT
    ld [wPlayerDirection], a
    ret

.right
    ld a, [wPad]
    and PAD_RIGHT
    ret z
    inc hl
    inc hl
    ld a, [hl]
    cp TILE_PLATFORM
    ret nc
    call DownOneRow
    ld a, [hl]
    cp TILE_PLATFORM
    ret nc
    ld a, DIR_RIGHT
    ld [wPlayerDirection], a
    ret

; HL -= 32: one row DOWN the playfield. The Z80 does SBC HL,BC with BC=$0020;
; the flag result is never used, so a plain ADD with a negative constant is the
; same thing (and SBC HL,rr does not exist on the Game Boy).
DownOneRow:
    ld bc, -LEVEL_WIDTH
    add hl, bc
    ret

; ---------------------------------------------------------------------------
; MovePlayer: shift Harry one pixel left or right, if the key is held and the
; cells he would move into are clear.
; ---------------------------------------------------------------------------
MovePlayer:
    ld a, [wPlayerY]
    ld d, a
    ld a, [wPlayerX]
    ld e, a
    ; The Z80 picks the column from the CURRENT facing, not from the key being
    ; held: left-facing checks x-1, right-facing checks x. Faithfully odd, and
    ; it self-corrects a frame later if the two disagree.
    ld a, [wPlayerDirection]
    and a
    jr z, .have_addr
    dec e
.have_addr
    call GetMapAddr

    ld a, [wPad]
    and PAD_LEFT
    jr z, .right

    ld a, [wPlayerX]
    dec a
    jr z, .stop              ; would reach the left edge
    ld a, [hl]
    cp TILE_PLATFORM
    jr nc, .stop
    call DownOneRow
    ld a, [hl]
    cp TILE_PLATFORM
    jr nc, .stop
    ld hl, wPlayerX
    dec [hl]
    ld a, DIR_LEFT
    ld [wPlayerDirection], a
    call CycleAnimFrame
    ret

.right
    ld a, [wPad]
    and PAD_RIGHT
    jr z, .stop
    ld a, [wPlayerX]
    cp $EE
    jr nc, .stop             ; would reach the right edge
    inc hl
    inc hl
    ld a, [hl]
    cp TILE_PLATFORM
    jr nc, .stop
    call DownOneRow
    ld a, [hl]
    cp TILE_PLATFORM
    jr nc, .stop
    ld hl, wPlayerX
    inc [hl]
    ld a, DIR_RIGHT
    ld [wPlayerDirection], a
    call CycleAnimFrame
    ret

.stop
    ; The Z80 parks the animation on frame 3 when nothing is pressed; the
    ; frame then advances again immediately, so all this really does is keep
    ; the cycle running while standing still.
    ld a, 3
    ld [wPlayerAnimFrame], a
    call CycleAnimFrame
    ret

; ---------------------------------------------------------------------------
; TryClimbLadder: move Harry up or down a ladder.
;
; Only runs when x IS cell-aligned, which is the exact complement of
; CheckForFalling -- so at any moment he is either eligible to climb or
; eligible to fall, never both.
;
; The up-check looks at the cell one row above Harry's top; the down-check
; looks two rows below that (three if y is aligned), i.e. under his feet.
; ---------------------------------------------------------------------------
TryClimbLadder:
    ld a, [wPlayerX]
    and $07
    ret nz
    ld a, [wPlayerY]
    inc a
    ld d, a                  ; the Z80 tests the cell at y+1
    ld a, [wPlayerX]
    ld e, a
    call GetMapAddr
    ld a, [hl]
    cp TILE_LADDERLEFT
    jr nz, .down

    ld a, [wPad]
    and PAD_UP
    jr z, .down
    ld a, DIR_CLIMB
    ld [wPlayerDirection], a
    ld hl, wPlayerY
    inc [hl]
    jr .moved

.down
    ld bc, -2 * LEVEL_WIDTH
    add hl, bc
    ld a, d
    and $07
    jr nz, .have_cell
    ld bc, -LEVEL_WIDTH
    add hl, bc
.have_cell
    ld a, [hl]
    cp TILE_LADDERLEFT
    ret nz

    ld a, [wPad]
    and PAD_DOWN
    ret z
    ld a, DIR_CLIMB
    ld [wPlayerDirection], a
    ld hl, wPlayerY
    dec [hl]
.moved
    call CycleAnimFrame
    xor a
    ld [wPlayerInAir], a      ; on a ladder is not in the air
    ret

; ---------------------------------------------------------------------------
; CheckForFalling: if there is nothing under Harry, start him falling.
; Complementary to TryClimbLadder: this runs when x is NOT cell-aligned.
; ---------------------------------------------------------------------------
CheckForFalling:
    ld a, [wPlayerX]
    and $07
    ret z
    call HarryMapAddr
    ; The Z80 subtracts $3F, not $40: minus 63 from the cell at (row r, col c)
    ; lands on (r-2, c+1) -- two rows down and one column RIGHT, so it samples
    ; the cell under Harry's right foot.
    ld bc, -2 * LEVEL_WIDTH + 1
    add hl, bc
    ld a, [hl]
    cp TILE_PLATFORM
    ret nc
    cp TILE_LADDERLEFT
    ret z
    cp TILE_LADDERRIGHT
    ret z

    ld a, 1
    ld [wPlayerInAir], a
    ld a, [wPlayerDirection]
    and a
    ld a, $FF                ; left
    jr nz, .set
    ld a, 1                  ; right
.set
    ld [wPlayerJumpDirection], a
    ld a, 4
    ld [wInAirCounter], a
    ret

; ---------------------------------------------------------------------------
; DoJump: start a jump. Translated from the Z80 at Chuckie.asm:2170.
; ---------------------------------------------------------------------------
DoJump:
    ld a, 2
    ld [wPlayerInAir], a
    xor a
    ld [wPlayerOnLift], a    ; a jump is the only way off a moving platform
    ld a, $8C
    ld [wInAirCounter], a
    xor a
    ld [wFallingCounter], a
    ld a, 1
    ld [wPlayerAirDirection], a

    ; Which way he jumps: the direction key held, or straight up if neither.
    ld a, [wPad]
    and PAD_RIGHT
    jr nz, .right
    ld a, [wPad]
    and PAD_LEFT
    jr nz, .left
    xor a                    ; straight up: facing is unchanged
    ld [wPlayerJumpDirection], a
    ret
.right
    ld a, 1
    ld [wPlayerJumpDirection], a
    ld a, DIR_RIGHT
    ld [wPlayerDirection], a
    ret
.left
    ld a, $FF
    ld [wPlayerJumpDirection], a
    ld a, DIR_LEFT
    ld [wPlayerDirection], a
    ret

; ---------------------------------------------------------------------------
; CycleAnimFrame: (frame + 1) mod 4.
; ---------------------------------------------------------------------------
CycleAnimFrame:
    ld hl, wPlayerAnimFrame
    ld a, [hl]
    inc a
    and $03
    ld [hl], a
    ret

; ---------------------------------------------------------------------------
; HarryMapAddr: HL = the cell at Harry's own (x, y). Clobbers A and BC.
; ---------------------------------------------------------------------------
HarryMapAddr:
    ld a, [wPlayerY]
    ld d, a
    ld a, [wPlayerX]
    ld e, a
    jp GetMapAddr

; ---------------------------------------------------------------------------
; UpdateCamera: keep Harry centred, both ways. Computes the camera; CommitCamera
; is what writes it to the registers. See wScrollX.
;
; VERTICAL: the playfield is 21 rows (168 px) and the status band takes the top
; 8 of the screen's 144, so SCY has SCY_MAX (32) to move through, not the 24 it
; had before the band. Harry's y is Cartesian, so his distance from the top of
; the playfield is 167-y and his screen row is that plus the band, minus SCY.
; Wanting that at the middle of the screen gives SCY = 96 - y, clamped to
; 0..SCY_MAX -- the same expression, a longer travel.
;
; HORIZONTAL: the playfield is 32 cells = 256 px, which is the width of the BG
; MAP, but the visible screen is only 160 px. So 96 px of the level is off
; screen and SCX has 0..96 to move through -- a much bigger crop than the
; vertical one, and the reason a horizontal camera exists at all. Centring
; Harry's 16px-wide sprite gives SCX = x + 8 - 80.
; ---------------------------------------------------------------------------
UpdateCamera:
    ld a, [wPlayerY]
    ld b, a
    ld a, 96
    sub b
    jr nc, .clamp_high       ; no borrow: 96 - y >= 0
    xor a                    ; y > 96 -> show the top of the playfield
    jr .set_y
.clamp_high
    cp SCY_MAX + 1
    jr c, .set_y
    ld a, SCY_MAX
.set_y
    ld [wScrollY], a

    ; SCX = x + 8 - 80, written as x - 72 so nothing can wrap: adding the 8
    ; first overflows a byte for x >= 248, and while the game's own edge checks
    ; keep x at or below $EE, a camera that only works for x < 248 is a trap
    ; laid for whoever changes those.
    ld a, [wPlayerX]
    sub 72                   ; 80 (screen centre) - 8 (half a sprite)
    jr nc, .clamp_right
    xor a                    ; left of centre: show the playfield's left edge
    jr .set_x
.clamp_right
    cp 97
    jr c, .set_x
    ld a, SCX_MAX            ; 256 - 160, the rightmost the map can scroll
.set_x
    ld [wScrollX], a
    ret

; ---------------------------------------------------------------------------
; CommitCamera: put the camera into the registers. VBlank only.
; ---------------------------------------------------------------------------
CommitCamera:
    ld a, [wScrollY]
    ldh [rSCY], a
    ld a, [wScrollX]
    ldh [rSCX], a
    ret

; ---------------------------------------------------------------------------
; ClearOamShadow: hide every entry of the OAM image.
;
; An entry nothing writes is a sprite pinned to the SCREEN -- OAM is in screen
; coordinates and nothing scrolls it, so it does not travel with the level --
; and the draws skip the slots a level does not use: DrawHens the entries of a
; hen its spawn table has no record for (HEN_NONE), and DrawLifts the ones a
; level with no lift has. That is a stray sprite on a real machine and nothing
; at all under an emulator's zeros, which is how it was found twice: once at
; power-on, and once when a game over at level 3 left its third hen and a
; platform on level 1 for good.
;
; Every level arrives through LoadLevel, which calls this, so a level cannot
; inherit the birds or platforms of the one before it. Start calls it too, for
; the state the cells powered on with -- see there.
;
; Y 0 is the whole of hiding an entry: it puts the sprite above the screen and
; its column, tile and attribute are never reached. A is 0 on return, which the
; two callers both use.
; ---------------------------------------------------------------------------
ClearOamShadow:
    xor a
    ld hl, wOamShadow
    ld b, OAM_BYTES
.loop
    ld [hl+], a
    dec b
    jr nz, .loop
    ret

; ---------------------------------------------------------------------------
; DrawFrame: compose the frame -- the camera, the sprites, the status row.
; Runs in the visible part of the frame, where the whole of it is a few
; thousand cycles out of the 65000-odd that are not VBlank. The handler then
; only copies the two images it leaves behind.
; ---------------------------------------------------------------------------
DrawFrame:
    call UpdateCamera
    call DrawHarry
    call DrawHens
    call DrawDuck
    call DrawLifts
    jp BuildHud

; ---------------------------------------------------------------------------
; BlitOam: the OAM image out of wOamShadow. VBlank only.
;
; Flat and unrolled. An entry is four bytes and DE has no auto-increment, so a
; byte costs a load, an increment and a store -- 24 cycles, and a loop's own
; counter would be another 16 on top of every one of them. At OAM_BYTES that is
; a third of the budget spent on loop overhead to save a page of source.
; ---------------------------------------------------------------------------
BlitOam:
    ld hl, _OAMRAM
    ld de, wOamShadow
    REPT OAM_BYTES
    ld a, [de]
    inc de
    ld [hl+], a
    ENDR
    ret

; ---------------------------------------------------------------------------
; ShowHud: the status row out of wHudRow and into the window's map. VBlank only
; -- it is VRAM. Unrolled for the same reason as BlitOam.
; ---------------------------------------------------------------------------
ShowHud:
    ld hl, HUD_MAP
    ld de, wHudRow
    REPT HUD_ROW_LEN
    ld a, [de]
    inc de
    ld [hl+], a
    ENDR
    ret

; ---------------------------------------------------------------------------
; ResetLifts: this level's platform column, from the Z80's table at $9787.
;
; The table is nine four-byte records indexed by (level & 7) + 1, so record 3
; is the first level with a platform: 1-based levels 3, 4, 5, 6 and 7, at
; x = 64, 144, 200, 120 and 240. Record 0 exists only as storage -- level init
; copies the level's own record into it, because the wrap-around reset always
; reloads from $9787 and would otherwise get the level's neighbour.
; ---------------------------------------------------------------------------
ResetLifts:
    ld a, [wCurrentLevel]
    and LEVEL_COUNT - 1      ; the maps repeat from the ninth level
    ld c, a
    ld b, 0
    ld hl, LiftXTable
    add hl, bc               ; one byte a level, so this one needs no table
    ld a, [hl]
    ld [wLiftX], a
    ld a, LIFT_HOME
    ld [wLiftYPos], a
    ld a, LIFT_HOME + LIFT_OFFSET
    ld [wLiftYPos + 1], a
    ld a, LIFT_SPEED
    ld [wLiftTick], a
    xor a
    ld [wPlayerOnLift], a
    ret

; ---------------------------------------------------------------------------
; UpdateLifts: the Z80's elevator block (Chuckie.asm:1985). On every second
; gameplay tick both platforms rise one pixel, and a player standing on one is
; carried up with them.
;
; A != 0 on return means the ride killed him, and ends the tick with it: past
; PlayerY $A5 the Z80 does `RET NC`, which returns out of MainLoop -- entered
; by JP, so with no return address of its own -- to the frame after `CALL
; PlayLevel`, and that code sends a player with eggs left to LoseLife.
;
; So riding a platform off the top of the playfield is a death, in the original
; and here. Read as "the input goes dead until his y wraps" once, which is what
; it did: Harry climbed past the ceiling and reappeared at the bottom.
; ---------------------------------------------------------------------------
UpdateLifts:
    ld hl, wLiftTick
    dec [hl]
    jr z, .tick
    xor a
    ret
.tick
    ld [hl], LIFT_SPEED
    ld hl, wLiftYPos
    ld b, 2
.platform
    ld a, [hl]
    inc a
    cp LIFT_TOP
    jr c, .store
    ld a, LIFT_HOME          ; a platform that runs off the top restarts below
.store
    ld [hl+], a
    dec b
    jr nz, .platform

    ld a, [wPlayerOnLift]
    and a
    jr nz, .ride
    xor a
    ret
.ride
    ld hl, wPlayerY
    inc [hl]
    ld a, [hl]
    cp LIFT_CEILING
    jr nc, .bail
    xor a
    ret
.bail
    call KillPlayer
    ld a, 1
    ret

; ---------------------------------------------------------------------------
; CheckLiftLanding: is Harry standing on a platform? Called from the four-tick
; window that opens when he steps off a ledge, so a platform catches him on the
; way down and nothing else can put him on one.
;
; The test is the Z80's (Chuckie.asm:3311): x within lift_x-9 .. lift_x+9, and
; y within YPos+10 .. YPos+15 for either platform. A match stands him on it --
; y snaps to YPos+17, two pixels above the band, so the landing lifts him onto
; the deck rather than leaving him buried in it.
; ---------------------------------------------------------------------------
CheckLiftLanding:
    ld a, [wLiftX]
    cp LIFT_NONE
    ret z
    sub LIFT_HALF
    ld c, a                  ; c = lift_x - 9, the left edge of the band
    ld a, [wPlayerX]
    cp c
    ret c
    sub 19                   ; the band is 19 wide: x-9 .. x+9
    cp c
    ret nc
    ld a, [wPlayerY]
    ld b, a
    ld hl, wLiftYPos
    ld e, 2
.platform
    ld a, [hl+]
    add a, 16                ; candidates YPos+15 down to YPos+10
    ld d, 6
.row
    dec a
    cp b
    jr z, .on
    dec d
    jr nz, .row
    dec e
    jr nz, .platform
    ret
.on
    dec hl                   ; the YPos that matched: [hl+] left us one past it
    ld a, [hl]
    add a, LIFT_STAND
    ld [wPlayerY], a
    ld a, 1
    ld [wPlayerOnLift], a
    xor a
    ld [wPlayerInAir], a
    ret

; ---------------------------------------------------------------------------
; CheckLiftFalling: the Z80's other half (Chuckie.asm:2698), run every tick
; once Harry is riding. Off the end of the platform he stops riding and starts
; the step-off window, facing the way he was walking -- but PlayerOnLift stays
; set, because in the original only a jump clears it. What that buys, on the
; levels with lifts, is a Harry who keeps drifting upwards after he steps off;
; it is faithfully odd, and the Z80 does it on purpose (nothing else writes
; $7355 anywhere in the source).
; ---------------------------------------------------------------------------
CheckLiftFalling:
    ld a, [wPlayerOnLift]
    and a
    ret z
    ld a, [wLiftX]
    cp LIFT_NONE
    ret z
    sub LIFT_HALF
    ld b, a
    ld a, [wPlayerX]
    cp b
    jr c, .off
    sub 19
    cp b
    ret c                    ; still over the platform
.off
    ld a, 1
    ld [wPlayerInAir], a
    ld a, [wPlayerDirection]
    and a
    ld a, $FF                ; facing left, so the step-off drifts left
    jr nz, .set
    ld a, 1
.set
    ld [wPlayerJumpDirection], a
    ld a, 4
    ld [wInAirCounter], a
    ret

; ---------------------------------------------------------------------------
; DrawHarry: fill in Harry's four OAM entries of the shadow. Visible frame.
;
; Sprite screen row is 167 - y (y is the top of the 16x16 sprite), and OAM
; stores screen row + 16. y + SCY is always 96..167, so the result is always
; 16..87 and never wraps off screen. The x likewise has SCX subtracted; the
; camera clamps guarantee that lands in 1..157, so he is always on screen and
; the two halves never wrap either.
; ---------------------------------------------------------------------------
DrawHarry:
    ld a, [wScrollY]
    ld c, a
    ld a, [wPlayerY]
    add a, c
    ld c, a
    ld a, OAM_ROW_BASE
    sub c
    ld b, a                  ; b = OAM y of the top half
    ld a, [wScrollX]
    ld c, a
    ld a, [wPlayerX]
    sub c
    add a, OAM_COL_OFFSET
    ld d, a                  ; d = OAM x of the left half

    ; Sprite number is frame + direction in the Z80; climbing is direction $0D,
    ; which lands on frames 13-16 of its table. Our table packs the three sets
    ; together, so climbing is frames 8-11 instead.
    ld a, [wPlayerDirection]
    cp DIR_CLIMB
    ld a, [wPlayerAnimFrame]
    jr nz, .walking
    add a, 8
    jr .have_frame
.walking
    ld e, a
    ld a, [wPlayerDirection]
    add a, e
.have_frame
    add a, a
    add a, a                 ; * 4 tiles per frame
    add a, HARRY_TILE_BASE
    ld e, a                  ; e = the frame's top-left tile

    ld hl, wOamShadow
    ; top-left
    ld a, b
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    ld [hl+], a
    xor a
    ld [hl+], a
    ; top-right
    ld a, b
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    inc a
    ld [hl+], a
    xor a
    ld [hl+], a
    ; bottom-left
    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    add a, 2
    ld [hl+], a
    xor a
    ld [hl+], a
    ; bottom-right
    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    add a, 3
    ld [hl+], a
    xor a
    ld [hl+], a
    ret

; ---------------------------------------------------------------------------
; ResetHens: load this level's hen spawns out of HenStarts into wHens.
; HenStarts is 21 bytes per level: [count][x,y,dir,frame] x 5, all five of them real
; -- from counter 24 the Z80 spawns every slot the table holds (`CP $18` -> $14 =
; 20 bytes), so the emitter writes the source's own five records and not the
; level's count padded with blanks.
; ---------------------------------------------------------------------------
ResetHens:
    ; Fill every slot with the Z80's not-in-use marker first, so whatever the
    ; level's record does not cover is already marked empty and the copy below
    ; needs no bookkeeping. (HEN_NONE cannot collide with a live x: x is the
    ; sprite's left edge and never gets near $FF.)
    ld hl, wHens
    ld a, HEN_NONE
    ld b, HEN_MAX * 4
.zero
    ld [hl+], a
    dec b
    jr nz, .zero

    ; The Z80 skips the hen setup between the ninth and the seventeenth level
    ; (`CP $08` / `CP $10`, Chuckie.asm:5955-5961): on those the hen house is
    ; empty and the mother duck is out of her cage instead. The fill above has
    ; already emptied every slot, so skipping is all it takes.
    ld a, [wCurrentLevel]
    cp 8
    jr c, .spawn
    cp 16
    jr c, .done

.spawn
    ld hl, HenStartPtrs
    call GetLevelEntry
    ld a, [de]               ; the level's own count, in hens
    inc de
    ; From the twenty-fifth level the Z80 overwrites that count with $14
    ; (`CP $18`, :5974-5978) -- 20 bytes, i.e. all five slots -- so those levels
    ; run every hen the table holds, the ones its count leaves idle included.
    ; Nothing is invented for them: gbdata emits the source's own five records,
    ; and build() asserts the spare ones are real hen records.
    ld c, a
    ld a, [wCurrentLevel]
    cp 24
    ld a, c
    jr c, .count_ok
    ld a, HEN_MAX
.count_ok
    add a, a
    add a, a                 ; hens -> bytes of hen data
    ld b, a
    ld hl, wHens
.copy
    ld a, b
    and a
    jr z, .done
    ld a, [de]
    ld [hl+], a
    inc de
    dec b
    jr .copy

.done
    call HenSpeed
    ld [wHenTick], a
    xor a
    ld [wCurrentHen], a
    ld [wHenFrameCtr], a
    ld [wPlayerDead], a
    ret

; ---------------------------------------------------------------------------
; HenSpeed: the ticks between hen steps, in A -- HEN_SPEED, or one less from
; the thirty-third level. The Z80 reloads the countdown from 3 and takes one
; off past `CP $20` (:2135-2145), so the birds cover the same ground a third
; faster on the fifth lap. HL is left alone: UpdateHens calls this holding it.
; ---------------------------------------------------------------------------
HenSpeed:
    ld a, [wCurrentLevel]
    cp 32
    ld a, HEN_SPEED
    ret c
    dec a
    ret

; ---------------------------------------------------------------------------
; UpdateHens: one gameplay tick's worth of hen -- at most one hen, and only
; every HEN_SPEED ticks. The Z80's ProcessHens (Chuckie.asm:644).
; ---------------------------------------------------------------------------
UpdateHens:
    ld hl, wHenTick
    dec [hl]
    ret nz
    call HenSpeed
    ld [hl], a

    ld hl, wHenFrameCtr
    inc [hl]

    ; The original's gates are not on the counter's parity. Having incremented
    ; it, the Z80 reads mem[Counter] -- the byte at the address the counter
    ; holds, on the Spectrum the ROM -- and takes bit 0 for the gate that lets
    ; a hen think about a ladder on only some of its steps, and bit 1 for which
    ; side it probes first (:9133, :91c7, :9237, :9228). The shape of that
    ; matters more than the source: the counter advances 5 per visit to a slot
    ; and a walking hen moves 4px, so a plain bit of the counter is the hen's
    ; own x phase in disguise, and the lookahead is then always armed or never.
    ; Mixing the byte with its nibble swap stands in for the fixed but
    ; arbitrary byte the original read, and its bits do not track that phase.
    ld a, [hl]
    ld b, a
    swap b
    xor b
    ld [wHenGate], a

    ld hl, wCurrentHen
    inc [hl]
    ld a, [hl]
    cp HEN_MAX
    jr c, .slot
    xor a
    ld [hl], a
.slot
    add a, a
    add a, a
    ld e, a
    ld d, 0
    ld hl, wHens
    add hl, de
    ld a, [hl]
    cp HEN_NONE
    ret z                    ; slot not in use
    ; The SM83 has no `ld [nn],hl`, so the record's address goes out a byte at
    ; a time. StoreHen picks it up the same way.
    ld a, l
    ld [wHenSlot], a
    ld a, h
    ld [wHenSlot + 1], a
    ld a, [hl]
    ld [wHenX], a
    inc hl
    ld a, [hl]
    ld [wHenY], a
    inc hl
    ld a, [hl]
    ld [wHenDir], a
    inc hl
    ld a, [hl]
    ld [wHenAnim], a

    ld a, [wHenDir]
    cp HEN_PECK + 1
    jp nc, HenPeck
    cp HEN_DOWN
    jp nc, HenClimb
    ; fall through

; ---------------------------------------------------------------------------
; HenWalk: a hen facing left or right.
;
; It probes the cell its leading edge would step onto, one pixel below the
; feet: blank or an egg turns it around, a ladder or a platform lets it carry
; on. Birdseed straight ahead is eaten instead, which starts a peck.
;
; The probes only run when x is 8-aligned. The hen steps 4px at a time, so that
; is every other step -- without the gate both steps would test the same cell.
; ---------------------------------------------------------------------------
HenWalk:
    ld a, [wHenX]
    and $04
    jr z, .check
    jp HenStepX              ; half way between cells: nothing to look at

.check
    ; The probe column: x+8 going right, x-8 going left. The Z80 computes x+8
    ; and, for a left-facing hen, subtracts 16 from that; either carry out is
    ; its off-screen test, so the same subtraction both aims the probe and
    ; turns the hen at the edge.
    ld a, [wHenX]
    add a, 8
    jp c, HenTurnX           ; x+8 ran off the right edge
    ld c, a
    ld a, [wHenDir]
    cp HEN_RIGHT
    jr z, .have_col
    ld a, c
    sub 16
    jp c, HenTurnX           ; x < 8, off the left edge
    ld c, a
.have_col
    ; The column stays in E, because GetMapAddr takes y in D and x in E and
    ; clobbers BC.
    ld a, [wHenY]
    ld d, a
    ld e, c
    call GetMapAddr
    ld a, [hl]
    cp TILE_BIRDSEED
    jr z, .seed

    ; The cell it would step onto, one pixel lower. GetMapAddr leaves DE
    ; alone, so only y needs setting.
    dec d
    call GetMapAddr
    ld a, [hl]
    and a
    jp z, HenTurnX           ; a hole: turn around
    cp TILE_EGG
    jp c, HenStepX           ; a ladder half (1 or 2): carry on
    cp TILE_PLATFORM
    jp z, HenStepX           ; ground: carry on
    jp HenTurnX              ; an egg, seed or the cage: turn around

.seed
    ; Eat it, and carry dir + HEN_PECK for one step -- 7 going left, 8 going
    ; right. The peck itself takes the step; the hen does not move onto it.
    call ClearCell
    ld a, [wHenDir]
    add a, HEN_PECK
    ld [wHenDir], a
    jp StoreHen

; ---------------------------------------------------------------------------
; HenTurnX: reverse a left/right hen, then still take this step -- the Z80
; changes direction and falls straight into the move, so a hen at the screen
; edge turns and walks away in the same tick rather than sticking.
; ---------------------------------------------------------------------------
HenTurnX:
    ld a, HEN_DOWN
    ld hl, wHenDir
    sub [hl]
    ld [hl], a
    ; fall through

; ---------------------------------------------------------------------------
; HenStepX: shift a left/right hen 4px. The Z80's HenOnPlatform
; (Chuckie.asm:731), which is also where a walking hen notices a ladder.
;
; There is no edge test here: HenWalk's probe has already turned any hen whose
; next step would leave the screen, and this routine is reached from there and
; from the mid-cell shortcut. Adding one would be a second, divergent answer.
; ---------------------------------------------------------------------------
HenStepX:
    ld a, [wHenDir]
    cp HEN_RIGHT
    jr z, .right
    ld hl, wHenX
    ld a, [hl]
    sub 4
    ld [hl], a
    jr .moved
.right
    ld hl, wHenX
    ld a, [hl]
    add a, 4
    ld [hl], a
.moved
    ; Advance the walk cycle. The Z80 passes a frame number derived from the
    ; direction and never cycles it, but its frame selection reads past the end
    ; of the hen table (see the note in gbdata.py), so there is no faithful
    ; behaviour to keep and a hen whose legs never move reads as broken.
    ld hl, wHenAnim
    inc [hl]

    ; The ladder lookahead, which is what turns a hen walking past a ladder
    ; into one that climbs it. It runs on the step that lands mid-cell --
    ; BIT 2 of the NEW x -- and then only when bit 0 of the gate byte is
    ; clear, and probes for the ladder's left half just below the feet and
    ; just above the head. The Z80 takes the order of those two probes from
    ; bit 1 of the same byte (:91c7, below the feet when it is set); this
    ; always tries below first, which is the direction it picks half the time.
    ; Only when a ladder runs both under the hen and over its head can the two
    ; disagree, and both answers are ones the original gives.
    ld a, [wHenX]
    and $04
    jp z, StoreHen
    ld a, [wHenGate]
    and $01
    jp nz, StoreHen

    ld a, [wHenY]
    sub 8
    ld d, a
    ld a, [wHenX]
    ld e, a
    call GetMapAddr
    ld a, [hl]
    cp TILE_LADDERLEFT
    jr z, .down

    ld a, [wHenY]
    add a, 16
    ld d, a
    ld a, [wHenX]
    ld e, a
    call GetMapAddr
    ld a, [hl]
    cp TILE_LADDERLEFT
    jp nz, StoreHen
    ld a, HEN_UP
    jr .climb
.down
    ld a, HEN_DOWN
.climb
    ld [wHenDir], a
    jp StoreHen

; ---------------------------------------------------------------------------
; HenClimb: a hen on a ladder. y is Cartesian, so HEN_DOWN is y-4 and HEN_UP is
; y+4 -- "down" means down the screen, toward y=0.
;
; Every other step, once y is cell-aligned, it looks for the ladder carrying on
; ahead and reverses if it has run out. And on an aligned y it looks to either
; side at y-8 for a platform to step off onto, which is how a hen leaves a
; ladder with no tile telling it to.
; ---------------------------------------------------------------------------
HenClimb:
    ld a, [wHenY]
    and $04
    jr nz, .move             ; between cells: nothing to look at
    ld a, [wHenDir]
    cp HEN_DOWN
    jr z, .probe_ladder
    ld a, [wHenY]
    add a, 16
    jr .have_ladder
.probe_ladder
    ld a, [wHenY]
    sub 8
.have_ladder
    ld d, a
    ld a, [wHenX]
    ld e, a
    call GetMapAddr
    ld a, [hl]
    cp TILE_LADDERLEFT
    jr z, .move
    ld a, 7                  ; 7 - dir, so down <-> up
    ld hl, wHenDir
    sub [hl]
    ld [hl], a

.move
    ld a, [wHenDir]
    cp HEN_DOWN
    jr z, .down
    ld hl, wHenY
    inc [hl]
    inc [hl]
    inc [hl]
    inc [hl]
    jr .moved
.down
    ld hl, wHenY
    ld a, [hl]
    sub 4
    ld [hl], a
.moved
    ; Stepping off sideways. Only on an aligned y and with bit 0 of the gate
    ; byte clear -- the Z80's C gate, which is why hens leave ladders at a
    ; stately pace.
    ld a, [wHenY]
    and $04
    jp nz, StoreHen
    ld a, [wHenGate]
    and $01
    jp nz, StoreHen
    ld a, [wHenY]
    sub 8
    ld [wHenProbe], a

    ; Bit 1 of the gate byte picks which side is tried first -- right when it
    ; is clear, left when it is set. Both are tried; this only decides the
    ; order, so a hen between two platforms alternates rather than always
    ; stepping off the same way.
    ld a, [wHenGate]
    and $02
    ld a, HEN_RIGHT
    jr z, .first
    ld a, HEN_LEFT
.first
    ld b, a
    call HenProbeSide
    and a
    jr nz, .done
    ld a, b
    xor HEN_LEFT ^ HEN_RIGHT
    ld b, a
    call HenProbeSide
.done
    jp StoreHen

; ---------------------------------------------------------------------------
; HenProbeSide: B = HEN_LEFT or HEN_RIGHT. If the neighbouring cell that way,
; at wHenProbe, is a platform, point the hen that way and return A = 1.
;
; A hen is 16px wide, so its x is the left of its two cells: the cell beside it
; is x-8 going left and x+16 going right (:923d, :9252). Probing x+8 for the
; right read the hen's own right half -- on a ladder, its right ladder tile --
; so the platform the probe was after was only ever found there by coincidence.
; ---------------------------------------------------------------------------
HenProbeSide:
    push bc
    ld a, b
    cp HEN_RIGHT
    ld a, [wHenX]
    jr nz, .left
    add a, 16
    jr c, .no
    jr .go
.left
    sub 8
    jr c, .no
.go
    ld e, a
    ld a, [wHenProbe]
    ld d, a
    call GetMapAddr
    ld a, [hl]
    cp TILE_PLATFORM
    jr nz, .no
    pop bc
    ld a, b
    ld [wHenDir], a
    ld a, 1
    ret
.no
    pop bc
    xor a
    ret

; ---------------------------------------------------------------------------
; HenPeck: dir is 7 (pecking left) or 8 (right). One step is spent pecking and
; the next restores the walk direction, so a peck costs two hen-steps and shows
; the pecking pose for one of them.
; ---------------------------------------------------------------------------
HenPeck:
    ld a, [wHenDir]
    sub HEN_PECK
    ld [wHenDir], a
    ; fall through

; ---------------------------------------------------------------------------
; StoreHen: write the scratch hen back into its record.
; ---------------------------------------------------------------------------
StoreHen:
    ld a, [wHenSlot]
    ld l, a
    ld a, [wHenSlot + 1]
    ld h, a
    ld a, [wHenX]
    ld [hl+], a
    ld a, [wHenY]
    ld [hl+], a
    ld a, [wHenDir]
    ld [hl+], a
    ld a, [wHenAnim]
    ld [hl], a
    ret

; ---------------------------------------------------------------------------
; DrawLifts: two OAM entries per platform, after the hens' twenty. Visible
; frame -- see wOamShadow.
;
; A platform is 16 px wide and 4 px thick in the source -- a Spectrum screen
; write of two bytes over four pixel rows -- so it is two of our 8x8 tiles side
; by side, both showing the bar in their top half.
; ---------------------------------------------------------------------------
DrawLifts:
    ld a, [wLiftX]
    cp LIFT_NONE
    jr z, .hide
    ld a, [wScrollX]
    ld c, a
    ld a, [wLiftX]
    sub c
    add a, OAM_COL_OFFSET
    ld d, a                  ; d = OAM x of the left half
    ld a, [wScrollY]
    ld c, a                  ; c = SCY
    ld hl, wOamShadow + LIFT_OAM * 4
    ld a, [wLiftYPos]
    call DrawOneLift
    ld a, [wLiftYPos + 1]
    call DrawOneLift
    ret
.hide
    ld hl, wOamShadow + LIFT_OAM * 4
    ld b, 4                  ; two entries per platform, and there are two of them
    xor a
.hide_entry
    ; y = 0 puts the entry above the screen, which is the whole of hiding it --
    ; its column, tile and attribute are never reached. ONLY the y is written, so
    ; nothing past the platforms is touched. The count used to be 2, which hid
    ; the near platform and stopped: on a level with no lift the far one is the
    ; platform of the level before it, still on the screen.
    ld [hl], a
    inc hl
    inc hl
    inc hl
    inc hl
    dec b
    jr nz, .hide_entry
    ret

; ---------------------------------------------------------------------------
; DrawOneLift: A = the platform's YPos, C = SCY, D = the left half's OAM x,
; HL = its first OAM entry. Leaves HL on the next platform's entries.
; ---------------------------------------------------------------------------
DrawOneLift:
    add a, c
    ld b, a
    ld a, LIFT_ROW_BASE
    sub b                    ; the same 8-bit wrap the player and hens use, so
    ld b, a                  ; a platform the camera hides stays hidden
    ld a, b
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, LIFT_TILE_BASE
    ld [hl+], a
    ld a, LIFT_OBP
    ld [hl+], a
    ld a, b
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, LIFT_TILE_BASE
    ld [hl+], a
    ld a, LIFT_OBP
    ld [hl+], a
    ret

; ---------------------------------------------------------------------------
; DrawHens: four OAM entries per live hen, after Harry's. Visible frame.
;
; The transform is Harry's except in the row's base: OAM row = HEN_OAM_ROW_BASE
; - (y + SCY), column = x - SCX. Both subtractions are 8-bit and wrap as they do
; for him -- and a hen the camera has scrolled past lands outside 0..167, where
; the hardware hides it, so there is nothing to clip.
; ---------------------------------------------------------------------------
DrawHens:
    ld b, 0
.slot
    ld a, b
    add a, a
    add a, a
    ld e, a
    ld d, 0
    ld hl, wHens
    add hl, de
    ld a, [hl]
    cp HEN_NONE
    jr z, .next
    ld [wDrawX], a
    inc hl
    ld a, [hl]
    ld [wDrawY], a
    inc hl
    ld a, [hl]
    ld [wDrawDir], a
    inc hl
    ld a, [hl]
    ld [wDrawAnim], a

    ld a, b
    swap a                   ; *16, a slot's worth of OAM
    add a, 16                ; Harry owns the first four entries
    ld e, a
    ld d, 0
    ld hl, wOamShadow
    add hl, de
    push bc
    call DrawOneHen
    pop bc
.next
    inc b
    ld a, b
    cp HEN_MAX
    jr c, .slot
    ret

; ---------------------------------------------------------------------------
; DrawOneHen: HL = this hen's first OAM entry, wDrawX/Y/Dir/Anim unpacked.
;
; Which of the eight hen frames to show is chosen here, not translated. The
; Z80's own selection (DrawHenFrame, Chuckie.asm:1045) alternates the pose by
; testing the hen's x and y against 4, because a Spectrum screen write is
; byte-aligned: its picture lands on a byte whatever x is, so it draws the +4
; copy of the art whenever x is at the half cell. An OBJ takes a pixel X and
; this routine adds the OAM column to x itself, so that compensation is not
; wanted and gbdata takes the 4px back off frames 2/3 and 4/5 at extraction.
; What is left of the Z80's x and y tests is the pose choice: the leg positions
; alternate with the step, which is what those tests were doing by accident (a
; 4px step flips that bit every other one), so the port alternates on the
; animation counter and every frame stands at the hen's own x.
;
; The source's eight blocks are: 0/1 standing left/right, 2/3 the two climbing
; poses, 4/5 walking left/right, and 6/7 the eating poses -- but 6/7 are not
; usable art (they are a merged composite, see the note in gbdata.py), so a
; pecking hen keeps the standing pose and the peck reads as the pause where it
; stops. The walking and climbing pairs are the two poses the animation
; alternates.
;
; Hens carry attribute $10, selecting OBP1, so they read as a different thing
; from Harry even though both are drawn from the same tile ink.
; ---------------------------------------------------------------------------
DrawOneHen:
    ld a, [wDrawDir]
    cp HEN_PECK
    jr nc, .peck
    cp HEN_DOWN
    jr nc, .climb
    ; Walking: 0 standing left / 1 standing right, and 4/5 are the same two
    ; with the legs apart.
    dec a
    ld e, a
    ld a, [wDrawAnim]
    and 1
    jr z, .tile
    ld a, e
    add a, 4
    ld e, a
    jr .tile
.peck
    sub HEN_PECK             ; 7/8 -> 1/2
    dec a                    ; -> 0/1, the standing pose
    ld e, a
    jr .tile
.climb
    ld e, 2                  ; the two climbing poses are adjacent blocks
    ld a, [wDrawAnim]
    and 1
    jr z, .tile
    inc e
.tile
    ld a, e
    add a, a
    add a, a                 ; four tiles a frame
    add a, HEN_TILE_BASE
    ld e, a                  ; e = the frame's top-left tile

    ld a, [wScrollY]
    ld c, a
    ld a, [wDrawY]
    add a, c
    ld c, a
    ld a, HEN_OAM_ROW_BASE
    sub c
    ld b, a                  ; b = OAM row of the top half
    ld a, [wScrollX]
    ld c, a
    ld a, [wDrawX]
    sub c
    add a, OAM_COL_OFFSET
    ld d, a                  ; d = OAM column of the left half

    ld a, b
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    ld [hl+], a
    ld a, $10
    ld [hl+], a
    ld a, b
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    inc a
    ld [hl+], a
    ld a, $10
    ld [hl+], a
    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    add a, 2
    ld [hl+], a
    ld a, $10
    ld [hl+], a
    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    add a, 3
    ld [hl+], a
    ld a, $10
    ld [hl], a
    ret

; ---------------------------------------------------------------------------
; DrawDuck: the mother duck's four OAM entries, after the lifts'. Visible
; frame -- see wOamShadow.
;
; Harry's transform exactly, not the hens': the Z80 draws the duck through the
; same DrawSpriteNum it draws Harry through, so its y is the TOP of the 16x16
; box and its x the left edge. (A hen's record is anchored at its feet, which is
; why it needs HEN_OAM_ROW_BASE; the duck does not.) Its caged position lands it
; on the cage's top two rows -- x 8..23, y 152..167 at SCX 0, which is level
; columns 1-2 of the five-row cage.
;
; It draws what the last update decided and nothing else. Both the pose and the
; facing are settled there (UpdateDuck), so the duck's position, its wing and
; its direction all change together once per DUCK_SPEED of frames -- which is
; what the Z80 does, because MoveMotherDuck both moves it and draws it, and the
; frame it draws with is the flip it just computed (:3471-3483).
;
; Reading the facing off Harry HERE instead -- which this did -- puts it on the
; frame clock rather than the duck's: the duck's x is frozen for twelve frames
; while Harry's is not, so walking Harry past it turns the duck on a frame that
; is not one of its steps. One step per beat is a wing beat; a second one is the
; jitter this was asked to fix.
;
; So: the pose is the frame (wDuckFrame), the facing is OAM's X-flip and a swap
; of the halves (wDuckFace). The attribute is $10 -- the hens' palette, it is a
; bird, and the level draws both as the same ink -- plus $20 when it is flipped.
; ---------------------------------------------------------------------------
DrawDuck:
    ld a, [wDuckFrame]       ; the pose picks the tiles -- both poses are the
    add a, a                 ; right-facing bird, so the facing is drawn by
    add a, a                 ; flipping and swapping the halves, not by a
    add a, DUCK_TILE_BASE    ; second set of tiles
    ld e, a

    ld a, [wScrollY]
    ld c, a
    ld a, [wDuckY]
    add a, c
    ld c, a
    ld a, OAM_ROW_BASE
    sub c
    ld b, a                  ; b = the OAM row of the top half
    ld a, [wScrollX]
    ld c, a
    ld a, [wDuckX]
    sub c
    add a, OAM_COL_OFFSET
    ld d, a                  ; d = the OAM column of the left half

    ld hl, wOamShadow + DUCK_OAM * 4
    ld a, [wDuckFace]
    and a
    jr nz, .left

; --- right: the frame's own four tiles, TL TR BL BR -------------------------
    ld a, b
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    ld [hl+], a
    ld a, $10
    ld [hl+], a
    ld a, b
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    inc a
    ld [hl+], a
    ld a, $10
    ld [hl+], a
    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    add a, 2
    ld [hl+], a
    ld a, $10
    ld [hl+], a
    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    add a, 3
    ld [hl+], a
    ld a, $10
    ld [hl], a
    ret

; --- left: the same art mirrored, which on OAM is attribute bit 5 ($30 =
; --- OBP1 | X-flip) plus a swap of each half's columns. Flipped, the tile at
; --- column d is the frame's top-RIGHT one and the tile at d+8 its top-left --
; --- which is exactly the source's frame 10, because 10 is 8 mirrored pixel
; --- for pixel (asserted in gbdata.duck_frames). So the facing costs no tiles.
.left
    inc e                    ; e is now the frame's top-right tile

    ld a, b
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    ld [hl+], a
    ld a, $30
    ld [hl+], a

    ld a, b
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    dec a
    ld [hl+], a
    ld a, $30
    ld [hl+], a

    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    ld [hl+], a
    ld a, e
    add a, 2                 ; the frame's bottom-right tile
    ld [hl+], a
    ld a, $30
    ld [hl+], a

    ld a, b
    add a, 8
    ld [hl+], a
    ld a, d
    add a, 8
    ld [hl+], a
    ld a, e
    inc a                    ; ...and its bottom-left
    ld [hl+], a
    ld a, $30
    ld [hl], a
    ret

; ---------------------------------------------------------------------------
; CollidePlayerAndHen: the Z80's overlap test (Chuckie.asm:2986), run against
; every live hen every frame.
;
;   hen_x - 8 < player_x <= hen_x + 5
;   hen_y     < player_y <= hen_y + 28
;
; The original reaches this twice. Geometrically while Harry is airborne, and
; on the ground implicitly: the hen lives in the background map, so drawing
; one where Harry already stands clobbers the tiles saved behind him. That
; second path is an artifact of hens being background, and ours are sprites, so
; it is gone -- which means the geometric test has to be run always, not just
; in the air.
; ---------------------------------------------------------------------------
CollidePlayerAndHen:
    ld a, [wPlayerDead]
    and a
    ret nz
    ld de, wHens
    ld b, HEN_MAX
.hen
    ld a, [de]
    cp HEN_NONE
    jr z, .next

    ; The four tests are the Z80's, with HL on the player and the hen's x in
    ; A -- `cp [hl]` is the only compare the SM83 has against memory, so the
    ; operands have to sit this way round.
    ld hl, wPlayerX
    add a, 1
    jr c, .next              ; hen_x+1 wrapped, so hen_x is 255
    add a, 4                 ; hen_x + 5
    cp [hl]
    jr c, .next              ; hen_x+5 < player_x
    sub 13                   ; hen_x - 8
    jr nc, .x_lo
    xor a                    ; hen_x < 8: the Z80 clamps the bound to 0
.x_lo
    cp [hl]
    jr nc, .next             ; hen_x-8 >= player_x

    inc hl
    inc de
    ld a, [de]
    dec de                   ; a = hen_y
    cp [hl]
    jr nc, .next             ; hen_y >= player_y
    add a, 28                ; the hen is 28px tall
    cp [hl]
    jr c, .next              ; hen_y+28 < player_y

    jp KillPlayer

.next
    inc de
    inc de
    inc de
    inc de
    dec b
    jr nz, .hen
    ret

; ---------------------------------------------------------------------------
; ResetDuck: the duck's opening state, called from LoadLevel with the rest.
;
; The Z80's initial block (:6112) puts it at $08/$98 -- the cage -- which is
; also where it is re-planted every update while the counter is below
; DUCK_FREE_FROM. So the reset is the same number twice, and from level 9 the
; duck starts caged and flies out on its own.
; ---------------------------------------------------------------------------
ResetDuck:
    ld a, DUCK_CAGE_X
    ld [wDuckX], a
    ld a, DUCK_CAGE_Y
    ld [wDuckY], a
    xor a
    ld [wDuckVelX], a
    ld [wDuckVelY], a
    ld [wDuckFace], a
    ld [wDuckFrame], a
    ld a, DUCK_SPEED
    ld [wDuckTick], a
    ret

; ---------------------------------------------------------------------------
; UpdateDuck: one gameplay tick of the mother duck -- every DUCK_SPEED of them,
; the Z80's MoveMotherDuck (Chuckie.asm:3364).
;
; It chases Harry: each axis' velocity steps one per update toward him and
; saturates at ±5, then the position moves by it and turns round at the level's
; edges. The chase is crude and so is the original's -- it will happily
; overshoot, and the overshoot is what makes it oscillate around him.
;
; Below DUCK_FREE_FROM the whole thing is thrown away at the end: the duck is
; put back in the cage every update, so it never moves while it is caged and its
; velocities spin up and down in place, exactly as they do in the Z80.
; ---------------------------------------------------------------------------
UpdateDuck:
    ld hl, wDuckTick
    dec [hl]
    ret nz
    ld a, DUCK_SPEED
    ld [hl], a

    ; The wing flap, one pose an update. Toggled HERE, before the plant's own
    ; gate at the end, because the Z80's MotherDuckFrame is toggled in the draw
    ; path (`XOR $01`, Chuckie.asm:3481) and every level reaches that -- only the
    ; movement below the gate is the loose duck's. So the caged duck flaps too.
    ld hl, wDuckFrame
    ld a, [hl]
    xor $01
    ld [hl], a

    ld a, [wPlayerX]
    ld b, a
    ld a, [wDuckX]
    ld hl, wDuckVelX
    call DuckVelocity
    ld a, [wPlayerY]
    ld b, a
    ld a, [wDuckY]
    ld hl, wDuckVelY
    call DuckVelocity

    ; x first, as the source does -- and the Z80 branches on the SIGN of the
    ; velocity before it looks at the edge, because `ADD A,vel`'s carry means
    ; opposite things the two ways round. A leftward velocity is $FB..$FF, so
    ; the carry is set whenever the step does NOT wrap below zero, i.e. when it
    ; is perfectly fine. Read as "the step would have left 0 behind" -- which is
    ; how this started -- a leftward duck turns round on every single update,
    ; jumps 2*vel the wrong way and pins its velocity to +5.
    ld a, [wDuckX]
    ld hl, wDuckVelX
    bit 7, [hl]
    jr nz, .x_neg
    add a, [hl]
    cp DUCK_X_MAX            ; $EE reached: the far edge
    jr nc, .x_turn
    ld [wDuckX], a
    jr .y
.x_neg
    add a, [hl]
    jr nc, .x_turn           ; wrapped below zero: the near edge
    ld [wDuckX], a
    jr .y
.x_turn
    ; A refused step is undone and reflected rather than clamped, and the
    ; velocity is flipped to the far end of its range -- which is what
    ; `SUB (IX+$72)` twice followed by `LD (IX+$72),$FB` is.
    ld c, [hl]               ; the velocity, which is what gets undone
    ld a, [wDuckX]
    sub c
    sub c
    ld [wDuckX], a
    ld a, -DUCK_VEL_MAX
    bit 7, c                 ; moving left when it hit the near edge?
    jr z, .x_set
    ld a, DUCK_VEL_MAX
.x_set
    ld [hl], a
.y
    ; y is only its two bounds, no sign test: it has a bound at each end, so
    ; the value itself says which edge was reached ($A6 is the top, $14 the
    ; bottom -- the level's y is Cartesian). A step below $14 lands under 20
    ; whether or not it wrapped, so the compare catches the near edge too.
    ld a, [wDuckY]
    ld hl, wDuckVelY
    add a, [hl]
    cp DUCK_Y_MAX
    jr nc, .y_turn
    cp DUCK_Y_MIN
    jr c, .y_turn
    ld [wDuckY], a
    jr .plant
.y_turn
    ld c, [hl]
    ld a, [wDuckY]
    sub c
    sub c
    ld [wDuckY], a
    ld a, -DUCK_VEL_MAX
    bit 7, c
    jr z, .y_set
    ld a, DUCK_VEL_MAX
.y_set
    ld [hl], a
.plant
    ; The Z80's `LD A,(CurrentLevel) / CP $08 / JR NC` -- levels 9 and up only.
    ; This is last, after the bounds, so the caged duck is planted at the cage
    ; whatever the chase just did with it.
    ld a, [wCurrentLevel]
    cp DUCK_FREE_FROM
    jr nc, .face
    ld a, DUCK_CAGE_X
    ld [wDuckX], a
    ld a, DUCK_CAGE_Y
    ld [wDuckY], a
.face
    ; Which way it faces, decided here rather than in the draw: the Z80 picks
    ; it in the same routine that moves the duck (`LD A,(PlayerX) / CP
    ; (IX+$70)`, :3471-3476) and only ever draws it from there, so it turns on
    ; the duck's own clock. After the plant, so a caged duck faces whichever way
    ; Harry last stood. DrawDuck just reads it.
    ld a, [wPlayerX]
    ld hl, wDuckX
    cp [hl]
    ld a, 0                  ; he is to its right: face that way
    jr nc, .face_set
    inc a                    ; ...and to its left: face the other
.face_set
    ld [wDuckFace], a
    ret

; ---------------------------------------------------------------------------
; DuckVelocity: A = the duck's coordinate, B = Harry's, HL = the velocity byte.
; One step toward him, saturating at ±DUCK_VEL_MAX, and nothing at all when they
; are aligned. The Z80 writes this out four times (twice for x, twice for y),
; with its `CP $06`/`CP $FA` guards spelled out as the clamps they are.
; ---------------------------------------------------------------------------
DuckVelocity:
    cp b
    ret z                    ; level with him: leave the velocity alone
    jr nc, .away             ; duck > player -> move back down/left
    inc [hl]
    ld a, [hl]
    cp DUCK_VEL_MAX + 1
    ret nz
    dec [hl]
    ret
.away
    dec [hl]
    ld a, [hl]
    cp -DUCK_VEL_MAX - 1
    ret nz
    inc [hl]
    ret

; ---------------------------------------------------------------------------
; CollidePlayerAndDuck: the Z80's duck overlap (Chuckie.asm:2545), run once a
; frame like the hen's.
;
;   duck_x - 8 <= player_x <= duck_x + 7
;   duck_y - 9 <= player_y <= duck_y + 9
;
; A window CENTRED on the duck, where the hen's is offset: the source's two
; ADD/SUB pairs are symmetric here and its `+5` is not. Written as one distance
; test an axis -- (player - duck + 8) in 0..15, (player - duck + 9) in 0..18 --
; which is the same set of pixels with none of the Z80's four clamps: on a byte
; the wrap IS the far side of the range, so `cp 16` / `ret nc` rejects both.
; ---------------------------------------------------------------------------
CollidePlayerAndDuck:
    ld a, [wPlayerDead]
    and a
    ret nz
    ld hl, wDuckX
    ld a, [wPlayerX]
    sub [hl]
    add a, 8
    cp 16
    ret nc
    inc hl
    ld a, [wPlayerY]
    sub [hl]
    add a, 9
    cp 19
    ret nc
    jp KillPlayer

; ---------------------------------------------------------------------------
; KillPlayer: Harry is caught, by a hen or by the duck. The Z80 goes to LoseLife
; (Chuckie.asm:4493) from both: the jingle, then the screen cleared and its word
; scrolled across it, and only then the level back.
;
; The freeze the port needs before the reload is that same pause, so it is spent
; on the announcement screen when there is a word for it, and on the frozen
; level when there is not. Either way wDeathTimer is left at 1: the dead branch
; in MainLoop counts it out on its next frame and does the deduction, which is
; the Z80's `DEC (HL)` on the life byte.
;
; Which word: the Z80 says "OUT OF TIME !" when the clock had already run out,
; and "game over" only once the last life is gone. A death he can come back from
; gets neither, and a timed-out one he cannot gets the clock's -- the port shows
; one screen where the Z80 shows two, and the table behind it says the rest.
; ---------------------------------------------------------------------------
KillPlayer:
    ld a, 1
    ld [wPlayerDead], a
    ld hl, LoseLifeMusic
    call StartMusic

    ld a, [wTimeUp]
    and a
    ld de, NoticeTimeUp
    jr nz, .announce
    ld a, [wLives]
    cp 1
    ld de, NoticeGameOver
    jr z, .announce
    ld a, DEATH_DELAY                ; lives in hand: the freeze, and no word
    ld [wDeathTimer], a
    ret
.announce
    ld a, 1
    ld [wDeathTimer], a              ; the notice is the freeze: it is the wait
    ld c, DEATH_DELAY
    jp ShowNotice


; ---------------------------------------------------------------------------
; ClearCell: blank the map cell at HL (a wLevelBuffer address) and queue the
; same cell in the BG map to be blanked at the next VBlank.
;
; Both halves are needed and used to be only the first: a hen eating corn
; blanked the buffer and left the corn on screen, because nothing wrote VRAM.
; Eggs would have had the same bug twice over.
;
; The BG map is the level upside down -- DrawLevel puts buffer row 0 at map row
; PLAYFIELD_ROW0/32 -- so the destination is BG_LAST_ROW - (offset & ~31) +
; (offset & 31) from the start of the map. Clobbers everything.
; ---------------------------------------------------------------------------
DEF BG_LAST_ROW EQU PLAYFIELD_ROW0     ; buffer row 0's map row

ClearCell:
    ld [hl], TILE_BLANK
    ld bc, wLevelBuffer
    ld a, l
    sub c
    ld l, a
    ld a, h
    sbc a, b
    ld h, a                  ; hl = the cell's offset in the buffer
    ld a, l
    and 31
    ld e, a
    ld d, 0                  ; de = the column
    ld a, l
    and $E0
    ld l, a                  ; hl = 32 * row  (h is already the high half)
    ld a, BG_LAST_ROW & $FF
    sub l
    ld l, a
    ld a, BG_LAST_ROW >> 8
    sbc a, h
    ld h, a                  ; hl = the map row that buffer row drew to
    add hl, de
    ld de, _SCRN0
    add hl, de
    ld a, l
    ld [wPickupAddr], a
    ld a, h
    ld [wPickupAddr + 1], a
    ld a, 1
    ld [wPickupDo], a
    ret

; ---------------------------------------------------------------------------
; AddToScore: add B to the score, counting in base ten, and pay an extra life.
;
; The Z80 walks the digit chain up from the units, carrying at 10 -- each digit
; is its own byte and the value is decimal, not binary. B is a count of ones,
; so this is `B` increments, not a numeric add.
;
; Then the extra life (Chuckie.asm:3916): every thousand points, one more.
; The Z80 reads that change off the score's THOUSANDS digit -- +1, since the
; digits run from +0 with the units at +4 -- against LastDigitValue, its shadow.
; The digit only moves every 1 000, so comparing it to the shadow is what makes
; this fire once rather than on every point. The Z80 draws a hat for the life
; and stops at six of them; this HUD shows a count instead (the divergence 6c
; settled), so a life past the sixth still shows.
;
; Not reached for a B of 0: the Z80 jumps straight to PrintScore, and the ret
; above is the same thing.
; ---------------------------------------------------------------------------
AddToScore:
    ld a, b
    and a
    ret z
    ld c, b
    ld a, $0A
.loop
    ld hl, wScore + 4
.carry
    inc [hl]
    cp [hl]
    jr nz, .next
    ld [hl], 0
    dec hl
    jr .carry
.next
    dec c
    jr nz, .loop

    ld hl, wScore + 1
    ld a, [hl]
    ld hl, wLastDigit
    cp [hl]
    ret z
    ld [hl], a
    ld hl, wLives
    inc [hl]
    ret

; ---------------------------------------------------------------------------
; ResetEggs: twelve to find. The score is NOT touched -- the Z80 zeroes it once
; in NewGame and level completion adds the time bonus to it, so zeroing here
; would throw the score away at every level change. ResetScore does the once.
; ---------------------------------------------------------------------------
ResetEggs:
    ld a, EGGS_PER_LEVEL
    ld [wEggsRemaining], a
    ret

; ---------------------------------------------------------------------------
; ResetScore: six decimal digits, all zero -- and the saved copy and the extra
; life's shadow with them. The score data block in the source begins at 002550,
; which is the author's own value and not a rule; a fresh game starts at 0.
; wScoreSaved and wLastDigit sit immediately after wScore so one loop clears all
; three, which is what NewGame needs: a new game has no banked score to fall back
; on. Zeroing the shadow is right rather than incidental -- the fresh score's
; thousands digit is 0, so nothing is owed until it moves.
; ---------------------------------------------------------------------------
ResetScore:
    xor a
    ld hl, wScore
    ld b, 13
.zero
    ld [hl+], a
    dec b
    jr nz, .zero
    ret

; ---------------------------------------------------------------------------
; SaveScore: the live score becomes the banked one. The Z80's LevelCompleted
; write-back (Chuckie.asm:4420), which runs after the bonus drain -- so the
; bonus is part of what is banked.
; ---------------------------------------------------------------------------
SaveScore:
    ld de, wScore
    ld hl, wScoreSaved
    ld bc, 6
    call MemCopy
    ret

; ---------------------------------------------------------------------------
; LoadSavedScore: the banked score becomes the live one. The Z80 reaches this
; from two places -- PlayLevel when a level starts, and HasLivesRemaining after
; a death (Chuckie.asm:4605) -- and they want the same thing here, so one
; routine serves both. On the death path it is what makes the points earned on
; the fatal attempt forfeit.
;
; The extra life's shadow is re-synced here, as the Z80's PlayLevel re-syncs
; LastDigitValue (Chuckie.asm:5947). Without it a level would pay: the live
; score drops back to the banked one, but the shadow still holds the digit the
; fatal attempt reached, so the first point earned would look like a crossing.
; ---------------------------------------------------------------------------
LoadSavedScore:
    ld de, wScoreSaved
    ld hl, wScore
    ld bc, 6
    call MemCopy
    ld a, [wScore + 1]
    ld [wLastDigit], a
    ret

; ---------------------------------------------------------------------------
; ResetLives: back to a full set. Called by NewGame only -- a level load must
; not touch it, or dying would be free.
; ---------------------------------------------------------------------------
ResetLives:
    ld a, LIVES_START
    ld [wLives], a
    ret

; ---------------------------------------------------------------------------
; NewGame: everything a game starts with, i.e. what the Z80's PressStart sets up
; before the first PlayLevel. Boot calls it, and so does game over -- which is
; the port's stand-in for the front-end 6c-2 will add.
; ---------------------------------------------------------------------------
NewGame:
    ld a, LEVEL_NUM - 1
    ld [wCurrentLevel], a
    call ResetScore
    call ResetLives
    ret

; ---------------------------------------------------------------------------
; ResetTimer: both counters for a fresh level, from PlayLevel
; (Chuckie.asm:5864).
;
; Both come off the counter and both are clamped, so both keep stepping past
; the thirty-third level the way the source's do:
;
;   Bonus+0 = min(counter + 1, 9)
;   Time+0  = 9 - min(counter >> 4, 5)
;
; So level 1 opens at a BONUS OF 100: the digits are [1,0,0] and the counter is
; decimal, so it is one hundred steps of one. The >>4 clamp takes a step off
; the clock every sixteen levels, from level 17 down to a floor of 4 from level
; 81. **Three** rules were wrong while the counter wrapped at eight, all by one
; and all from reading the source's 0-based counter as 1-based: the bonus (the
; source's operand is `INC A`, not +2), the clock (it shifts the counter itself,
; with no `INC` first), and the duck's cage (a separate constant, DUCK_FREE_FROM).
; None could be seen over eight levels -- the bonus was wrong by one, the other
; two could not fire. See PLAN.md, "The five laps".
; The Z80 zeroes the other two digits of each (Chuckie.asm:6113-6120).
; ---------------------------------------------------------------------------
ResetTimer:
    ld a, [wCurrentLevel]
    add a, 1
    cp 10
    jr c, .bonus_ok
    ld a, 9
.bonus_ok
    ld [wBonus], a
    xor a
    ld [wBonus + 1], a
    ld [wBonus + 2], a

    ld a, [wCurrentLevel]
    swap a
    and $0F                  ; the counter >> 4, the Z80's four SRLs. No `inc`
                             ; first: the source shifts CurrentLevel itself
                             ; (:5874), so the clock steps down a level later
                             ; than a 1-based reading would -- from level 17.
    cp 5
    jr c, .time_ok
    ld a, 5
.time_ok
    ld b, a
    ld a, 9
    sub b
    ld [wTime], a
    xor a
    ld [wTime + 1], a
    ld [wTime + 2], a

    ; Both dividers reset to 1, not to their reload value -- so the first step
    ; of each lands on the first tick of the level, not the tenth or fiftieth.
    ld a, 1
    ld [wBonusTick], a
    ld [wTimeTick], a
    ld [wTimerRunning], a
    xor a
    ld [wTimeUp], a
    ret

; ---------------------------------------------------------------------------
; DecDigits: decrement the three-digit decimal counter whose UNITS byte is at
; HL. One digit per byte, counted in base ten (the Z80's DecLoop1,
; Chuckie.asm:3497): decrement, and if that borrowed to $FF put 9 back and
; carry into the next digit up. Carry set means all three borrowed out, and
; the top digit is then left at $FF -- the sentinel the source writes.
; ---------------------------------------------------------------------------
DecDigits:
    ld a, TIMER_UNDERFLOW
    ld d, 3
.loop
    dec [hl]
    cp [hl]
    jr nz, .done
    dec d
    jr nz, .reset
    scf
    ret
.reset
    ld [hl], 9
    dec hl
    jr .loop
.done
    and a                    ; clear carry
    ret

; ---------------------------------------------------------------------------
; StepBonus: one step of the bonus counter. Borrowing out clears
; wTimerRunning -- the BONUS underflow is the half that returns normally
; (Chuckie.asm:3510); only the TIME one unwinds the tick.
; ---------------------------------------------------------------------------
StepBonus:
    ld hl, wBonus + 2
    call DecDigits
    ret nc
    xor a
    ld [wTimerRunning], a
    ret

; ---------------------------------------------------------------------------
; UpdateTimer: one gameplay tick for the two counters (Chuckie.asm:2080-2130).
;
; The bonus divider only runs while wTimerRunning is set -- the Z80 tests it
; before even decrementing the counter, so an expired bonus stops the divider
; too. The time divider is NOT gated: the source's TensCounter block is
; unconditional, which is why the clock is the one that can kill you.
; ---------------------------------------------------------------------------
UpdateTimer:
    ld a, [wTimerRunning]
    and a
    jr z, .time
    ld hl, wBonusTick
    dec [hl]
    jr nz, .time
    ld [hl], TIMER_BONUS_STEP
    call StepBonus

.time
    ; A stopped clock is stopped: nothing left to count down, and no second
    ; borrow-out to record. The Z80 has no equivalent check, so its digits keep
    ; stepping past $FF,$09,$09 into nonsense -- harmless there (nothing tests
    ; the digits except LoseLife, whose match therefore only lands for the nine
    ; ticks after the borrow), but not something worth reproducing. 6a killed
    ; Harry here because the clock stopping had no other way to be seen.
    ld a, [wTimeUp]
    and a
    ret nz
    ld hl, wTimeTick
    dec [hl]
    ret nz
    ld [hl], TIMER_TIME_STEP
    ld hl, wTime + 2
    call DecDigits
    ret nc
    ld a, 1
    ld [wTimeUp], a
    ret

; ---------------------------------------------------------------------------
; DrainBonus: the Z80's LevelCompleted loop (Chuckie.asm:4397) -- step the
; BONUS down to nothing, scoring a point a step, while the countdown is still
; running.
;
; A bonus of N scores N+1, and that is the original's own arithmetic: the step
; that borrows out scores too, because only the TIME borrow-out unwinds and
; this AddToScore runs regardless. Level 1 opens at 200, so a level finished
; with the bonus intact scores 201 for it.
; ---------------------------------------------------------------------------
DrainBonus:
    ld a, [wTimerRunning]
    and a
    ret z
    call SfxPickup
    call StepBonus
    ld b, 1
    call AddToScore
    jr DrainBonus

; ---------------------------------------------------------------------------
; BuildHud: fill wHudRow with the status row's tile indices. Twenty columns,
; exactly full:
;
;     col 01234567890123456789
;         S00000 E12 T900 B800
;
; Five score digits, not six: AddToScore carries DOWN from wScore+4 and never
; writes wScore+5, so the sixth is provably always zero and its column buys
; more elsewhere. Nothing is zero-suppressed -- leading zeros are the look the
; original has, and the counters are already decimal digits, so there is no
; conversion anywhere except the egg count.
; ---------------------------------------------------------------------------
BuildHud:
    ld hl, wHudRow
    ld a, HUD_TILE_BASE + HUD_CH_S
    ld [hl+], a
    ld de, wScore
    ld b, 5
.score
    ld a, [de]
    inc de
    add a, HUD_TILE_BASE
    ld [hl+], a
    dec b
    jr nz, .score

    xor a
    ld [hl+], a                       ; blank
    ld a, HUD_TILE_BASE + HUD_CH_E
    ld [hl+], a
    ld a, [wEggsRemaining]            ; the one count that needs converting
    ld b, 0
.tens
    cp 10
    jr c, .tens_done
    sub 10
    inc b
    jr .tens
.tens_done
    push af
    ld a, b
    add a, HUD_TILE_BASE
    ld [hl+], a
    pop af
    add a, HUD_TILE_BASE
    ld [hl+], a

    xor a
    ld [hl+], a                       ; blank
    ld a, HUD_TILE_BASE + HUD_CH_T
    ld [hl+], a
    ld de, wTime
    ld b, 3
.time
    ld a, [de]
    inc de
    add a, HUD_TILE_BASE
    ld [hl+], a
    dec b
    jr nz, .time

    xor a
    ld [hl+], a                       ; blank
    ; Lives, as a two-digit count rather than the Z80's row of hats: the port
    ; has one HUD row, and this is the field that had to give up its place
    ; (BONUS -- still earned, still drained into the score at level end, just
    ; no longer shown). The count is the true number of lives, where the Z80
    ; draws lives-1 hats because its last hat is left blank.
    ld a, HUD_TILE_BASE + HUD_CH_L
    ld [hl+], a
    ld a, [wLives]
    ld b, 0
    ld c, a
.lives_tens
    ld a, c
    cp 10
    jr c, .lives_done
    sub 10
    ld c, a
    inc b
    jr .lives_tens
.lives_done
    ld a, b
    add a, HUD_TILE_BASE
    ld [hl+], a
    ld a, c
    add a, HUD_TILE_BASE
    ld [hl+], a
    ; The field is L + two digits, one column narrower than the BONUS it
    ; replaced. DrawHud copies a fixed HUD_ROW_LEN bytes, so the odd column has
    ; to be written here rather than left to whatever was in the buffer.
    xor a
    ld [hl+], a                       ; blank
    ret

; ---------------------------------------------------------------------------
; DrawHud: rebuild the status row and put it in the window's map. Called from
; VBlank (VRAM is writable there) and from the load paths, which run with the
; LCD off.
; ---------------------------------------------------------------------------
DrawHud:
    call BuildHud
    ld de, wHudRow
    ld hl, HUD_MAP
    ld bc, HUD_ROW_LEN
    jp MemCopy

; ---------------------------------------------------------------------------
; The sound. One step a frame, from the VBlank handler: the APU registers are
; writable at any time, but a frame is the unit the note lengths are counted in
; and VBlank is the only place this ROM has a per-frame hook.
; ---------------------------------------------------------------------------
UpdateMusic:
    ld a, [wMusicPtr]
    ld hl, wMusicPtr + 1
    or [hl]
    ret z                          ; nothing playing: 0 is not a ROM address
    ld hl, wMusicTimer
    ld a, [hl]
    and a
    jr z, .note                    ; 0 means "the next note starts now"
    dec [hl]
    ret

; Read the next pair and start it. PlayMusic's own order, with the stream
; pointer advanced before anything can fail on it, so a terminator stops the
; tune with the pointer past it rather than replaying it.
.note
    ld a, [wMusicPtr]
    ld l, a
    ld a, [wMusicPtr + 1]
    ld h, a
    ld a, [hl+]                    ; duration, in BEEP units
    ld d, a
    ld a, [hl+]                    ; pitch, a semitone index from middle C
    ld e, a
    ld a, l
    ld [wMusicPtr], a
    ld a, h
    ld [wMusicPtr + 1], a
    ld a, d
    and a
    jr z, StopMusic

    ; The period for the pitch, then the trigger -- which is also what restarts
    ; the channel, so a repeated note is retriggered rather than run on.
    ld a, e
    add a, a                       ; pitch * 2: the table holds words
    ld hl, MusicPeriods
    add a, l
    ld l, a
    ld a, 0
    adc a, h
    ld h, a
    ld a, [hl+]
    ld [wMusicPeriod], a
    ldh [rNR13], a                 ; period, low 8 bits
    ld a, [hl]
    ld [wMusicPeriod + 1], a
    or AUDTRIGGER                  ; period bit 8, and start the note
    ldh [rNR14], a

    ; And how long it lasts: `10 / duration` BEEP units, the division the ZX
    ; ROM's calc does, times NOTE_UNIT.
    ld a, 10
    ld b, 0
.units
    cp d
    jr c, .units_done
    sub d
    inc b
    jr .units
.units_done
    ld a, b
    and a
    ret z                          ; a duration over 10: no length to give it
    ld c, a
    xor a
.mult
    add a, NOTE_UNIT
    dec c
    jr nz, .mult
    dec a                          ; this frame counts as one of them, so that
    ld [wMusicTimer], a            ; the gap between notes is exactly the note
    ret

; ---------------------------------------------------------------------------
; StartMusic: hl = a stream from src/music.asm.
;
; The pointer is the whole of "playing": a stream runs until its terminator,
; and no ROM address is 0. Starting one also re-arms the volume, which is what
; StopMusic took down.
; ---------------------------------------------------------------------------
StartMusic:
    ld a, l
    ld [wMusicPtr], a
    ld a, h
    ld [wMusicPtr + 1], a
    xor a
    ld [wMusicTimer], a
    ld a, AUDVOL_MAX
    ldh [rNR12], a
    ret

; ---------------------------------------------------------------------------
; StopMusic: the stream ended, or the level is being reloaded.
; ---------------------------------------------------------------------------
StopMusic:
    ld hl, wMusicPtr
    xor a
    ld [hl+], a
    ld [hl], a
    ld [wMusicTimer], a
    ldh [rNR12], a                 ; volume 0: channel 1 silent
    ret

; ---------------------------------------------------------------------------
; SfxPickup: a short blip for an egg or corn. Channel 4, so it never eats the
; tune; the envelope in rNR42 takes the volume down on its own while UpdateSfx
; slides the frequency.
; ---------------------------------------------------------------------------
SfxPickup:
    ld a, SFX_LEN
    ld [wSfxTimer], a
    ld a, SFX_FREQ
    ld [wSfxFreq], a
    ldh [rNR43], a
    ld a, %11110011                ; volume 15, envelope decreasing, period 3
    ldh [rNR42], a
    ld a, AUDTRIGGER
    ldh [rNR44], a
    ret

UpdateSfx:
    ld a, [wSfxTimer]
    and a
    ret z
    dec a
    ld [wSfxTimer], a
    jr z, .done
    ld hl, wSfxFreq
    add a, [hl]
    ldh [rNR43], a
    ret
.done
    xor a
    ldh [rNR42], a                 ; volume 0: the blip is over
    ret


; ---------------------------------------------------------------------------
; PlayerPickUp: the Z80's egg-and-corn check (Chuckie.asm:2233). One cell, not
; a box: (x+8, y-8) -- `LD HL,(PlayerX)` is little-endian over the adjacent
; PlayerX/PlayerY, so the SUB 8 lands on y and the ADD 8 on x.
;
; The last egg does not return here in the Z80; it unwinds the stack and
; abandons the rest of the tick. wLevelDone is that, spelled out.
; ---------------------------------------------------------------------------
PlayerPickUp:
    ld a, [wPlayerY]
    sub 8
    ld d, a
    ld a, [wPlayerX]
    add a, 8
    ld e, a
    call GetMapAddr
    ld a, [hl]
    cp TILE_EGG
    jr nz, .not_egg

    call ClearCell
    ; 10 * (min(counter >> 2, 9) + 1): the Z80's CalcLp counts in tens, and the
    ; CP/JR C before it clamps the counter. Both operands are the 0-based
    ; counter, so level 1 is 10 an egg and the multiplier steps every fourth
    ; level -- 100 an egg, the clamp, from level 37 (counter 36).
    ld a, [wCurrentLevel]
    srl a
    srl a
    cp 9
    jr c, .unclamped
    ld a, 9
.unclamped
    inc a
    ld b, a
    xor a
.tens
    add a, 10
    dec b
    jr nz, .tens
    ld b, a
    call AddToScore
    call SfxPickup

    ld hl, wEggsRemaining
    dec [hl]
    ret nz
    ld a, 1
    ld [wLevelDone], a
    ret

.not_egg
    cp TILE_BIRDSEED
    ret nz
    call ClearCell
    ld b, 5
    call AddToScore
    call SfxPickup
    ; The Z80 stores $FFFF over FiftiesCounter (Chuckie.asm:2281), which is the
    ; two adjacent dividers -- so corn pushes BOTH counts back a full period,
    ; delaying the next step of each. It does not touch the counter values.
    ld a, $FF
    ld [wBonusTick], a
    ld [wTimeTick], a
    ret

; ---------------------------------------------------------------------------
; LoadLevel: the level wCurrentLevel names, from ROM to screen and back to its
; starting state. The LCD must be off when this is called -- ClearMap and
; DrawLevel write VRAM.
; ---------------------------------------------------------------------------
LoadLevel:
    ld hl, LevelPtrs
    call GetLevelEntry
    ld hl, wLevelBuffer
    ld bc, LEVEL_WIDTH * LEVEL_HEIGHT
    call MemCopy

    call ClearMap
    ; The sprite image goes with the map. The draws below cover only the slots
    ; this level fills, so without this one that spawns fewer hens than the last
    ; keeps its birds -- and one with no lift keeps its platform. See
    ; ClearOamShadow.
    call ClearOamShadow
    call DrawLevel

    call ResetPlayer
    call ResetHens
    call ResetDuck
    call ResetLifts
    call ResetEggs
    call ResetTimer
    ; The Z80's PlayLevel starts a level on the player's banked score, which is
    ; the same thing a death's HasLivesRemaining wants -- so a death, which
    ; comes through here too, reverts the score to what it was when the level
    ; began and the points earned on the fatal attempt are gone.
    call LoadSavedScore
    call UpdateCamera
    call StopMusic

    xor a
    ld [wLevelDone], a
    ld [wPickupDo], a
    ret

; ---------------------------------------------------------------------------
; NextLevel: what the Z80's PlayLevel does after the last egg -- reload with
; the screen blanked, as the original also does, then carry on. The counter has
; no bound (the Z80's `INC (HL)`, Chuckie.asm:4434): the eight maps repeat, but
; the rules that change per lap read the counter, not the masked index, so lap
; two onwards is a higher number and not a wrap.
; ---------------------------------------------------------------------------
NextLevel:
    ; The bonus becomes score here, on completion only -- deliberately not in
    ; .reload, which a death also reaches.
    call DrainBonus
    ; ...and then the finished score is banked, after the drain so the bonus is
    ; in it. Also completion-only: a death must not bank, because the reload it
    ; goes through is what puts the banked score back.
    call SaveScore

    ld a, [wCurrentLevel]
    inc a
    ld [wCurrentLevel], a

    ; The Z80 says the level's number here, as one closes and the next loads
    ; (`LevelScrollText`, Chuckie.asm:4464, under NextPlayerPlayLevel). A death
    ; comes straight to .reload below and says nothing -- on the Spectrum that
    ; is the difference between the two paths, too.
    ld de, NoticeLevel
    ld c, NOTICE_HOLD
    call ShowNotice

    ; Falls into the reload, which is also how a death restarts the level.
.reload
    ; The reload writes VRAM, so blank the screen for the duration. Interrupts
    ; go off across it -- see LcdOffForVram for why the wait needs them off.
    di
    call LcdOffForVram
    call LoadLevel
    call DrawHud                     ; VRAM is addressable with the LCD off
    ld a, LCDC_BASE
    ldh [rLCDC], a
    ei
    ret

; ---------------------------------------------------------------------------
; The title screen -- the Z80's FrontEnd. Reached from Start, so the ROM opens
; on it, and from the death path when the last life goes.
; ---------------------------------------------------------------------------

; EnterTitle: put the title up, from wherever we were. Clears the screen and
; starts the tune. Safe with the LCD on, which is how the game-over path
; reaches it.
;
; NewGame is called here rather than when a game starts, so the score, the
; lives and the level index are a fresh game's the moment the title appears.
EnterTitle:
    di
    call LcdOffForVram               ; safe here too: the LCD is off at boot
    xor a
    ldh [rSCY], a
    ldh [rSCX], a
    call NewGame
    call DrawTitle                 ; clears the map as it goes
    ; The death that got here left its flag up. Nothing under the title reads it
    ; and StartGame clears it anyway -- but only once START is pressed, so
    ; anything waiting for that death's reload to finish would wait right past
    ; the title. It ends here instead.
    xor a
    ld [wPlayerDead], a
    ld [wOnScores], a                ; the front ends are exclusive
    ld [wOnInstr], a                 ; ...all three of them
    inc a
    ld [wOnTitle], a
    ; OBJ off: at boot nothing has written OAM, and on hardware an unwritten
    ; OAM is noise rather than the blank sprites an emulator hands back. WIN off
    ; too, so the frame is all BG -- the band belongs to a game, and the STAT
    ; handler clearing a bit that is already clear costs nothing.
    ld a, LCDC_BASE & ~(LCDCF_OBJON | LCDCF_WINON)
    ldh [rLCDC], a
    ld hl, TitleMusic
    call StartMusic
    ei
    ret

; StartGame: START on the title, or on the instructions -- both are front ends
; that begin the next game. Leaves through NextLevel.reload, which is already
; "blank the screen and load the level" -- the same path a death and a completed
; level take -- and puts the full LCDC, OBJ and WIN included, back.
;
; Both front-end flags are cleared, not just wOnTitle's: left set, either one
; short-circuits MainLoop back into the front-end branch every frame and the
; level would never tick.
StartGame:
    xor a
    ld [wOnTitle], a
    ld [wOnInstr], a
    call NextLevel.reload
    xor a
    ld [wPlayerDead], a
    ; The first playing VBlank copies the shadow out, so it has to hold this
    ; level and not the last screen's -- which is a whole front end's worth of
    ; sprites ago, or the title's blank OAM at boot.
    call DrawFrame
    ret

; DrawTitle: the title screen, into map 0. The LCD must be off, and it clears
; the map itself, so it stands alone rather than beside a ClearMap.
DrawTitle:
    call ClearMap
    ld de, TitleLines
.line
    ld a, [de]                     ; peep only: RowColAddr reads this byte
    cp $FF
    jr z, .logo                    ; the table ends -- the logo is last
    call RowColAddr                ; HL = the map cell the line starts at
    call DrawText
    jr .line
.logo
    call DrawLogo
    ; The last line is drawn from the SCORE run, not this one: the title's own
    ; glyph set holds only the letters its lines use, so "SELECT HELP" would cost
    ; it three more tiles (C, H and L) out of a VRAM two tiles from full -- and
    ; every capital is already in the run the table and the instructions share,
    ; which is resident whatever screen is up.
    ld de, TitleHelpLine
    jp DrawRunLines

; DrawText: DE = an encoded line, HL = the map cell. The lines are stored as
; 1-based indices into the title's glyph run -- 0 ends a line, and the space
; glyph is the set's first, so a 0-based scheme would confuse the two -- which
; is why the index is decremented before the run's base is added.
;
; The zero is stepped over, not left under DE: DrawTitle reads the next
; (row, col) pair straight after, and a terminator left there would be read as
; that row.
DrawText:
    ld a, [de]
    inc de
    and a
    ret z
    dec a
    add a, TEXT_TILE_BASE
    ld [hl+], a
    jr DrawText

; DrawLogo: the CHUCKIE EGG block, TITLE_LOGO_W x TITLE_LOGO_H tiles at the
; fixed corner src/title.asm carries. Same 1-based conversion, and a row is a
; row of the map, so the destination advances by a whole map line each time.
DrawLogo:
    ld hl, _SCRN0 + TITLE_LOGO_ROW * 32 + TITLE_LOGO_COL
    ld de, TitleLogoCells
    ld b, TITLE_LOGO_H
.row
    push bc
    ld c, TITLE_LOGO_W
.cell
    ld a, [de]
    inc de
    dec a                          ; 1-based, as DrawText's lines are
    add a, LOGO_TILE_BASE
    ld [hl+], a
    dec c
    jr nz, .cell
    ; The row's cells advanced the pointer past the end of it, so step the rest
    ; of the way to the next map line.
    ld bc, 32 - TITLE_LOGO_W
    add hl, bc
    pop bc
    dec b
    jr nz, .row
    ret

; RowColAddr: read a (row, col) pair from DE and return it in HL as the map
; cell in map 0's top-left, advancing DE past the pair. Clobbers A and BC.
RowColAddr:
    ld a, [de]                     ; row
    inc de
    ld l, a
    ld h, 0
    add hl, hl                     ; hl = row * 32: five doublings, and a row
    add hl, hl                     ; number is at most 17, so this cannot
    add hl, hl                     ; overflow 16 bits
    add hl, hl
    add hl, hl
    ld a, [de]                     ; col
    inc de
    ld c, a
    ld b, 0
    add hl, bc
    ld bc, _SCRN0
    add hl, bc
    ret

; ---------------------------------------------------------------------------
; MemCopy: copy BC bytes from DE to HL.
; ---------------------------------------------------------------------------
MemCopy:
    ld a, [de]
    inc de
    ld [hl+], a
    dec bc
    ld a, b
    or c
    jr nz, MemCopy
    ret

; ---------------------------------------------------------------------------
; ClearMap: fill all 32x32 cells of BG map 0 with tile 0.
; ---------------------------------------------------------------------------
ClearMap:
    ld hl, _SCRN0
    ld bc, SCRN_BYTES
    ld d, 0
.clr
    ld [hl], d
    inc hl
    dec bc
    ld a, b
    or c
    jr nz, .clr
    ret

; ---------------------------------------------------------------------------
; SetLevelDigits: the level's number as the two glyphs a notice's digit cells
; hold, in wLevelTens/wLevelUnits. The Z80 computes the same pair and patches
; its own text with them (`LevelDig1`/`LevelDig2`, Chuckie.asm:4437-4460).
;
; The tens cell is BLANK below level ten -- the source stores tile 0 there
; (`LD A,B / AND A / JR Z,.Skip`) rather than a zero -- and two cells is all the
; text has, so the number wraps: the Z80 subtracts 100 there, and 200 once more
; before that (`CP $C8` then `CP $64`). Both rules meet at level 100, which is
; 100 - 100 = 0 and so reads BLANK,'0' -- "LEVEL  0", not "LEVEL 00", because
; the blank is decided by the tens digit and not by the number being under ten.
;
; A and B only: the caller is holding the notice record pointer in DE.
; ---------------------------------------------------------------------------
SetLevelDigits:
    ld a, [wCurrentLevel]
    inc a                            ; the counter is 0-based; the number is not
    cp 200
    jr c, .under200
    sub 200
.under200
    cp 100
    jr c, .under100
    sub 100
.under100
    ld b, 0
.div
    cp 10
    jr c, .units
    sub 10
    inc b
    jr .div
.units
    add a, SCORE_DIGIT_FIRST
    ld [wLevelUnits], a
    ld a, b
    and a
    jr z, .blank
    add a, SCORE_DIGIT_FIRST
    ld [wLevelTens], a
    ret
.blank
    xor a                            ; the text's blank glyph
    ld [wLevelTens], a
    ret

; ---------------------------------------------------------------------------
; ShowNotice: the Z80's ScrollTextLine (Chuckie.asm:5051) -- the score screen's
; blank map with one line of text on it, held for C frames. DE points at a
; notice record from src/score.asm: a map row, a map column, a cell count, then
; that many glyph indices into the score run, two of which are the level's
; number on the announcement. The LCD is on when this is
; called, and left on with the notice up; the caller puts the next screen over
; it, which every caller does (a level, or the table).
;
; The words are the Z80's three: the level's number, "GAME OVER" when the last
; life goes, and "OUT OF TIME !" for a death after the clock ran out. The Z80
; scrolls the word across a *cleared* screen, which is why this blanks the map
; rather than drawing over the level: the source's screen is empty behind the
; text, and the camera is what would be scrolling it here, not a print.
;
; wOnNotice is what keeps it: the VBlank handler would otherwise follow the
; camera and redraw the status row over the top of this.
; ---------------------------------------------------------------------------
ShowNotice:
    push bc                          ; C is the hold, and RowColAddr wants BC
    push de                          ; ClearMap zeroes D to get its blank byte, so
    di                               ; the record pointer has to survive it
    call LcdOffForVram
    xor a
    ldh [rSCY], a                    ; an announcement is not a camera: the
    ldh [rSCX], a                    ; map is read from its top-left cell
    call ClearMap
    pop de
    call SetLevelDigits              ; what the record's digit cells will show
    call RowColAddr                  ; HL = the cell, DE at the cell count
    ld a, [de]
    inc de
    ld b, a
.row
    ld a, [de]
    inc de
    cp NOTICE_TENS                   ; the level's number is two cells: the
    jr z, .tens                      ; tens, blank below level ten, then the
    cp NOTICE_DIGIT                  ; units -- as the Z80's text has them
    jr nz, .store
    ld a, [wLevelUnits]
    jr .store
.tens
    ld a, [wLevelTens]
.store
    add a, SCORE_TILE_BASE           ; the store is shared, so the digit is
    ld [hl+], a                      ; turned into a tile here like the rest
    dec b
    jr nz, .row
    pop bc
    ld a, LCDC_BASE & ~(LCDCF_OBJON | LCDCF_WINON)
    ldh [rLCDC], a
    ld a, 1
    ld [wOnNotice], a
    ei
.hold
    halt                             ; the handler runs the tune, and nothing
    dec c                            ; else: wOnNotice is up
    jr nz, .hold
    xor a
    ld [wOnNotice], a
    ret

; ---------------------------------------------------------------------------
; LcdOffForVram: wait for the blanking interval and switch the LCD off, so the
; caller can write VRAM. Three routines want exactly this -- NextLevel.reload,
; EnterTitle and EnterScores -- and it is one place to get right.
;
; Interrupts must already be off. VBlank is serviced the instant rLY reaches 144
; and the handler does not return until rLY has moved past it, so with them on
; this wait only ever wins by luck, and never on the levels whose handler is
; long (the ones with lifts, which is how that bug announced itself).
;
; Skipped when the LCD is already off, because a switched-off LCD holds rLY at
; 0 and the wait would never end -- which is the state Start boots into. With
; the LCD off nothing in here may halt either, for the same reason.
; ---------------------------------------------------------------------------
LcdOffForVram:
    ldh a, [rLCDC]
    and LCDCF_ON
    jr z, .dark
.blank
    ldh a, [rLY]
    cp 144
    jr nz, .blank
.dark
    xor a
    ldh [rLCDC], a
    ret

; ---------------------------------------------------------------------------
; The high-score table. The Z80's HighScores / CheckPlayersHighScores /
; InHighScoreTable / name entry, less the parts with no GB analogue (the
; attribute pulses, the speech, the "PLAYER n, well done" text block).
;
; Reached from the death path's last life, which is where the Z80's goes too:
; LoseLife -> CheckPlayersHighScores -> FrontEnd. A player who did not qualify
; still sees the table, as they do on the Spectrum -- the source prints it there
; whoever is playing.
; ---------------------------------------------------------------------------

; SeedHighScores: the ten starting entries, from the Z80's own data block.
; Called once, from Start.
SeedHighScores:
    ld hl, wHighScores
    ld b, SCORE_COUNT
.entry
    push bc
    push hl
    ld de, DefaultEntry
    ld bc, SCORE_ENTRY_BYTES
    call MemCopy
    pop hl
    pop bc
    ld de, SCORE_ENTRY_BYTES
    add hl, de
    dec b
    jr nz, .entry
    ret

; ---------------------------------------------------------------------------
; HighEntryAddr: A = a 1-based rank -> HL = that entry. Clobbers A, DE and HL;
; B is left alone, because NameType is holding the glyph it is about to store
; there.
; ---------------------------------------------------------------------------
HighEntryAddr:
    dec a                        ; a 0-based slot
    ld e, a
    ld d, 0
    add a, a
    add a, a
    add a, a
    add a, a                     ; slot * 16 -- at most 9, so it cannot overflow
    sub e                        ; ...less slot: slot * 15
    ld l, a
    ld h, 0
    ld de, wHighScores
    add hl, de
    ret

; ---------------------------------------------------------------------------
; OfferScore: A = the rank the player's score takes, 1..SCORE_COUNT, or 0 if it
; beats nothing. The Z80's CheckHighScore (Chuckie.asm:4680): walk the table and
; stop at the first entry the score is STRICTLY greater than. CompareScore sets
; its flag only for `>`, so an equal score does not displace the entry already
; there.
;
; It reads wScoreSaved, not wScore, because the Z80 reads P1Score here: the
; score banked at the end of the last level the player FINISHED, which is the
; only thing LevelCompleted ever writes. So the points of the level a player
; died on do not count, on the last life as much as on any other -- the same
; rule LoadLevel already applies through a death that leaves lives over.
; ---------------------------------------------------------------------------
OfferScore:
    ld hl, wHighScores + SCORE_NAME_LEN
    ld b, 1
.entry
    push bc
    push hl
    call ScoreBeatsEntry
    pop hl
    pop bc
    and a
    jr nz, .found
    ld de, SCORE_ENTRY_BYTES
    add hl, de
    inc b
    ld a, b
    cp SCORE_COUNT + 1
    jr c, .entry
    xor a
    ret
.found
    ld a, b
    ret

; ---------------------------------------------------------------------------
; ScoreBeatsEntry: HL = a table entry's SCORE field -- past the name, which is
; glyph indices and would compare as nonsense; A = 1 if wScoreSaved is strictly
; greater, else 0.
;
; Digit by digit, most significant first, which is a numeric compare only
; because both fields are fixed width and zero padded. The Z80 does the same,
; but on ASCII digits it has to convert them first -- `ADD A,$30` over P1Score
; in CheckPlayersHighScores (Chuckie.asm:4640). Ours are one digit per byte in
; wScore's own layout, so nothing is ever converted.
; ---------------------------------------------------------------------------
ScoreBeatsEntry:
    ld de, wScoreSaved
    ld c, SCORE_SCORE_LEN
.digit
    ld a, [hl]
    ld b, a
    ld a, [de]
    cp b                         ; ours minus theirs
    jr c, .less                  ; ours is smaller, so no
    jr nz, .more                 ; not smaller and not equal, so greater
    inc hl
    inc de
    dec c
    jr nz, .digit
    xor a                        ; equal on every digit: no
    ret
.more
    ld a, 1
    ret
.less
    xor a
    ret

; ---------------------------------------------------------------------------
; InsertScore: A = a rank from OfferScore, 1..SCORE_COUNT. The Z80's
; InHighScoreTable (Chuckie.asm:4705): the entries from that rank down shift one
; slot, the last falling off the end of the table, and the vacated slot gets the
; player's score with a blank name for NameEntry to fill in.
;
; The block is copied BACKWARDS, from the table's end, so no byte is overwritten
; before it has been read.
; ---------------------------------------------------------------------------
InsertScore:
    push af                      ; the rank, for the fill at the end
    ld b, a
    ld a, SCORE_COUNT
    sub b
    jr z, .fill                  ; the last slot has nothing below it to move
    ; BC = (SCORE_COUNT - rank) * SCORE_ENTRY_BYTES, as *16 less *1 -- the same
    ; trick HighEntryAddr uses, and no multiply loop.
    ld c, a
    ld b, 0
    ld l, c
    ld h, b
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl                   ; 16 * records
    ld a, l
    sub c
    ld l, a
    ld a, h
    sbc a, b
    ld h, a                      ; 15 * records
    ld b, h
    ld c, l
    ; The last byte to move and where it goes: one record higher. Both ends are
    ; fixed -- the block always runs from the end of the second-to-last record to
    ; the end of the table, and only its LENGTH changes with the rank, because
    ; (rank-1) + (SCORE_COUNT-rank) is SCORE_COUNT-1 whatever the rank is.
    ld hl, wHighScores + (SCORE_COUNT - 1) * SCORE_ENTRY_BYTES - 1
    ld d, h
    ld e, l
    ld a, SCORE_ENTRY_BYTES
    add a, l
    ld l, a
    ld a, h
    adc a, 0
    ld h, a
.shift
    ld a, [de]
    ld [hl-], a
    dec de
    dec bc
    ld a, b
    or c
    jr nz, .shift
.fill
    pop af
    call HighEntryAddr           ; HL = the vacated record
    ld b, SCORE_NAME_LEN
    xor a
.blank
    ld [hl+], a                  ; index 0 is the space glyph
    dec b
    jr nz, .blank
    ld de, wScoreSaved
    ld b, SCORE_SCORE_LEN
.score
    ld a, [de]
    inc de
    ld [hl+], a
    dec b
    jr nz, .score
    ret

; ---------------------------------------------------------------------------
; ScoreRowAddr: A = a 1-based rank -> DE = the map cell its name field starts
; at, in map 0. Clobbers A, BC and HL.
; ---------------------------------------------------------------------------
ScoreRowAddr:
    dec a
    add a, SCORE_ENTRY_ROW0
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl                   ; * 32: a map row
    ld bc, _SCRN0 + SCORE_ENTRY_COL
    add hl, bc
    ld d, h
    ld e, l
    ret

; ---------------------------------------------------------------------------
; GridRowAddr: A = a grid row (0-based) -> A = the map row it is drawn on. The
; panel's rows are SCORE_PANEL_STEP apart and not consecutive, so that the
; two alphabet rows do not touch; this and DrawGrid have to agree. Clobbers B
; and C.
; ---------------------------------------------------------------------------
GridRowAddr:
    ld b, a
    ld c, SCORE_PANEL_STEP
    ld a, 0
.mul
    add a, b
    dec c
    jr nz, .mul
    add a, SCORE_GRID_ROW
    ret

; ---------------------------------------------------------------------------
; GridAddr: HL = the map cell the grid's cursor is on. Clobbers A, BC and HL.
; ---------------------------------------------------------------------------
GridAddr:
    ld a, [wGridRow]
    call GridRowAddr
    ld l, a
    ld h, 0
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    ld a, [wGridCol]
    add a, SCORE_GRID_COL
    ld c, a
    ld b, 0
    add hl, bc
    ld bc, _SCRN0
    add hl, bc
    ret

; ---------------------------------------------------------------------------
; GridCellIndex: A = the cursor's cell in the alphabet, 0..26, counting across
; the rows. Clobbers B and C.
; ---------------------------------------------------------------------------
GridCellIndex:
    ld a, [wGridRow]
    ld b, a
    ld c, SCORE_GRID_COLS
    ld a, 0
.mul
    add a, b
    dec c
    jr nz, .mul                  ; row * SCORE_GRID_COLS
    ld b, a
    ld a, [wGridCol]
    add a, b
    ret

; ---------------------------------------------------------------------------
; DrawGlyphs: B glyph indices from DE to the map at HL, shifted by the run's
; base. The screen's own strings are fixed width, so there is no terminator and
; a zero byte is the space glyph rather than an end marker -- which is what
; lets a blank name render as blanks.
; ---------------------------------------------------------------------------
DrawGlyphs:
    ld a, [de]
    inc de
    add a, SCORE_TILE_BASE
    ld [hl+], a
    dec b
    jr nz, DrawGlyphs
    ret

; ---------------------------------------------------------------------------
; DrawRunLines: a table of (row, col, cell count) records, each followed by that
; many glyph indices, ended by a row byte of $FF -- InstructionsLines and
; TitleHelpLine, both in src/score.asm. DE points at the first record. The LCD
; must be off.
;
; The table screen's own lines are one stanza of asm each instead, because the
; ten entries are drawn between them; these two screens are nothing but text, so
; they are a walk rather than a dozen ld hl/ld de pairs.
; ---------------------------------------------------------------------------
DrawRunLines:
    ld a, [de]
    cp $FF
    ret z
    call RowColAddr                ; the row and the col, DE left at the count
    ld a, [de]
    inc de
    ld b, a
    call DrawGlyphs
    jr DrawRunLines

; ---------------------------------------------------------------------------
; DrawEntryRow: the record at HL to the map at DE. The name is already glyph
; indices, so it is a straight copy; a digit is its own value plus the run's
; first digit tile. Leaves HL past the record.
; ---------------------------------------------------------------------------
DrawEntryRow:
    ld b, SCORE_NAME_LEN
.name
    ld a, [hl+]
    add a, SCORE_TILE_BASE
    ld [de], a
    inc de
    dec b
    jr nz, .name
    ld b, SCORE_SCORE_LEN
.score
    ld a, [hl+]
    add a, SCORE_TILE_BASE + SCORE_DIGIT_FIRST
    ld [de], a
    inc de
    dec b
    jr nz, .score
    ret

; ---------------------------------------------------------------------------
; DrawScoreTable: the whole screen into map 0. The LCD must be off.
; ---------------------------------------------------------------------------
DrawScoreTable:
    call ClearMap
    ld hl, _SCRN0 + SCORE_HEADING_ROW * 32 + SCORE_HEADING_COL
    ld de, ScoreHeading
    ld b, SCORE_HEADING_LEN
    call DrawGlyphs

    ; The eight entries, a map row each. The Z80 steps its rows by two -- H =
    ; 21, 19, ... 3 (Chuckie.asm:5517) -- but it has 24 rows and shows the table
    ; alone. This screen has 18 and shares them with the alphabet panel, so the
    ; entries stay consecutive and it is the COUNT that gives way; see
    ; SCORE_COUNT in tools/gbdata.py for the arithmetic.
    ld hl, wHighScores
    ld de, _SCRN0 + SCORE_ENTRY_ROW0 * 32 + SCORE_ENTRY_COL
    ld c, SCORE_COUNT
.entry
    push bc
    push de
    call DrawEntryRow            ; leaves HL on the next record
    pop de
    pop bc
    ld a, e
    add a, 32
    ld e, a
    ld a, d
    adc a, 0
    ld d, a
    dec c
    jr nz, .entry

    ; The panel and its legend are for a name being typed, and there is a name to
    ; type only when the score made the table. Drawn regardless, a game that did
    ; not qualify shows a grid with no cursor beneath a legend promising "PAD
    ; move" -- a control that does nothing, NameEntry being a no-op at rank 0.
    ; The Z80's table is the table and nothing else (Chuckie.asm:5517); this is
    ; the same screen.
    ld a, [wNameEntry]
    and a
    ret z
    call DrawGrid
    ld hl, _SCRN0 + SCORE_LEGEND1_ROW * 32 + SCORE_LEGEND1_COL
    ld de, ScoreLegend1
    ld b, SCORE_LEGEND1_LEN
    call DrawGlyphs
    ld hl, _SCRN0 + SCORE_LEGEND2_ROW * 32 + SCORE_LEGEND2_COL
    ld de, ScoreLegend2
    ld b, SCORE_LEGEND2_LEN
    call DrawGlyphs
    ret

; ---------------------------------------------------------------------------
; DrawGrid: the alphabet panel and, if the cursor is in its visible half, its
; cursor. Redrawn whole rather than cell by cell -- 28 cells is cheaper to write
; than to track which two changed, and it cannot drift out of step that way.
; ---------------------------------------------------------------------------
DrawGrid:
    ld hl, _SCRN0 + SCORE_GRID_ROW * 32 + SCORE_GRID_COL
    ld de, ScoreGrid
    ld c, SCORE_GRID_ROWS
.row
    ld b, SCORE_GRID_COLS
.cell
    ld a, [de]
    inc de
    add a, SCORE_TILE_BASE
    ld [hl+], a
    dec b
    jr nz, .cell
    ld a, l
    add a, 32 * SCORE_PANEL_STEP - SCORE_GRID_COLS
    ld l, a
    ld a, h
    adc a, 0
    ld h, a
    dec c
    jr nz, .row
    ; The cursor cell, drawn from the run's inverted copies of the same letters
    ; -- which is why the cursor is always a letter and never a blob.
    ld a, [wBlinkOn]
    and a
    ret z
    call GridCellIndex
    add a, SCORE_TILE_BASE + SCORE_INV_FIRST
    push af                      ; GridAddr clobbers C, and this is the tile
    call GridAddr
    pop af
    ld [hl], a
    ret

; ---------------------------------------------------------------------------
; DrawEditingRow: the record being typed, with the name field's cursor on it.
; The cursor is the run's inverted space tile -- a solid block -- so it costs no
; tiles of its own, and it blinks, as the Z80's $B7 blob does. Only legal in the
; blanking interval.
; ---------------------------------------------------------------------------
DrawEditingRow:
    ld a, [wNameEntry]
    call HighEntryAddr
    push hl                      ; the record, for DrawEntryRow
    ld a, [wNameEntry]
    call ScoreRowAddr            ; DE = the map cell
    pop hl
    call DrawEntryRow
    ld a, [wBlinkOn]
    and a
    ret z
    ld a, [wNameEntry]
    call ScoreRowAddr
    ld a, [wNamePos]
    ld l, a
    ld h, 0
    add hl, de
    ld a, SCORE_TILE_BASE + SCORE_INV_FIRST
    ld [hl], a
    ret

; ---------------------------------------------------------------------------
; WaitVBlank: return during the blanking interval, so VRAM is addressable.
;
; The test is a RANGE (rLY >= 144) rather than an exact value, for the reason
; LcdOffForVram gives. It also means the wait ends wherever in the window it
; arrives, so what follows has to be short -- the two redraws below are 47 cells
; between them, against the ~1140 cycles a VBlank lasts. Interrupts must be on:
; this is the wait that relies on the handler firing, unlike the one it shares a
; name with.
; ---------------------------------------------------------------------------
WaitVBlank:
    ldh a, [rLY]
    cp 144
    jr c, WaitVBlank
    ret

; ---------------------------------------------------------------------------
; NameEntry: the Z80's name typing (Chuckie.asm:4789), as an alphabet panel
; rather than its letter-by-letter scroll. Runs with the LCD ON -- the panel and
; the cursor ARE the feedback. A no-op for a score that did not make the table.
;
; The Z80 debounces on KSTATE/LASTK so that a held key types once; wPadNew does
; the same job here, which is why the menus read it and the game does not.
; ---------------------------------------------------------------------------
NameEntry:
    ld a, [wNameEntry]
    and a
    ret z
    xor a
    ld [wNamePos], a
    ld [wGridRow], a
    ; Cell 1, which is 'A': cell 0 is the space, and a cursor parked on it turns
    ; the first A press into a leading blank. The Z80's field starts blank too,
    ; but its cursor is an insertion point rather than a cell, so there is
    ; nothing there to sit on.
    inc a
    ld [wGridCol], a
    xor a
    ld [wNameDone], a
    ld [wScoreDirty], a
    ld a, SCORE_BLINK
    ld [wBlinkCtr], a            ; reloaded on each flip; seeded, or the first
    ld a, 1                      ; period would run through 256 counts of zero
    ld [wBlinkOn], a             ; the cursor starts visible
    ld [wScoreDirty], a          ; ...and the first pass has to draw
.loop
    halt                         ; one pass a frame; the handler draws as usual
    call ReadButtons
    call NameInput
    ld a, [wNameDone]
    and a
    jr nz, .done
    ; The blink. It marks the screen dirty like any other change, so a phase
    ; flip and a keystroke take the same path out of here.
    ld hl, wBlinkCtr
    dec [hl]
    jr nz, .draw
    ld [hl], SCORE_BLINK
    ld a, [wBlinkOn]
    xor 1
    ld [wBlinkOn], a
    ld a, 1
    ld [wScoreDirty], a
.draw
    call RedrawScore
    jr .loop
.done
    ; Left with no cursors: the typed row is what is remembered, and the panel
    ; is decoration from here.
    xor a
    ld [wBlinkOn], a
    inc a
    ld [wScoreDirty], a
    call RedrawScore
    ret

; ---------------------------------------------------------------------------
; RedrawScore: the editing row and the panel, if anything changed. Waits for the
; blanking interval itself, so it is legal with the LCD on.
; ---------------------------------------------------------------------------
RedrawScore:
    ld a, [wScoreDirty]
    and a
    ret z
    xor a
    ld [wScoreDirty], a
    call WaitVBlank
    call DrawEditingRow
    jp DrawGrid

; ---------------------------------------------------------------------------
; NameInput: act on the buttons that went down this frame. One step per press,
; which is what makes the panel drivable: a held direction does not run.
; ---------------------------------------------------------------------------
NameInput:
    ld a, [wPadNew]
    and PAD_START
    jr z, .not_start
    ld a, 1
    ld [wNameDone], a
    ret
.not_start
    ld a, [wPadNew]
    and PAD_A
    jr z, .not_a
    jp NameType
.not_a
    ld a, [wPadNew]
    and PAD_B
    jr z, .not_b
    jp NameRub
.not_b
    ld a, [wPadNew]
    and PAD_UP
    jr z, .not_up
    ld hl, wGridRow
    ld a, [hl]
    and a
    jr nz, .up
    ld a, SCORE_GRID_ROWS
.up
    dec a
    ld [hl], a
    jr MarkDirty
.not_up
    ld a, [wPadNew]
    and PAD_DOWN
    jr z, .not_down
    ld hl, wGridRow
    ld a, [hl]
    inc a
    cp SCORE_GRID_ROWS
    jr c, .down
    xor a
.down
    ld [hl], a
    jr MarkDirty
.not_down
    ld a, [wPadNew]
    and PAD_LEFT
    jr z, .not_left
    ld hl, wGridCol
    ld a, [hl]
    and a
    jr nz, .left
    ld a, SCORE_GRID_COLS
.left
    dec a
    ld [hl], a
    jr MarkDirty
.not_left
    ld a, [wPadNew]
    and PAD_RIGHT
    ret z
    ld hl, wGridCol
    ld a, [hl]
    inc a
    cp SCORE_GRID_COLS
    jr c, .right
    xor a
.right
    ld [hl], a
    ; falls through

; MarkDirty: the screen has something new to show.
MarkDirty:
    ld a, 1
    ld [wScoreDirty], a
    ret

; ---------------------------------------------------------------------------
; NameType: the panel's current letter into the name field. The Z80's rule is
; nine characters -- an L running $10..$18 against `CP $19` -- and the tenth is
; simply not stored, so a full name stops taking input rather than wrapping.
; ---------------------------------------------------------------------------
NameType:
    ld a, [wNamePos]
    cp SCORE_MAX_NAME
    ret nc
    call GridCellIndex
    ld hl, ScoreGrid
    ld e, a
    ld d, 0
    add hl, de
    ld a, [hl]
    ld b, a                      ; the glyph index -- HighEntryAddr keeps B
    ld a, [wNameEntry]
    call HighEntryAddr
    ld a, [wNamePos]
    ld e, a
    ld d, 0
    add hl, de
    ld [hl], b
    ld hl, wNamePos
    inc [hl]
    jp MarkDirty

; ---------------------------------------------------------------------------
; NameRub: the Z80's DELETE. Steps back one cell and blanks it, and does nothing
; at the start of the field, so a backspace there is not a jump to the end.
; ---------------------------------------------------------------------------
NameRub:
    ld a, [wNamePos]
    and a
    ret z
    dec a
    ld [wNamePos], a
    ld a, [wNameEntry]
    call HighEntryAddr
    ld a, [wNamePos]
    ld e, a
    ld d, 0
    add hl, de
    ld [hl], 0                   ; the space glyph
    jp MarkDirty

; ---------------------------------------------------------------------------
; EnterScores: the high-score table, from the death that ended the game. Mirrors
; EnterTitle -- blank, clear, draw, and leave the screen entirely BG -- plus the
; name entry, when the score made the table.
; ---------------------------------------------------------------------------
EnterScores:
    di
    ; The score is offered and inserted first, so what the draw below puts up is
    ; the table the player's entry is already in.
    call OfferScore
    ld [wNameEntry], a
    and a
    jr z, .draw
    call InsertScore
.draw
    call LcdOffForVram
    xor a
    ldh [rSCY], a
    ldh [rSCX], a
    call DrawScoreTable
    xor a
    ld [wPlayerDead], a
    ld [wOnTitle], a
    ld [wOnInstr], a             ; the front ends are exclusive
    ld [wBlinkOn], a             ; no cursor until the name entry asks for one
    inc a
    ld [wOnScores], a
    ; OBJ off and WIN off, as on the title: nothing here is a sprite, and the
    ; status band belongs to a game that is over.
    ld a, LCDC_BASE & ~(LCDCF_OBJON | LCDCF_WINON)
    ldh [rLCDC], a
    ei
    call NameEntry
    ret

; ---------------------------------------------------------------------------
; EnterInstructions: the instructions, from SELECT on the title. The Z80's `I`
; at the front end (TestKeys, Chuckie.asm:4113) -- SELECT because a DMG has no I
; key and SELECT is what the pad calls "this button does something else".
;
; The tune is deliberately left alone: this is a screen off the title, not a
; screen of its own, so the title's music runs on under it. Leaving it is
; EnterTitle, which starts the tune over -- one keypress, and a front end that
; has not gone anywhere.
; ---------------------------------------------------------------------------
EnterInstructions:
    di
    call LcdOffForVram               ; safe with the LCD on, which is how the
    xor a                            ; title reaches this
    ldh [rSCY], a
    ldh [rSCX], a
    call DrawInstructions
    xor a
    ld [wOnTitle], a
    ld [wOnScores], a
    inc a
    ld [wOnInstr], a
    ; OBJ off and WIN off, as on the title and the table: the words are the
    ; whole screen, and the status band belongs to a game.
    ld a, LCDC_BASE & ~(LCDCF_OBJON | LCDCF_WINON)
    ldh [rLCDC], a
    ei
    ret

; ---------------------------------------------------------------------------
; DrawInstructions: the screen into map 0. The LCD must be off.
; ---------------------------------------------------------------------------
DrawInstructions:
    call ClearMap
    ld de, InstructionsLines
    jp DrawRunLines

; ---------------------------------------------------------------------------
; DrawLevel: copy 21 rows of 32 from wLevelBuffer into the BG map bottom-up,
; since the Z80 source stores data row 0 as the level's last screen row. That
; row is map row PLAYFIELD_ROW0/32 -- one row lower than the level's own
; height alone would put it, to leave room for the status band above.
; ---------------------------------------------------------------------------
DrawLevel:
    ld hl, wLevelBuffer
    ld d, h
    ld e, l                          ; de = source row
    ld hl, _SCRN0 + PLAYFIELD_ROW0   ; dest = last level row of the map
    ld b, 21
.row
    push bc
    ld c, 32
.col
    ld a, [de]
    inc de
    ld [hl+], a
    dec c
    jr nz, .col
    ld bc, -64                       ; back up two rows from the end of this one
    add hl, bc
    pop bc
    dec b
    jr nz, .row
    ret

; ---------------------------------------------------------------------------
; GetLevelEntry: HL = a table, DE = its wCurrentLevel'th word.
;
; Two per-level tables are strided by a size that is not a power of two --
; levels are 672 bytes, hen records 21 -- so indexing them means a multiply.
; A table of addresses is that multiply done once, by the assembler, and it
; reads as what it is.
;
; The mask is the Z80's `AND $07`, which it applies at every per-level lookup,
; and it is the ONLY wrap left in the port: the counter itself runs on without
; a bound (`INC (HL)`, Chuckie.asm:4434) and the eight maps repeat from the
; ninth. Everything that is not a per-level lookup -- the
; duck's cage, the hens, their speed, the clock, the score -- reads the counter
; unmasked, because that is exactly what the source does with it.
; ---------------------------------------------------------------------------
GetLevelEntry:
    ld a, [wCurrentLevel]
    and LEVEL_COUNT - 1
    add a, a                 ; entries are words
    ld e, a
    ld d, 0
    add hl, de
    ld a, [hl+]
    ld d, [hl]
    ld e, a
    ret

LevelPtrs:
    FOR n, 8
        dw Level1 + n * LEVEL_WIDTH * LEVEL_HEIGHT
    ENDR

HenStartPtrs:
    FOR n, 8
        dw HenStarts + n * HEN_RECORD
    ENDR

; ---------------------------------------------------------------------------
; The lifts' own data. Only the table's x survives the port: the record's other
; field is a Spectrum screen address, which is a position in a memory layout
; the Game Boy does not share, and YPos already says where the platform is.
; ---------------------------------------------------------------------------
SECTION "LiftData", ROM0

LiftXTable:
    db LIFT_NONE, LIFT_NONE, 64, 144, 200, 120, 240, LIFT_NONE

LiftTiles:
    db $FF,$FF, $FF,$FF, $FF,$FF, $FF,$FF   ; four rows of platform ink
    db $00,$00, $00,$00, $00,$00, $00,$00
LiftTilesEnd:
