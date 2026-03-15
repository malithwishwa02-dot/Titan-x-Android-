#!/usr/bin/env bash
# Titan Console — desktop launcher (Cuttlefish)
# Launches the Electron wrapper for Titan V11.3 Cuttlefish console

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ELECTRON="$SCRIPT_DIR/node_modules/.bin/electron"

if [[ ! -x "$ELECTRON" ]]; then
  echo "Electron not found at $ELECTRON" >&2
  exit 1
fi

export PYTHONPATH="${SCRIPT_DIR}/../server:${SCRIPT_DIR}/../core:/opt/titan/core${PYTHONPATH:+:$PYTHONPATH}"

# Cuttlefish KVM environment — override via env if needed
export CVD_BIN_DIR="${CVD_BIN_DIR:-/opt/titan/cuttlefish/cf/bin}"
export CVD_HOME_BASE="${CVD_HOME_BASE:-/opt/titan/cuttlefish}"
export CVD_IMAGES_DIR="${CVD_IMAGES_DIR:-/opt/titan/cuttlefish/images}"

exec "$ELECTRON" "$SCRIPT_DIR" "$@"
