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

# --check NEVER fails the caller. It reports on stdout and exits 0 even when the
# upstream is unreachable, so a caller can treat "cannot tell" exactly like
# "nothing to do" without inspecting exit codes. An update check is a
# convenience; it must never be able to block the work it precedes.
#
# In --check mode stdout carries ONE machine-readable line and nothing else;
# human narration goes to stderr. Callers parse stdout, humans read stderr.
#   status=current           installed=X upstream=X
#   status=update-available  installed=X upstream=Y
#   status=unavailable       installed=X reason=<token>
#
# Performing an actual update still exits non-zero on failure — that is a real
# error the caller must see.
give_up() {                       # $1 = reason token, $2 = human message
  if $check_only; then
    printf 'status=unavailable installed=%s reason=%s\n' "$CURRENT" "$1"
    printf '%s\n' "$2" >&2
    exit 0
  fi
  printf '%s\n' "$2" >&2
  exit 1
}

command -v gh >/dev/null \
  || give_up gh-not-found "gh CLI not found"
gh auth status >/dev/null 2>&1 \
  || give_up gh-not-authenticated "gh not authenticated — run: gh auth login"

latest="$(gh api "repos/$UPSTREAM/releases/latest" --jq '.tag_name' 2>/dev/null | sed 's/^v//' || true)"
if [[ -z "$latest" ]]; then
  latest="$(gh api "repos/$UPSTREAM/contents/VERSION" --jq '.content' 2>/dev/null | base64 -d | tr -d '[:space:]' || true)"
fi
# Validate the SHAPE, not just non-emptiness. `gh api` prints its error body to
# stdout on failure, so a 404 yields a JSON blob here rather than an empty
# string — which would sail past a -n test and be reported as an available
# "version". Verified against a nonexistent repo.
if [[ ! "$latest" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  give_up upstream-unreachable \
    "could not read a valid version from the upstream — check access"
fi

target="${want:-$latest}"
if $check_only; then
  printf 'installed: %s\nupstream:  %s  (%s)\n' "$CURRENT" "$latest" "$UPSTREAM" >&2
  if [[ "$CURRENT" == "$target" ]]; then
    printf 'status=current installed=%s upstream=%s\n' "$CURRENT" "$latest"
    printf 'already up to date.\n' >&2
  else
    printf 'status=update-available installed=%s upstream=%s\n' "$CURRENT" "$target"
    printf 'update available: %s -> %s\n' "$CURRENT" "$target" >&2
  fi
  exit 0
fi

echo "installed: $CURRENT"
echo "upstream:  $latest  ($UPSTREAM)"
if [[ "$CURRENT" == "$target" ]]; then
  echo "already up to date."
  exit 0
fi

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
