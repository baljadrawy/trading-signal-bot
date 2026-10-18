#!/usr/bin/env bash
# Read-only runtime ↔ GitHub evidence collector. Run on the actual runtime host.
set -euo pipefail
umask 077
OUT="${1:-./runtime-parity-evidence}"
mkdir -p "$OUT"
date -u +%FT%TZ > "$OUT/collected-at-utc.txt"
hostname | sha256sum | awk '{print $1}' > "$OUT/host-id-sha256.txt"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD > "$OUT/runtime-git-head.txt"
  git status --porcelain=v1 --untracked-files=no > "$OUT/tracked-worktree-changes.txt"
  git remote get-url origin | sed -E 's#(https?://)[^/@]+@#\1[REDACTED]@#g' > "$OUT/git-origin-redacted.txt" || true
else
  printf 'UNVERIFIED: not running inside a git checkout\n' > "$OUT/runtime-git-head.txt"
fi
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker ps --no-trunc --format '{{.ID}} {{.Image}} {{.Names}}' > "$OUT/containers.txt"
  docker ps -q | while IFS= read -r id; do
    docker inspect --format '{{.Id}} {{.Image}} {{.Config.Image}}' "$id"
  done > "$OUT/container-image-identities.txt"
else
  printf 'UNVERIFIED: docker unavailable or insufficient permission\n' > "$OUT/container-image-identities.txt"
fi
printf '%s\n' 'Evidence only; no source secrets, environment values, or docker inspect JSON collected.' > "$OUT/README.txt"
printf '%s\n' 'Do not publish this directory; review names and metadata before sharing.'
