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
  "$BASE_DIR/" "$WORKDIR/"

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
