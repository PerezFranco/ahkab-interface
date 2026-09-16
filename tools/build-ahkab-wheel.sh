#!/bin/bash
# Rebuild vendor/ahkab-*.whl from the local ahkab clone, and record which
# commit it came from in vendor/AHKAB_SOURCE.txt.
#
# Copyright 2026 Roberto Perez-Franco
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Usage (Git Bash): bash tools/build-ahkab-wheel.sh [branch]   (default: lazy-imports)
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CLONE="$HERE/../ahkab"
PY="$HERE/../.venv/Scripts/python.exe"
BRANCH="${1:-lazy-imports}"
cd "$CLONE"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ahkab clone has uncommitted changes to tracked files; refusing to build" >&2; exit 1
fi
git checkout -q "$BRANCH"
rm -f "$HERE"/vendor/ahkab-*.whl
"$PY" -m pip wheel . --no-deps -w "$HERE/vendor" -q
{
  echo "ahkab wheel built from https://github.com/PerezFranco/ahkab"
  echo "branch: $BRANCH"
  echo "commit: $(git rev-parse HEAD)"
  echo "built:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$HERE/vendor/AHKAB_SOURCE.txt"
cat "$HERE/vendor/AHKAB_SOURCE.txt"
