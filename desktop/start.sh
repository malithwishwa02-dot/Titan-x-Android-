#!/usr/bin/env bash
# Titan Console — desktop launcher
# Launches the Electron wrapper for Titan V11.3 console

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ELECTRON="$SCRIPT_DIR/node_modules/.bin/electron"

if [[ ! -x "$ELECTRON" ]]; then
  echo "Electron not found at $ELECTRON" >&2
  exit 1
fi

export PYTHONPATH="${SCRIPT_DIR}/../server:${SCRIPT_DIR}/../core:/opt/titan/core${PYTHONPATH:+:$PYTHONPATH}"
exec "$ELECTRON" "$SCRIPT_DIR" "$@"
