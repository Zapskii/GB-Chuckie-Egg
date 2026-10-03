#!/usr/bin/env python3
"""Assert the five laps: every rule that changes with the level number.

The Z80's level counter has no bound (Chuckie.asm:4434, `INC (HL)`), and every
rule that changes across a run is a threshold on it -- not a lap counter of its
own. Above $20 nothing new happens at all, and only the two multipliers (the
egg's score, the clock) keep stepping, so level 41 is level 33 again:

    the duck's cage    caged below 8             (:3462, `CP $08`)
    the hens           gone 9..16, back at 17    (:633-641, `CP $08`/`CP $10`)
    how many           5 from 25                 (:5968-5978, `CP $18`)
    their speed        3 -> 2 from 33            (:2135-2145, `CP $20`)
    starting time      9 - min(n >> 4, 5)        (:5874-5886, floor 4 from 81)
    the bonus          min(n + 1, 9)             (:5864-5872)
    egg's score        10 * (min(n >> 2, 9) + 1) (:2246-2256, 100 from level 37)

The counter is poked and a level's completion drives the reload, because
ResetHens and ResetTimer are what read it -- the boot flag is just the starting
value. Each row is one reload, and each expectation is transcribed from the
source above rather than from the port, so a formula that drifted fails here.

The map the counter points at is masked (`AND $07`, the only wrap left), which
is why the counters are chosen in pairs that share a map: 16 and 24 are both
map 0, so the hen count's jump from the table's own 2 to 5 is the gate and not
the level data. The duck's own boundary is verify_duck.py's l8/l9 pair, and the
egg's multiplier verify_eggs.py's level 37 -- this is the rest of the table.

    python3 tools/verify_laps.py chuckie.gb
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"
HENSTARTS = "src/henstarts.asm"

HEN_MAX, HEN_NONE = 5, 0xFF
HEN_SPEED = 3                       # main.asm's DEF, the fourth lap's own

# The gates, as the source's own operands on the 0-based counter.
HENS_OFF_FROM, HENS_BACK_FROM = 8, 16
ALL_FIVE_FROM, SPEED_UP_FROM = 24, 32

SPEED_WINDOW = 150                  # a whole number of beats at either speed
SPEED_COUNTERS = (31, 32)           # the pair the rate is measured on


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


sym = symbols(SYM)
need = ["wCurrentLevel", "wHens", "wHenTick", "wBonus", "wTime", "wLives",
        "wLevelDone", "wOnNotice", "wTimerRunning", "wPlayerDead"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

# The level's own hen count, out of the generated table: the gate is what this
# check is about, so the data it gates has to come from the data.
counts = [int(n) for n in re.findall(r"^\s+db (\d+)\s+; level \d",
                                     open(HENSTARTS).read(), re.M)]
if len(counts) != 8:
    raise SystemExit("FAIL: %s gives %d levels' hen counts, expected 8"
                     % (HENSTARTS, len(counts)))


def hen_speed(counter):
    """main.asm's HenSpeed, transcribed: the ticks between hen steps."""
    return HEN_SPEED if counter < SPEED_UP_FROM else HEN_SPEED - 1


def expected_hens(counter):
    """ResetHens' spawn: the table's own count, unless a gate replaces it."""
    if HENS_OFF_FROM <= counter < HENS_BACK_FROM:
        return 0
    if counter >= ALL_FIVE_FROM:
        return HEN_MAX
    return counts[counter & 7]


failed = []
fail = failed.append

pb = harness.boot(ROM)


def reg(name):
    return pb.memory[sym[name]]


def setreg(name, v):
    pb.memory[sym[name]] = v


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


def value3(name):
    """The three cells' number. ResetTimer writes the counter as [hundreds,
    tens, units], so a count of 9 reads 900 -- the cells, not a scaled value."""
    d = pb.memory[sym[name]:sym[name] + 3]
    return d[0] * 100 + d[1] * 10 + d[2]


def wait_for(name, want, limit=300):
    """Tick until a flag reads `want`. Frame counting, not a fixed sleep: the
    main loop works in the visible part of a frame, so a poke lands anywhere."""
    for _ in range(limit):
        tick(1)
        if bool(reg(name)) == want:
            return True
    return False


def reload_at(counter):
    """Land the ROM on `counter` with a level reload.

    NextLevel's own path -- the one that calls ResetHens and ResetTimer -- is
    the level-completion one, so the counter is poked one below and the level
    driven to its end. The announcement that goes up first is waited out;
    wLevelDone clearing is LoadLevel's last act, so the frame it clears on still
    holds the values ResetHens and ResetTimer left behind.
    """
    setreg("wLives", 9)
    setreg("wTimerRunning", 0)          # the bonus drain would delay the word
    setreg("wCurrentLevel", counter - 1)
    setreg("wLevelDone", 1)
    if not wait_for("wOnNotice", True):
        fail("counter %d: no announcement came up" % counter)
    elif not wait_for("wOnNotice", False):
        fail("counter %d: the announcement never came down" % counter)
    elif not wait_for("wLevelDone", False):
        fail("counter %d: the level never reloaded" % counter)
    if reg("wCurrentLevel") != counter:
        fail("counter %d: the reload landed on %d" % (counter, reg("wCurrentLevel")))


# --- 1. The state each threshold produces, read out of the ROM ---------------
# (counter, speed, bonus, time). Bonus and time are written in level numbers --
# the counter is 0-based and the source does its `INC A` before every `CP`, so
# level n is counter n-1 -- and hen_speed/expected_hens take the counter itself.
STATE = [
    (0, HEN_SPEED, 1, 9),             # level 1: the bottom of every formula
    (7, HEN_SPEED, 8, 9),             # level 8: the last with birds
    (8, HEN_SPEED, 9, 9),             # level 9: birds off, bonus clamps here
    (15, HEN_SPEED, 9, 9),            # level 16: the last without birds
    (16, HEN_SPEED, 9, 8),            # level 17: birds back, the clock's 1st step
    (23, HEN_SPEED, 9, 8),            # level 24: the last with the table's count
    (24, HEN_SPEED, 9, 8),            # level 25: all five
    (31, HEN_SPEED, 9, 7),            # level 32: the last at the old speed
    (32, HEN_SPEED - 1, 9, 7),        # level 33: the birds speed up
    (40, HEN_SPEED - 1, 9, 7),        # level 41: ...and it is level 33 again
    (79, HEN_SPEED - 1, 9, 5),        # level 80: the clock's last step down
    (80, HEN_SPEED - 1, 9, 4),        # level 81: the floor
    (99, HEN_SPEED - 1, 9, 4),        # level 100: still the floor
]

print("%5s %4s %6s %5s %5s" % ("level", "hens", "speed", "bonus", "time"))
seen = {}
for counter, _speed, _bonus, _time in STATE:
    n = counter + 1                             # the counter is 0-based
    if counter:                                 # level 1 is what the ROM boots on
        reload_at(counter)
    hens = sum(1 for s in range(HEN_MAX)
               if pb.memory[sym["wHens"] + s * 4] != HEN_NONE)
    bonus, time = value3("wBonus"), value3("wTime")
    # The countdown only ever counts down, so its largest value over a few
    # frames IS the reload HenSpeed left -- however the frames fall on the beat,
    # and whether or not any hen is out to step.
    speed = 0
    for _ in range(6):
        tick(1)
        speed = max(speed, reg("wHenTick"))
    seen[counter] = (hens, speed, bonus, time)
    print("%5d %4d %6d %5d %5d" % (n, hens, speed, bonus, time))
    for name, got, want in (("hens", hens, expected_hens(counter)),
                            ("speed", speed, hen_speed(counter)),
                            ("bonus", bonus, min(n, 9) * 100),
                            ("time", time, (9 - min(counter >> 4, 5)) * 100)):
        if got != want:
            fail("level %d: %s is %d, expected %d" % (n, name, got, want))

# --- 2. Nothing is gated past $20 -------------------------------------------
# The pair either side of the gate that has to be the last one, and then the
# whole tuple: 41 is 33's state, not a sixth lap.
if seen.get(40) != seen.get(32):
    fail("level 41's state %s is not level 33's %s -- something is gated above "
         "$20, where the Z80 has no comparison left" % (seen.get(40), seen.get(32)))
else:
    print("level 41 == level 33, state %s" % (seen[32],))

# --- 3. The speed is a rate, not just a reload value ------------------------
# Same reload value, same level, measured: the beats of wHenTick over a window
# that is a whole number of them at either speed. 150 frames is 50 beats at 3
# and 75 at 2 -- the 50% the Z80's own `DEC C` buys, counted rather than read.
for counter in SPEED_COUNTERS:
    reload_at(counter)
    setreg("wHenTick", 1)                       # so the first beat lands on frame 1
    prev, beats = 1, 0
    for _ in range(SPEED_WINDOW):
        tick(1)
        cur = reg("wHenTick")
        if cur > prev:                          # 1 -> the reload value
            beats += 1
        prev = cur
    want = SPEED_WINDOW // hen_speed(counter)
    print("level %d: %d hen beats in %d frames, expected %d"
          % (counter + 1, beats, SPEED_WINDOW, want))
    if beats != want:
        fail("level %d: %d hen beats in %d frames, expected %d -- the birds are "
             "not stepping 1/%d per frame" % (counter + 1, beats, SPEED_WINDOW,
                                              want, hen_speed(counter)))
    if reg("wPlayerDead"):
        fail("level %d: Harry died during the window, so the beats counted "
             "through a reload" % (counter + 1))

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
