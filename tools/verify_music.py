#!/usr/bin/env python3
"""Assert the tunes are the source's bytes and the driver walks them right.

Phase 6b. Fidelity is NOT asserted and cannot be: the Game Boy has no AY, so
this is a re-encode, and whether the two tunes sound like themselves is an ear
test in mGBA. What is asserted here is everything mechanical around them -- the
emitted streams against the Z80 source byte for byte, the period table against
the semitone formula, and the driver's own walk: one note at a time, its length,
its period register, and the terminator that stops it.

    python3 tools/verify_music.py [rom.gb]
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gbdata  # noqa: E402
import harness  # noqa: E402


ROM = sys.argv[1] if len(sys.argv) > 1 else "chuckie.gb"
SYM = os.path.splitext(ROM)[0] + ".sym"
ASM = "reference/paulie/Chuckie.asm"

LEVEL_WIDTH = 32
TILE_EGG = 3
HEN_MAX, HEN_NONE = 5, 0xFF
AUDTRIGGER = 0x80


def main_asm_def(name):
    """A constant out of src/main.asm or src/hardware.inc.

    NOTE_UNIT is the one number in 6b that is a judgement rather than a
    translation, and AUDVOL_MAX is the volume StartMusic re-arms, so both are
    read rather than repeated. hardware.inc writes them lowercase with binary
    literals; main.asm uses the uppercase form and decimal.
    """
    src = open("src/main.asm").read() + open("src/hardware.inc").read()
    m = re.search(r"^(?:DEF|def)\s+%s\s+(?:EQU|equ)\s+(\S+)" % name, src, re.M)
    if not m:
        raise SystemExit("FAIL: %s is not a constant in src/main.asm or "
                         "src/hardware.inc" % name)
    return int(m.group(1).replace("%", "0b"), 0)


def symbols(path):
    out = {}
    for line in open(path):
        m = re.match(r"[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


NOTE_UNIT = main_asm_def("NOTE_UNIT")
sym = symbols(SYM)
need = ["MusicPeriods", "TitleMusic", "LoseLifeMusic", "LoseLifeMusicEnd",
        "wMusicPtr", "wMusicTimer",
        "wMusicPeriod",
        "wSfxTimer", "wSfxFreq", "wLevelBuffer", "wPlayerX", "wPlayerY",
        "wPlayerInAir", "wInAirCounter", "wHens", "wEggsRemaining", "wPlayerDead"]
missing = [n for n in need if n not in sym]
if missing:
    raise SystemExit("FAIL: %s not in %s -- did the labels change?" % (missing, SYM))

failed = []
fail = failed.append

with open(ROM, "rb") as f:
    rom = f.read()

# --- 1. The streams are the source's bytes, and nothing else -----------------
# Read straight out of the linked ROM at the symbols, so what is checked is
# what shipped rather than what the generator printed.
streams = gbdata.music_streams(ASM)
for label, vals in streams:
    got = list(rom[sym[label]:sym[label] + len(vals)])
    print("%s: %d bytes, %d notes + terminator" % (label, len(vals), len(vals) // 2 - 1))
    if got != vals:
        first = next(i for i in range(len(vals)) if got[i] != vals[i])
        fail("%s in the ROM differs from the source at byte %d: $%02X, expected $%02X"
             % (label, first, got[first], vals[first]))
    if vals[-2] != 0:
        fail("%s does not end on a 0 duration byte, so the driver would run off "
             "the end of it" % label)

# --- 2. The period table is the semitone formula ------------------------------
# Recomputed here from the formula rather than imported: if the generator's
# arithmetic drifts, this is what says so.
table_bytes = sym["TitleMusic"] - sym["MusicPeriods"]
if table_bytes % 2:
    fail("the period table is %d bytes, not a whole number of words" % table_bytes)
table = [rom[sym["MusicPeriods"] + i * 2] | rom[sym["MusicPeriods"] + i * 2 + 1] << 8
         for i in range(table_bytes // 2)]
bad = [i for i, p in enumerate(table)
       if p != 2048 - round(131072 / (261.63 * 2 ** (i / 12)))]
print("period table: %d semitones from middle C (%d..%d), %s"
      % (len(table), table[0], table[-1], "PASS" if not bad else "FAIL at %s" % bad))
if bad:
    fail("the period table is not the semitone formula at %s" % bad)

pitches = [p for _, vals in streams for p in vals[1:-1:2]]
top = max(pitches)
if top >= len(table):
    fail("the tunes use pitch %d but the table stops at %d -- the driver indexes "
         "it as pitch*2 and would read past the end" % (top, len(table) - 1))
print("pitches used: %d..%d, inside the table" % (min(pitches), top))

# --- 3. The driver walks the title tune ---------------------------------------
# The only verifier here that asks for sound. Everywhere else the APU is dead
# weight; here it is the thing under test -- and with sound_emulated=False
# PyBoy does not model the APU registers at all, so a write to one is dropped
# and reads back 0. See the note above the period shadow for the half that
# cannot be read back even with it on.
pb = harness.boot(ROM, sound=True)

for s in range(HEN_MAX):
    pb.memory[sym["wHens"] + s * 4] = HEN_NONE


def reg(addr):
    return pb.memory[addr]


def tick(n=1):
    for _ in range(n):
        pb.tick(1, True)


# The APU is on and wired up. Read here rather than beside the table, because
# nothing about it is meaningful until the ROM has run.
if not reg(0xFF26) & 0x80:
    fail("the APU is not powered on (rNR52 is $%02X)" % reg(0xFF26))
if not reg(0xFF25) or not reg(0xFF24):
    fail("the outputs are not routed/at volume (rNR51 $%02X, rNR50 $%02X)"
         % (reg(0xFF25), reg(0xFF24)))

# A game opens silent: the title has its own tune, and LoadLevel -- which is
# what START reaches -- stops it. (That the title's tune is playing while the
# title is up is verify_title.py's, read off the same pointer.)
if reg(sym["wMusicPtr"]) or reg(sym["wMusicPtr"] + 1):
    fail("a game opens with something playing (wMusicPtr = $%04X), and LoadLevel "
         "should have stopped the title's tune"
         % (reg(sym["wMusicPtr"]) | reg(sym["wMusicPtr"] + 1) << 8))

# A note lasts `10 / duration` BEEP units, times NOTE_UNIT, and the frame it was
# fetched on is one of them -- so the gap between one note starting and the
# next is exactly that many frames. The driver's own arithmetic, done here the
# same way, so a note that runs long or short is a frame that does not match.
def note_frames(d):
    return (10 // d) * NOTE_UNIT


pairs = [(streams[0][1][i], streams[0][1][i + 1])
         for i in range(0, len(streams[0][1]) - 1, 2)]
notes = [p for p in pairs if p[0]]                 # the terminator is (0, 0)
ends_at = 1 + sum(note_frames(d) for d, _ in notes)

# The channel's volume at 0 is how StopMusic says "not playing", and a game
# opens through LoadLevel -- which stops the title's tune -- so a poke that
# short-circuits StartMusic would leave the channel silent and every note would
# play into a muted channel. StartMusic's own re-arm is done here by hand.
if reg(0xFF12):
    fail("a game opens with channel 1 at volume $%02X, and LoadLevel should "
         "have silenced the title's tune" % reg(0xFF12))
AUDVOL_MAX = main_asm_def("AUDVOL_MAX")


# Poke, settle, poke again. A poke made straight after a tick can straddle the
# frame boundary, and the driver can be part way through a note when it lands --
# its own store to the timer then overwrites the poke a frame later, and the
# note it was on plays again at its full length. So the first note starts a
# frame either side of where the poke alone would have put it. Which frame that
# is, is the emulator's business and not the driver's: the check below reads the
# origin off the run and asserts what the driver actually promises, the gap from
# one note to the next. The throwaway tick is verify_hud's idiom and stays, so
# the straddle is at least the same one every run.
def start_stream(addr):
    pb.memory[sym["wMusicPtr"]] = addr & 0xFF
    pb.memory[sym["wMusicPtr"] + 1] = addr >> 8
    pb.memory[sym["wMusicTimer"]] = 0
    pb.memory[0xFF12] = AUDVOL_MAX      # StartMusic's re-arm, which this skips


start_stream(sym["TitleMusic"])
tick(1)
start_stream(sym["TitleMusic"])

# The tune can only start late by the one note the straddle costs it, so the
# window is the tune plus the longest note it has -- bounded, because a driver
# that never reaches its terminator must still end the loop rather than hang.
LIMIT = ends_at + max(note_frames(d) for d, _ in notes) + 4

starts, seen, stopped = [], 0, None
prev = sym["TitleMusic"]
for f in range(1, LIMIT):
    tick(1)
    ptr = reg(sym["wMusicPtr"]) | reg(sym["wMusicPtr"] + 1) << 8
    if ptr == prev:
        continue
    prev = ptr
    if ptr == 0:
        stopped = f
        break
    # A fetch: the period the driver picked has to be this note's table entry.
    # Read from the shadow rather than the APU, because NR13's period byte and
    # NR14's period bits are write-only on the DMG -- there is no register to
    # read it back from, on hardware or here. The channel's own state below is
    # what ties the shadow to a channel that is really running.
    d, p = notes[seen]
    want = table[p]
    got = reg(sym["wMusicPeriod"]) | reg(sym["wMusicPeriod"] + 1) << 8
    starts.append(f)
    if got != want:
        fail("note %d (pitch %d) played period $%04X, expected $%04X"
             % (seen, p, got, want))
    if reg(0xFF12) >> 4 == 0:
        fail("note %d (pitch %d) is playing with the channel volume at 0"
             % (seen, p))
    seen += 1

print("title tune: %d notes, starts on frame %s, stopped on frame %s"
      % (seen, starts[0:1], stopped))
if seen != len(notes):
    fail("the driver played %d notes of the title tune, expected %d"
         % (seen, len(notes)))
# Every gap is absolute: the first note's frame is wherever the poke landed, and
# the whole tune is that frame plus its own length. A run that never started at
# all has no origin to measure from, so it is 0 and the compare below fails.
origin = starts[0] if starts else 0
want_starts = [origin]
for d, _ in notes[:-1]:
    want_starts.append(want_starts[-1] + note_frames(d))
if starts != want_starts:
    off = next((i for i, (a, b) in enumerate(zip(starts, want_starts)) if a != b),
               min(len(starts), len(want_starts)))
    fail("the notes do not start where their lengths say: note %d starts on frame "
         "%s, expected %s" % (off, starts[off:off + 1], want_starts[off:off + 1]))
if stopped != origin + ends_at - 1:
    fail("the tune stopped on frame %s, expected %d"
         % (stopped, origin + ends_at - 1))
if reg(0xFF12):
    fail("the tune ended with channel 1 still at volume $%02X" % reg(0xFF12))
if reg(sym["wMusicPtr"]) or reg(sym["wMusicPtr"] + 1):
    fail("the stream pointer is not clear after the terminator")

# --- 4. A pickup plays the effect, and it ends ------------------------------
def stand_on(r, c):
    pb.memory[sym["wPlayerX"]] = c * 8 - 8
    pb.memory[sym["wPlayerY"]] = r * 8 + 8
    pb.memory[sym["wPlayerInAir"]] = 0
    pb.memory[sym["wInAirCounter"]] = 4


R, C = 12, 6
pb.memory[sym["wLevelBuffer"] + R * LEVEL_WIDTH + C] = TILE_EGG
stand_on(R, C)
tick(1)
sfx = reg(sym["wSfxTimer"])
print("pickup: sfx timer %d, rNR42 $%02X, rNR43 $%02X"
      % (sfx, reg(0xFF21), reg(0xFF22)))
if not sfx:
    fail("an egg was collected and no effect was started")
if reg(0xFF21) & 0xF0 == 0:
    fail("the effect's channel has volume 0, so the blip is silent")
if reg(0xFF22) != reg(sym["wSfxFreq"]) + sfx:
    fail("the effect's frequency is $%02X, expected the slide $%02X"
         % (reg(0xFF22), reg(sym["wSfxFreq"]) + sfx))

tick(reg(sym["wSfxTimer"]) + 1)
if reg(sym["wSfxTimer"]):
    fail("the effect is still running after its length")
if reg(0xFF21):
    fail("the effect ended with channel 4 at volume $%02X" % reg(0xFF21))

# --- 5. A death plays the jingle --------------------------------------------
# Last, because it kills Harry and the level reloads 90 frames later.
# Where he is now, not where he spawned: the egg above moved him. The Z80's
# four tests are satisfied by a hen three pixels left of him and four above.
pb.memory[sym["wHens"]] = reg(sym["wPlayerX"]) - 3
pb.memory[sym["wHens"] + 1] = reg(sym["wPlayerY"]) - 4
pb.memory[sym["wHens"] + 2] = 1
pb.memory[sym["wHens"] + 3] = 0
tick(1)
music = reg(sym["wMusicPtr"]) | reg(sym["wMusicPtr"] + 1) << 8
# Inside the stream, not equal to its first byte: the tick that ran the death
# also fetched the first note, which walks the pointer on by two.
print("death: playerDead %d, music pointer $%04X (LoseLifeMusic is $%04X..$%04X)"
      % (reg(sym["wPlayerDead"]), music, sym["LoseLifeMusic"],
         sym["LoseLifeMusicEnd"] - 1))
if not reg(sym["wPlayerDead"]):
    fail("the hen did not kill him, so this is not testing the death path")
elif not sym["LoseLifeMusic"] <= music < sym["LoseLifeMusicEnd"]:
    fail("a death did not start the jingle")

pb.stop(save=False)
for f in failed:
    print("FAIL:", f)
print("RESULT:", "FAIL" if failed else "PASS")
sys.exit(1 if failed else 0)
