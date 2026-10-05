# Chuckie Egg (Game Boy) -- RGBDS build.
#   make          build chuckie.gb
#   make data     regenerate src/tiles.asm + src/levels.asm from the Z80 source
#   make shot     headless screenshot (FRAMES=200 SCRIPT=...)
#   make clean
# The ROM is a work in progress; see PLAN.md for the phase list.

# The recursive `$(MAKE)` calls below pass no goal, so they build whatever the
# default goal is: it has to stay `all` even though other targets sit above it.
.DEFAULT_GOAL := all

ROM  := chuckie.gb
SRC  := src/main.asm
# Generated from reference/paulie/Chuckie.asm by `make data`. main.asm INCLUDEs
# these, so they must not also be assembled as objects of their own.
DATA := src/tiles.asm src/levels.asm src/sprites.asm \
        src/hens.asm src/henstarts.asm src/font.asm src/music.asm src/title.asm \
        src/score.asm src/duck.asm
HDRS := src/hardware.inc

FRAMES ?= 200
SCRIPT ?=
# Extra rgbasm flags, e.g. make ASMFLAGS=-DCAMERA_Y=0 to see the level's top
# of the playfield. Remove $(ROM) first: the flags are not in any timestamp, so
# a ROM built with them is "up to date" the next time you ask for it without.
ASMFLAGS ?=
# Python with PyBoy in it. `python3` so a fresh checkout works with nothing but
# `pip install pyboy`; point it at a venv in an untracked local.mk (which this
# includes) or on the command line with `make PY=... verify`.
-include local.mk
PY ?= python3

# Boot straight into a level, to look at one without playing up to it:
#   make level N=5
# A ROM of its own rather than $(ROM) on purpose. A flag baked into $(ROM)
# survives a later plain `make` -- make sees no newer source and relinks
# nothing -- so `make ASMFLAGS=-DLEVEL_NUM=5` leaves the default ROM booting
# into level 5 for good. Naming the ROM per level makes the flags part of what
# is asked for, so re-running is a no-op and never a stale build.
level:
	@$(MAKE) -s -B ROM=build/l$(N).gb ASMFLAGS=-DLEVEL_NUM=$(N)
	@echo "build/l$(N).gb boots into level $(N); $(ROM) is untouched"

all: $(ROM)

$(ROM): $(SRC) $(DATA) $(HDRS)
	@mkdir -p build
	rgbasm $(ASMFLAGS) -I src -o build/main.o $(SRC)
	rgblink -o $@ -n $(ROM:.gb=.sym) -m $(ROM:.gb=.map) build/main.o
	rgbfix -v -p 0xFF -t "CHUCKIE" -m 0x00 -r 0x00 $@

data:
	@test -f reference/paulie/Chuckie.asm || { \
	  echo "make data needs the reference disassembly, which is not in this repo:"; \
	  echo "  git clone https://github.com/Paulie68000/ZXSpectrumChuckieEgg reference/paulie"; \
	  exit 1; }
	python3 tools/gbdata.py --write src/

# Assert the ROM against the reference disassembly. Needs PyBoy.
# The levels are each a separate ROM (LEVEL_NUM is assemble-time), so recurse
# per level rather than threading a rebuild through the Python script.
#
# Those recursions pass -B. A per-level ROM is named for its flags, but a build
# with them is still "up to date" for a later one -- the flags are in no
# timestamp -- which is how `make verify` verified a stale l9.gb once already.
# -B costs a re-assemble of a 32K ROM; it buys a check that reads the tree it
# was run on.
LEVELS := 1 2 3 4 5 6 7 8
verify: verify-levels verify-level9 verify-camera verify-player verify-hens verify-lifts verify-eggs \
        verify-hud verify-lives verify-music verify-title verify-scores verify-duck \
        verify-notice verify-sprites verify-init verify-laps

verify-levels:
	@for n in $(LEVELS); do \
	  $(MAKE) -s -B ROM=build/l$$n.gb ASMFLAGS=-DLEVEL_NUM=$$n >/dev/null && \
	  $(PY) tools/verify.py build/l$$n.gb $$n || exit 1; \
	done
	@echo "levels: all $(words $(LEVELS)) PASS"

# The ninth level: the map repeats from there (the Z80's `AND $07`) and the hen
# house is empty. Only the boot flag reaches it -- the counter has no bound but
# nothing at boot can set it past the flag -- so this is the check on the mask
# and the hen gate.
verify-level9:
	@$(MAKE) -s -B ROM=build/l9.gb ASMFLAGS=-DLEVEL_NUM=9 >/dev/null && \
	  $(PY) tools/verify.py build/l9.gb 9 || exit 1

verify-camera: $(ROM)
	$(PY) tools/verify_camera.py $(ROM)
verify-player: $(ROM)
	$(PY) tools/verify_player.py $(ROM)
verify-hens: $(ROM)
	$(PY) tools/verify_hens.py $(ROM)

# Level 3 is the first with lifts; level 1 is a control, so the level with no
# platforms has to survive the code that handles them.
verify-lifts:
	@$(MAKE) -s -B ROM=build/l3.gb ASMFLAGS=-DLEVEL_NUM=3 >/dev/null && \
	  $(PY) tools/verify_lifts.py build/l3.gb || exit 1
	@$(MAKE) -s -B ROM=build/l1.gb ASMFLAGS=-DLEVEL_NUM=1 >/dev/null && \
	  $(PY) tools/verify_lifts.py build/l1.gb || exit 1

# Level 1 is worth 10 an egg, level 5 (index 4) 20 -- the multiplier steps at
# every fourth level, so the pair brackets the step -- and level 37 (index 36)
# is where the Z80's own `CP $09` clamp lands it at 100.
verify-eggs:
	@$(MAKE) -s -B ROM=build/l1.gb ASMFLAGS=-DLEVEL_NUM=1 >/dev/null && \
	  $(PY) tools/verify_eggs.py build/l1.gb || exit 1
	@$(MAKE) -s -B ROM=build/l5.gb ASMFLAGS=-DLEVEL_NUM=5 >/dev/null && \
	  $(PY) tools/verify_eggs.py build/l5.gb || exit 1
	@$(MAKE) -s -B ROM=build/l37.gb ASMFLAGS=-DLEVEL_NUM=37 >/dev/null && \
	  $(PY) tools/verify_eggs.py build/l37.gb || exit 1

# Level 1 (no lifts) and level 3 (the first with them): the status row is a
# window plus a raster split, and neither cares about the level -- but the corn
# the timer's divider poke lives on does, and level 3 has some.
verify-hud:
	@$(MAKE) -s -B ROM=build/l1.gb ASMFLAGS=-DLEVEL_NUM=1 >/dev/null && \
	  $(PY) tools/verify_hud.py build/l1.gb || exit 1
	@$(MAKE) -s -B ROM=build/l3.gb ASMFLAGS=-DLEVEL_NUM=3 >/dev/null && \
	  $(PY) tools/verify_hud.py build/l3.gb || exit 1

# The OAM image and wOnNotice: the memory the ROM read before writing, against a
# machine that powered up dirty instead of an emulator's zeros -- at boot, and
# again at every level load, which is where a level inherits the slots the one
# before it used. The boot ROM is level 1, which is the level the check's
# never-written entry range is read off; see the script.
verify-init: $(ROM)
	$(PY) tools/verify_init.py $(ROM)

# Lives, game over, and the time-up rule. Level-independent, so the boot ROM.
verify-lives: $(ROM)
	$(PY) tools/verify_lives.py $(ROM)

# The tunes and the driver: the streams byte for byte against the source, the
# period table against the semitone formula, and the pointer/register walking
# one note at a time on the ROM.
verify-music: $(ROM)
	$(PY) tools/verify_music.py $(ROM)

# The title screen, the mode it puts the hardware in, its tune, and the
# START that leaves it -- including the way back in after a game over.
verify-title: $(ROM)
	$(PY) tools/verify_title.py $(ROM)

# The high-score table: the sort, the insert, the name entry, and the route
# through it from a game over to the next game.
verify-scores: $(ROM)
	$(PY) tools/verify_scores.py $(ROM)

# The mother duck: caged through 8, loose and lethal from 9. Level 1 is where
# its pixels are read off the screen against the cage, level 3 the first with
# lifts -- which is the level that says the duck's OAM entries do not collide
# with a platform's -- and the 8/9 pair is the plant's own boundary: caged on 8
# (one level later than the port first had it) and chasing on 9.
verify-duck:
	@$(MAKE) -s -B ROM=build/l1.gb ASMFLAGS=-DLEVEL_NUM=1 >/dev/null && \
	  $(PY) tools/verify_duck.py build/l1.gb || exit 1
	@$(MAKE) -s -B ROM=build/l3.gb ASMFLAGS=-DLEVEL_NUM=3 >/dev/null && \
	  $(PY) tools/verify_duck.py build/l3.gb || exit 1
	@$(MAKE) -s -B ROM=build/l8.gb ASMFLAGS=-DLEVEL_NUM=8 >/dev/null && \
	  $(PY) tools/verify_duck.py build/l8.gb || exit 1
	@$(MAKE) -s -B ROM=build/l9.gb ASMFLAGS=-DLEVEL_NUM=9 >/dev/null && \
	  $(PY) tools/verify_duck.py build/l9.gb || exit 1

# The three announcements: the word, the blank screen behind it, the digit on
# the level one, and the death that says nothing.
verify-notice: $(ROM)
	$(PY) tools/verify_notice.py $(ROM)

# The 10-sprites-a-line limit: level 5 is the four-hen fit with the duck over it,
# level 8 the only one whose duck is lethal, and level 25 the five-hen level where
# the overflow reaches the birds. The check pins the OAM slot order -- Harry, the
# hens, the lifts, the duck -- as load-bearing, not a comment.
verify-sprites:
	@$(MAKE) -s -B ROM=build/l5.gb ASMFLAGS=-DLEVEL_NUM=5 >/dev/null && \
	  $(PY) tools/verify_sprites.py build/l5.gb || exit 1
	@$(MAKE) -s -B ROM=build/l8.gb ASMFLAGS=-DLEVEL_NUM=8 >/dev/null && \
	  $(PY) tools/verify_sprites.py build/l8.gb || exit 1
	@$(MAKE) -s -B ROM=build/l25.gb ASMFLAGS=-DLEVEL_NUM=25 >/dev/null && \
	  $(PY) tools/verify_sprites.py build/l25.gb || exit 1

# The five laps. Every rule that changes with the level number is a threshold on
# the counter, which is why the rules live per-level and this drives the counter
# itself: one ROM, the thresholds on it, and level 41 pinned equal to level 33.
verify-laps: $(ROM)
	$(PY) tools/verify_laps.py $(ROM)

# Every WRAM byte the ROM reads before writing: one boot per variable, so it is
# minutes rather than seconds and stays out of `verify`. `make sweep` is the
# check to reach for when something works in PyBoy and not on hardware; see the
# script and PLAN.md, "The bytes nothing writes".
sweep: $(ROM)
	$(PY) tools/sweep_wram.py $(ROM)

# Headless screenshot. SCRIPT is one char per frame:
#   . none   R/L/U/D d-pad   A B buttons   S T start/select
# ASMFLAGS changes the ROM but not any timestamp, so make would happily reuse a
# stale build; drop the ROM and rebuild so the flags actually land.
shot: FORCE
	@mkdir -p build
	rm -f $(ROM)
	$(MAKE) -s $(ROM)
	$(PY) tools/shot.py $(ROM) $(OBJDIR)/shot.png $(FRAMES) $(SCRIPT)

FORCE:

OBJDIR := build

clean:
	rm -rf build $(ROM) $(ROM:.gb=.sym) $(ROM:.gb=.map)

.PHONY: all data verify verify-levels verify-level9 verify-camera verify-player verify-hens verify-lifts verify-eggs verify-hud verify-lives verify-music verify-title verify-scores verify-duck verify-notice verify-sprites verify-init verify-laps sweep shot clean FORCE
