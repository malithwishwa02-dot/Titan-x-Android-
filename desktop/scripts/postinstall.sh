#!/bin/bash
# Titan Console — .deb post-install script
# Runs after dpkg installs the package

set -e

# Create data directories
mkdir -p /opt/titan/data/devices
mkdir -p /opt/titan/data/profiles
mkdir -p /opt/titan/data/config
mkdir -p /opt/titan/data/forge_gallery
mkdir -p /opt/titan/data/gapps

# Set permissions so non-root users can use the app
chmod -R 755 /opt/titan/data 2>/dev/null || true

# Update desktop database if available
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

echo ""
echo "════════════════════════════════════════════════════"
echo "  Titan Console V11.3.2 installed successfully!"
echo "════════════════════════════════════════════════════"
echo ""
echo "  Launch from your application menu or run:"
echo "    titan-console"
echo ""
echo "  The first launch will set up a Python virtual"
echo "  environment and install dependencies automatically."
echo ""
echo "  For Cuttlefish KVM support, ensure:"
echo "    - /dev/kvm exists (hardware virtualization enabled)"
echo "    - Kernel modules: vhost_vsock, vhost_net"
echo "    - Cuttlefish images in /opt/titan/cuttlefish/images/"
echo ""
