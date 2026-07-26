#!/usr/bin/env bash
# Update this skill in place from its upstream repository.
#
#   ./scripts/update-skill.sh            # update to the latest release
#   ./scripts/update-skill.sh --check    # report whether an update exists
#   ./scripts/update-skill.sh --version 1.2.0
#
# Requires: gh, authenticated with read access to the upstream repo. Your
# .monday-sync/ state is never touched.

set -euo pipefail
UPSTREAM="${MONDAY_SYNC_UPSTREAM:-Nightfire-Ops/monday-github-issues-sync}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT="$(cat "$HERE/VERSION" 2>/dev/null || echo 0.0.0)"

want=""; check_only=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)   check_only=true; shift ;;
    --version) want="${2:?--version needs a value}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null || { echo "gh CLI not found" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated — run: gh auth login" >&2; exit 1; }

latest="$(gh api "repos/$UPSTREAM/releases/latest" --jq '.tag_name' 2>/dev/null | sed 's/^v//' || true)"
if [[ -z "$latest" ]]; then
  latest="$(gh api "repos/$UPSTREAM/contents/VERSION" --jq '.content' 2>/dev/null | base64 -d | tr -d '[:space:]' || true)"
fi
[[ -n "$latest" ]] || { echo "could not read a version from $UPSTREAM — check access" >&2; exit 1; }

target="${want:-$latest}"
echo "installed: $CURRENT"
echo "upstream:  $latest  ($UPSTREAM)"

if [[ "$CURRENT" == "$target" ]]; then
  echo "already up to date."
  exit 0
fi
$check_only && { echo "update available: $CURRENT -> $target"; exit 0; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo "fetching $target …"
gh repo clone "$UPSTREAM" "$tmp/src" -- --depth 1 --quiet \
  ${want:+--branch "v$target"} 2>/dev/null \
  || gh repo clone "$UPSTREAM" "$tmp/src" -- --depth 1 --quiet

# Replace skill surface only. .monday-sync/ is the user's data and is preserved.
for path in SKILL.md README.md VERSION references scripts packaging; do
  [[ -e "$tmp/src/$path" ]] || continue
  rm -rf "${HERE:?}/$path"
  cp -r "$tmp/src/$path" "$HERE/$path"
done
chmod +x "$HERE/scripts/"*.sh "$HERE/scripts/"*.py "$HERE/packaging/"*.sh 2>/dev/null || true

echo "updated $CURRENT -> $(cat "$HERE/VERSION")"
echo "your .monday-sync/ state was not modified."
