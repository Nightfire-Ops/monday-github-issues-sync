#!/usr/bin/env bash
# Build a shareable copy of the skill into dist/monday-github-issues-sync/.
# Runs the portability lint first and refuses to build if it fails.
#
#   ./packaging/build-share.sh [--zip]

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="monday-github-issues-sync"
OUT="$ROOT/dist/$NAME"

printf '── portability lint ──\n'
"$ROOT/packaging/verify-portable.sh" "$ROOT" | tail -8
printf '\n── building %s ──\n' "dist/$NAME"

rm -rf "$ROOT/dist"
mkdir -p "$OUT/references" "$OUT/packaging" "$OUT/scripts" "$OUT/tests"

# Skill surface only. .monday-sync/ is deliberately excluded — it holds a real
# board id, repo slug, and item mapping, and belongs to the syncing user.
cp "$ROOT/SKILL.md" "$ROOT/README.md" "$ROOT/CLAUDE.md" "$ROOT/handoff.md" "$ROOT/VERSION" "$OUT/"
cp "$ROOT/references/"*.md                               "$OUT/references/"
cp "$ROOT/scripts/"*.py "$ROOT/scripts/"*.sh              "$OUT/scripts/"
cp "$ROOT/tests/"*.py                                     "$OUT/tests/"
cp "$ROOT/INSTALL.md"                                    "$OUT/"
cp "$ROOT/packaging/verify-portable.sh"                   "$OUT/packaging/"
cp "$ROOT/packaging/build-share.sh"                       "$OUT/packaging/"
chmod +x "$OUT/packaging/"*.sh "$OUT/scripts/"*.py "$OUT/scripts/"*.sh

# The shipped copy must pass its own lint, from inside the package.
printf '\n── verifying the built package ──\n'
"$OUT/packaging/verify-portable.sh" "$OUT" | tail -3

if [[ -e "$OUT/.monday-sync" ]]; then
  printf '\n✗ .monday-sync/ leaked into the package — aborting\n' >&2
  exit 1
fi

printf '\n── contents ──\n'
(cd "$ROOT/dist" && find . -type f | sort | sed 's|^\./|  |')

if [[ "${1:-}" == "--zip" ]]; then
  (cd "$ROOT/dist" && zip -qr "$NAME.zip" "$NAME")
  printf '\n  archive: dist/%s.zip (%s)\n' "$NAME" \
    "$(du -h "$ROOT/dist/$NAME.zip" | cut -f1)"
fi

printf '\nReady to share: dist/%s/\n' "$NAME"
printf 'Recipient installs with: cp -r %s ~/.claude/skills/\n' "$NAME"
