#!/usr/bin/env bash
# Idempotent: start hermes-machine if it is not already running.
# Used by the launchd plist — exits 0 once the machine is confirmed running.
set -euo pipefail

MACHINE_NAME="hermes-machine"
MAX_WAIT=120
INTERVAL=5

state=$(podman machine inspect "$MACHINE_NAME" --format '{{.State}}' 2>/dev/null || echo "unknown")

if [[ "$state" == "running" ]]; then
  echo "$MACHINE_NAME is already running."
  exit 0
fi

echo "Starting $MACHINE_NAME..."
podman machine start "$MACHINE_NAME"

# Poll until running or timeout
elapsed=0
while true; do
  state=$(podman machine inspect "$MACHINE_NAME" --format '{{.State}}' 2>/dev/null || echo "unknown")
  if [[ "$state" == "running" ]]; then
    echo "$MACHINE_NAME is running."
    exit 0
  fi
  if (( elapsed >= MAX_WAIT )); then
    echo "ERROR: $MACHINE_NAME did not reach 'running' state within ${MAX_WAIT}s." >&2
    exit 1
  fi
  sleep "$INTERVAL"
  (( elapsed += INTERVAL ))
done
