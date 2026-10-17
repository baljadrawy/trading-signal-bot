#!/usr/bin/env bash
# Disposable preview: internal Docker network only (no published port, no internet), synthetic data, removed after.
# Usage: SHARED=<scratch dir> preview/run.sh   -> $SHARED/shots/*.png, $SHARED/checks/*.json
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd); SHARED=${SHARED:?}; NET=a59-preview-net
SVC_IMG=${SVC_IMG:-tsb-aiohttp-test-pytestenv:3.14.3}; PW_IMG=${PW_IMG:-mcr.microsoft.com/playwright/python:v1.56.0-noble}
mkdir -p "$SHARED"; docker network create --internal --label purpose=a59-disposable-test "$NET" >/dev/null
trap 'docker rm -f a59-preview >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true' EXIT
for spec in healthy:ok degraded:degraded stale:stale failure:error expiry:ok:25 closed:ok; do
  IFS=: read -r scen mode win <<< "$spec"
  rm -f "$SHARED/url.txt" "$SHARED/req"
  docker run -d --rm --name a59-preview --network "$NET" --network-alias a59-preview --label purpose=a59-disposable-test \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e A59_MODE="$mode" -e A59_WINDOW_S="${win:-}" \
    -v "$REPO:/src:ro" -v "$SHARED:/shared" --tmpfs /tmp --entrypoint python "$SVC_IMG" /src/dashboard/preview/run_preview.py >/dev/null
  timeout 2 tail -f /dev/null || true
  docker run --rm --network "$NET" --label purpose=a59-disposable-test --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$REPO:/src:ro" -v "$SHARED:/shared" -v "${PW_PKG:?}:/pw:ro" -e PYTHONPATH=/pw --tmpfs /tmp --ipc=host "$PW_IMG" python /src/dashboard/preview/capture.py "$scen"
  docker rm -f a59-preview >/dev/null
done
