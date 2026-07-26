#!/usr/bin/env bash
# Cut a release: bump VERSION, rebuild dist/, produce a versioned zip, tag,
# and (with --publish) push the tag and create the GitHub release.
#
#   ./packaging/release.sh 1.2.0
#   ./packaging/release.sh 1.2.0 --publish
#
# Refuses to release if the portability lint fails.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="monday-github-issues-sync"
UPSTREAM="${MONDAY_SYNC_UPSTREAM:-Nightfire-Ops/$NAME}"

VER="${1:?usage: release.sh <version> [--publish]}"
[[ "$VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be X.Y.Z" >&2; exit 2; }
PUBLISH=false; [[ "${2:-}" == "--publish" ]] && PUBLISH=true

cd "$ROOT"
echo "── releasing $NAME $VER ──"

echo "$VER" > VERSION
# Keep the SKILL.md frontmatter version in lockstep — it is what users see.
sed -i -E "0,/^version: .*/s//version: $VER/" SKILL.md
grep -q "^version: $VER$" SKILL.md || { echo "failed to stamp SKILL.md" >&2; exit 1; }

./packaging/build-share.sh >/dev/null
cp -r "dist/$NAME" "dist/$NAME-$VER"
(cd dist && zip -qr "$NAME-$VER.zip" "$NAME-$VER" && rm -rf "$NAME-$VER")
rm -f "dist/$NAME.zip"                       # unversioned artifact is ambiguous
(cd dist && zip -qr "$NAME.zip" "$NAME")     # rebuild as "latest"

echo
echo "artifacts:"
ls -1sh dist/*.zip | sed 's/^/  /'

if $PUBLISH; then
  command -v gh >/dev/null || { echo "gh not found" >&2; exit 1; }
  git add -A
  git commit -m "release: $VER" || echo "  (nothing to commit)"
  git tag -f "v$VER"
  git push origin HEAD --tags
  gh release create "v$VER" "dist/$NAME-$VER.zip" \
    --repo "$UPSTREAM" --title "v$VER" --generate-notes \
    || gh release upload "v$VER" "dist/$NAME-$VER.zip" --repo "$UPSTREAM" --clobber
  echo "published v$VER to $UPSTREAM"
else
  echo
  echo "not published. To publish:  ./packaging/release.sh $VER --publish"
fi
