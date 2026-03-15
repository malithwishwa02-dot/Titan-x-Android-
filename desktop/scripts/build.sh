#!/bin/bash
# Titan Console — Build Script
# Builds .deb and .AppImage packages using electron-builder
#
# Usage:
#   cd desktop && bash scripts/build.sh          # Build both
#   cd desktop && bash scripts/build.sh deb      # Build .deb only
#   cd desktop && bash scripts/build.sh appimage  # Build AppImage only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$DESKTOP_DIR"

echo "═══════════════════════════════════════════════════"
echo "  Titan Console — Electron Build"
echo "  Version: $(node -p 'require("./package.json").version')"
echo "═══════════════════════════════════════════════════"

# Check node_modules
if [ ! -d "node_modules" ]; then
    echo "[*] Installing npm dependencies..."
    npm install
fi

# Check electron-builder is available
if ! npx electron-builder --version &>/dev/null; then
    echo "ERROR: electron-builder not found. Run: npm install"
    exit 1
fi

TARGET="${1:-all}"

case "$TARGET" in
    deb)
        echo "[*] Building .deb package..."
        npx electron-builder --linux deb
        ;;
    appimage)
        echo "[*] Building AppImage..."
        npx electron-builder --linux AppImage
        ;;
    all|*)
        echo "[*] Building .deb + AppImage..."
        npx electron-builder --linux deb AppImage
        ;;
esac

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Build complete! Artifacts in dist/"
echo "═══════════════════════════════════════════════════"
ls -lh dist/*.deb dist/*.AppImage 2>/dev/null || echo "  (check dist/ for output)"
echo ""
