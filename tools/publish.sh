#!/bin/sh
# Export the publishable tree: everything git tracks, minus the game data.
#
#   tools/publish.sh [destination]        (default: ~/chuckie-egg-gb)
#
# First run: the destination is a brand new repository with a single commit. If
# it already exists as one, the run syncs it instead -- same export rule, plus
# the removal of anything it tracks that the export no longer has. It commits
# and stops there; pushing stays a human decision.
#
# What ships is the port's own code. The ten files the Makefile lists in DATA are
# generated from a disassembly of the original game by `make data`, so they are
# not ours to publish -- which is also why a builder clones the reference rather
# than receiving it. See README.md.
#
# The export is a repository of its own. This repo's history carries the
# generated data in every commit back to Phase 1 (`434aecc`), so it cannot be
# pushed as-is; the alternative would be rewriting 46 commits.
set -e

DEST=${1:-$HOME/chuckie-egg-gb}
cd "$(git rev-parse --show-toplevel)"

UPDATE=
if [ -e "$DEST" ]; then
	[ -d "$DEST/.git" ] || {
		echo "publish: $DEST exists and is not a repository -- move it aside or name another path" >&2
		exit 1
	}
	UPDATE=1
fi

# The authoritative list of what is generated: the Makefile's DATA.
DATA=$(make -pn 2>/dev/null | sed -n 's/^DATA := //p')
if [ -z "$DATA" ]; then
	echo "publish: could not read DATA out of the Makefile" >&2
	exit 1
fi

LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT
# What the working tree would commit: tracked files plus new ones, less anything
# gitignored. So reference/, build/, local.mk and the ROM stay out by rule, and a
# file deleted but not yet staged drops out rather than breaking the copy.
git ls-files --cached --others --exclude-standard >"$LIST"

mkdir -p "$DEST"
# Plain cp rather than rsync: macOS ships rsync 2.6.9, which has neither --from0
# nor --ignore-missing-args.
while read -r f; do
	[ -f "$f" ] || continue
	# The published .gitignore is this repo's plus the DATA block below, so an
	# update must not copy ours over it -- that is the one file the two trees
	# hold differently on purpose.
	if [ -n "$UPDATE" ] && [ "$f" = ".gitignore" ]; then continue; fi
	mkdir -p "$DEST/$(dirname "$f")"
	cp -p "$f" "$DEST/$f"
done <"$LIST"

for f in $DATA; do
	rm -f "$DEST/$f"
done

# Keep a builder's own `make data` output out of their next commit. Append once:
# a sync runs this repeatedly, and a second copy of the block is just noise in
# the diff.
FIRST=
for f in $DATA; do FIRST=$f; break; done
if ! grep -qxF "$FIRST" "$DEST/.gitignore" 2>/dev/null; then
	{
		echo
		echo "# generated from the reference disassembly by \`make data\` -- the game's"
		echo "# data, not ours to publish, and not tracked here"
		for f in $DATA; do echo "$f"; done
	} >>"$DEST/.gitignore"
fi

# Anything the published repo tracks that the export does not have is gone: a
# renamed file, a deleted one.
if [ -n "$UPDATE" ]; then
	git -C "$DEST" ls-files | while read -r f; do
		[ "$f" = ".gitignore" ] && continue
		grep -qxF "$f" "$LIST" || rm -f "$DEST/$f"
	done
fi

# The trap this catches: a new generated file that never made it into DATA would
# sail into the export. main.asm is the only .asm in src/ that is ours.
STRAY=$(find "$DEST/src" -name '*.asm' ! -name 'main.asm')
if [ -n "$STRAY" ]; then
	echo "publish: these look generated but shipped anyway:" >&2
	echo "$STRAY" >&2
	exit 1
fi

cd "$DEST"
if [ -z "$UPDATE" ]; then
	git init -q -b main
fi
git add -A
if git diff --cached --quiet; then
	echo "published to $DEST -- already up to date at $(git rev-parse --short HEAD)"
else
	if [ -n "$UPDATE" ]; then
		# The bootstrap message below is about what this repository is, which is
		# only true of its first commit. A sync says what it moved instead.
		git commit -q -F - <<MSG
Sync the published tree with the working repo

$(git diff --cached --name-status)
MSG
	else
		git commit -q -F - <<'MSG'
Chuckie Egg (Game Boy): a DMG port of the ZX Spectrum original

The port's own code, and no game data: the ten src/*.asm files holding tiles,
sprites, level maps, fonts, music and text are generated from a disassembly of
the original by `make data`, so they are not published here. Neither is a ROM.
See README.md for the three commands that build one from a fresh clone.

Co-Authored-By: Claude Code <noreply@anthropic.com>
MSG
	fi
	echo "published to $DEST -- $(git ls-files | wc -l | tr -d ' ') files, $(git rev-parse --short HEAD)"
	echo "check what landed before pushing:"
	echo "  git -C $DEST show --stat HEAD"
	echo "  git -C $DEST ls-files src   # main.asm and hardware.inc, nothing else"
fi
echo "verify it builds from nothing before pushing:"
echo "  cp -R $DEST /tmp/pubcheck && cd /tmp/pubcheck"
echo "  git clone https://github.com/Paulie68000/ZXSpectrumChuckieEgg reference/paulie"
echo "  make data && make && make PY=/path/to/python verify"
