#!/usr/bin/env bash
# Orbit2 -> GitHub push helper.
#
# Reads the GitHub token from .github_token (a gitignored file in this project's root — just the
# token string, nothing else). Does a fresh throwaway clone of the remote, copies the current
# working tree into it, commits, and pushes from there. This deliberately avoids depending on a
# persistent local .git directory: over a long working session those can accumulate lock/tmp-object
# files that some sandboxes won't let you clean up, which silently breaks every commit after that.
# A fresh clone each time sidesteps the problem entirely.
#
# Usage: scripts/git_push.sh "commit message"

set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="$BASE_DIR/.github_token"
REPO="smojsak-code/orbit2"
MSG="${1:-Orbit2 data update}"

if [ ! -f "$TOKEN_FILE" ]; then
  echo "No token found at $TOKEN_FILE -- nothing to push. A GitHub PAT needs to be provided first." >&2
  exit 1
fi
TOKEN="$(cat "$TOKEN_FILE" | tr -d '[:space:]')"

WORKDIR="$(mktemp -d)"

git clone --quiet "https://x-access-token:${TOKEN}@github.com/${REPO}.git" "$WORKDIR"

rsync -a --exclude 'node_modules' --exclude '.git' --exclude '.github_token' --exclude '.git-credentials' \
  --exclude 'reports/_qa_tmp' --exclude 'reports/*.tmp' --exclude 'reports/slide-*.jpg' \
  --exclude 'data/embedded_snapshot.json' \
  --exclude '.~lock.*' --exclude '.fuse_hidden*' \
  "$BASE_DIR/" "$WORKDIR/"

# rsync --exclude only stops NEW copies of these paths — if they were committed by an earlier
# push, they need to be actively removed from the clone too, since the clone starts from
# whatever's already on GitHub.
# LibreOffice lock files (.~lock.*#) and fuse_hidden files are transient app/filesystem
# artifacts that should never be version controlled — remove wherever they appear, not just
# in reports/, since soffice drops them next to whatever file it's converting.
find "$WORKDIR" -name '.~lock.*' -o -name '.fuse_hidden*' | xargs -r rm -f
rm -rf "$WORKDIR/reports/_qa_tmp" "$WORKDIR"/reports/*.tmp "$WORKDIR"/reports/slide-*.jpg \
  "$WORKDIR/data/embedded_snapshot.json" 2>/dev/null || true

# One-time cleanup: "catworkx DE (TEST DATA)" was a throwaway test vendor used earlier in the
# project and was never a real weights.json entry — its report files got committed by an
# earlier push before the vendor was removed from weights.json. Strip any leftovers so the
# public site doesn't keep serving reports for a vendor that no longer exists.
rm -f "$WORKDIR"/reports/*"catworkx DE (TEST DATA)"* 2>/dev/null || true

cd "$WORKDIR"
git config user.email "smojsak@gmail.com"
git config user.name "Steve Mojsak"
git add -A
if git diff --cached --quiet; then
  echo "Nothing to commit -- GitHub already up to date."
  exit 0
fi
git commit --quiet -m "$MSG"
git push --quiet origin HEAD:main
echo "Pushed to https://github.com/${REPO}"
