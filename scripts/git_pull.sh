#!/usr/bin/env bash
# Orbit2 <- GitHub pull helper.
#
# Refreshes this project folder to match whatever is currently on GitHub (the master copy).
# Use this at the start of a work session -- especially the first time on a new computer, or
# any time you're not sure this copy is current (e.g. changes were made on another computer
# since you last opened this one).
#
# This OVERWRITES local files with what's on GitHub. It does not attempt to merge. If there are
# local edits that haven't been pushed yet, push them first (scripts/git_push.sh) -- otherwise
# they're only at risk locally, never on GitHub itself, since GitHub only ever has what was
# actually pushed to it.
#
# Uses the same fresh-clone-then-copy approach as git_push.sh, for the same reason: a long-lived
# local .git directory can accumulate lock files this sandbox can't clean up, which silently
# breaks git commands. Cloning fresh every time sidesteps that.
#
# Usage: scripts/git_pull.sh

set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="$BASE_DIR/.github_token"
REPO="smojsak-code/orbit2"

if [ ! -f "$TOKEN_FILE" ]; then
  echo "No token found at $TOKEN_FILE -- can't reach GitHub. A GitHub PAT needs to be provided first." >&2
  exit 1
fi
TOKEN="$(cat "$TOKEN_FILE" | tr -d '[:space:]')"

WORKDIR="$(mktemp -d)"
git clone --quiet "https://x-access-token:${TOKEN}@github.com/${REPO}.git" "$WORKDIR"

# Never touch local-only secrets/build artifacts that don't live in GitHub.
rsync -a --exclude '.git' --exclude '.github_token' --exclude '.git-credentials' --exclude 'node_modules' \
  "$WORKDIR/" "$BASE_DIR/"

echo "Pulled latest from https://github.com/${REPO} into $BASE_DIR"
