#!/usr/bin/env bash
# Verify the skill contains no account-, org-, or board-specific values.
# Run before sharing a modified copy. Exits non-zero on any finding.
#
#   ./packaging/verify-portable.sh [dir]     (default: repo root)

set -uo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
FAIL=0

# Only the skill's own text is checked. Excluded: this script (it contains the
# patterns by necessity), sync state (intentionally account-specific and never
# shipped), build output, and VCS internals.
#
# Exclusions are anchored to $ROOT, NOT written as '*/dist/*'. An unanchored
# glob matches every file whenever $ROOT itself sits under a directory of that
# name — scanning dist/<skill>/ would exclude its entire contents and silently
# pass. Anchoring is what makes the built package verifiable.
mapfile -t FILES < <(find "$ROOT" \
  -type f \( -name '*.md' -o -name '*.py' -o -name '*.json' \) \
  -not -path "$ROOT/.git/*" \
  -not -path "$ROOT/.monday-sync/*" \
  -not -path "$ROOT/packaging/*" \
  -not -path "$ROOT/dist/*" | sort)

# A zero-length file list must abort. `grep -r PATTERN` with no path arguments
# recurses the *current working directory* instead of erroring, so an empty list
# would quietly scan the wrong tree and report findings from outside $ROOT.
if (( ${#FILES[@]} == 0 )); then
  printf '✗ no scannable files found under %s\n' "$ROOT" >&2
  printf '  Expected SKILL.md, README.md, and references/*.md.\n' >&2
  exit 2
fi

# Canonical documentation placeholders. Examples need to be valid JSON, so they
# use these fixed fake values rather than <angle brackets>. Anything matching a
# risky pattern but not one of these is a real leak.
#   board id      1234567890
#   item ids      987654321, 987654322
#   column ids    <prefix>_mkabc1NN
#   workspace id  1122334455
#   monday user   12345678
PLACEHOLDER='12345678\b|1234567890|98765432[0-9]|1122334455|[a-z]+_mkabc[0-9]{3}'

check() {
  local label="$1" pattern="$2" hint="$3" allow="${4:-}"
  local reject="$PLACEHOLDER" hits
  [[ -n "$allow" ]] && reject="$PLACEHOLDER|$allow"
  hits=$(grep -rniE "$pattern" "${FILES[@]}" 2>/dev/null | grep -vE "$reject") || true
  if [[ -n "$hits" ]]; then
    printf '\n✗ %s\n' "$label"
    printf '  %s\n' "$hint"
    printf '%s\n' "$hits" | sed 's|^'"$ROOT"'/|    |'
    FAIL=1
  else
    printf '✓ %s\n' "$label"
  fi
}

printf 'Scanning %d files under %s\n\n' "${#FILES[@]}" "$ROOT"

check "no email addresses" \
  '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' \
  'Contact details are account-specific. Remove them.'

# mcp.monday.com is monday's public MCP endpoint — a product URL every install
# needs, not an account subdomain. Account boards live at <account>.monday.com.
check "no monday account subdomains" \
  'https?://[a-z0-9-]+\.monday\.com' \
  'Board URLs embed the account name. Use <account>.monday.com as a placeholder.' \
  'https://(mcp|www)\.monday\.com'

check "no long numeric ids (board / item / user)" \
  '\b[0-9]{8,}\b' \
  'monday board, item, and user ids are account-specific. Use <boardId> etc.'

check "no generated monday column ids" \
  '\b(color|numeric|dropdown|link|text|date|status)_[a-z0-9]{6,}\b' \
  'Column ids come from create_column at runtime. Describe the prefix, not a value.'

# The skill's OWN upstream is allowed — install and update need a real URL.
# What must stay generic is the *sync target*: the repo whose issues get mirrored.
# Override the upstream for a fork with MONDAY_SYNC_UPSTREAM at runtime.
#
# NOTE: grep -E is POSIX ERE — no negative lookahead. Allowed slugs are passed
# as an explicit allow list instead, which is why this check has a 4th argument.
UPSTREAM_SLUG="${MONDAY_SYNC_UPSTREAM:-Nightfire-Ops/monday-github-issues-sync}"
check "no concrete GitHub owner/repo slugs (other than this skill's upstream)" \
  'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9._-]+' \
  'Use OWNER/REPO or owner/repo. Real slugs bind the sync to one project.' \
  "github\.com/(OWNER/REPO|owner/repo|o/r|${UPSTREAM_SLUG})"

# The upstream slug may appear only in install/update/release plumbing — never
# in the sync logic itself, where it would pin what gets mirrored.
leaks=$(grep -rlE "${UPSTREAM_SLUG}" "${FILES[@]}" 2>/dev/null \
        | grep -vE '/(README|CLAUDE|INSTALL)\.md$' || true)
if [[ -n "$leaks" ]]; then
  printf '\n✗ upstream slug outside install/update docs\n'
  printf '  %s\n' 'It belongs in README/CLAUDE/INSTALL and the scripts only.'
  printf '%s\n' "$leaks" | sed 's|^'"$ROOT"'/|    |'
  FAIL=1
else
  printf '✓ upstream slug confined to install/update docs\n'
fi

# Attribution must never be hardcoded, and must never branch on bot-ness.
# Matches labelling *constructs* only — identifiers, badges, and group names.
# Prose that documents the [bot]-stripping rule is legitimate and must pass, so
# this deliberately does not match the bare string "[bot] suffix".
check "no bot labelling in output" \
  '(\bis_?bot\b|\bisBot\b|bot (badge|label|tag|marker)|\(bot\)|["'"'"']Automated["'"'"'] *(group|section))' \
  'Attribution is the GitHub login with [bot] stripped. No bot marking anywhere.'

if [[ -d "$ROOT/.monday-sync" ]]; then
  printf '\n! .monday-sync/ present — exclude it from any shared copy\n'
  printf '  It contains a real board id, repo slug, and item mapping.\n'
fi

printf '\n'
if (( FAIL )); then
  printf 'PORTABILITY: FAIL — resolve the findings above before sharing.\n'
  exit 1
fi
printf 'PORTABILITY: PASS — no account-specific values found.\n'
