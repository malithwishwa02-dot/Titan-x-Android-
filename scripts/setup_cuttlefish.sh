#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Titan V11.3 — Cuttlefish Host Setup Script
# Installs Cuttlefish dependencies, kernel modules, and downloads images.
# Run once on a bare-metal or KVM-capable VPS.
# ═══════════════════════════════════════════════════════════════════════

set -e

echo "═══════════════════════════════════════════════════"
echo "  Titan V11.3 — Cuttlefish Host Setup"
echo "═══════════════════════════════════════════════════"

# ─── Check KVM availability ──────────────────────────────────────────
if [ ! -e /dev/kvm ]; then
    echo "ERROR: /dev/kvm not found. KVM is required for Cuttlefish."
    echo "Ensure your host supports hardware virtualization (VT-x/AMD-V)."
    exit 1
fi
echo "[✓] KVM available"

# ─── Install required packages ───────────────────────────────────────
echo "[*] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    qemu-kvm bridge-utils libvirt-daemon-system \
    adb fastboot unzip curl wget git python3 python3-pip \
    libelf-dev linux-headers-$(uname -r) \
    v4l2loopback-dkms v4l2loopback-utils \
    2>/dev/null

# ─── Load kernel modules ─────────────────────────────────────────────
echo "[*] Loading kernel modules..."

MODULES="vhost_vsock vhost_net binder_linux v4l2loopback"
for mod in $MODULES; do
    if ! lsmod | grep -q "^${mod}"; then
        modprobe $mod 2>/dev/null || echo "  WARN: Could not load $mod (may need kernel rebuild)"
    fi
done

# Persist modules across reboots
MODULES_CONF="/etc/modules-load.d/titan-cuttlefish.conf"
cat > "$MODULES_CONF" << 'EOF'
# Titan V11.3 — Cuttlefish kernel modules
vhost_vsock
vhost_net
binder_linux
v4l2loopback
EOF
echo "[✓] Kernel modules configured: $MODULES_CONF"

# ─── Configure v4l2loopback ──────────────────────────────────────────
V4L2_CONF="/etc/modprobe.d/v4l2loopback.conf"
cat > "$V4L2_CONF" << 'EOF'
options v4l2loopback devices=8 video_nr=10,11,12,13,14,15,16,17 card_label="TitanCam0","TitanCam1","TitanCam2","TitanCam3","TitanCam4","TitanCam5","TitanCam6","TitanCam7" exclusive_caps=1
EOF
echo "[✓] v4l2loopback configured for 8 virtual cameras"

# ─── Install Cuttlefish host tools ───────────────────────────────────
CVD_DIR="/opt/android-cuttlefish"
if [ ! -d "$CVD_DIR" ]; then
    echo "[*] Cloning android-cuttlefish host tools..."
    git clone https://github.com/google/android-cuttlefish.git "$CVD_DIR" 2>/dev/null || true
fi

# Build and install cuttlefish host packages
if [ -d "$CVD_DIR" ]; then
    echo "[*] Building Cuttlefish host packages..."
    cd "$CVD_DIR"
    if [ -f "tools/buildutils/build_packages.sh" ]; then
        bash tools/buildutils/build_packages.sh
        dpkg -i ./cuttlefish-base_*.deb ./cuttlefish-user_*.deb 2>/dev/null || true
    fi
    cd -
fi
echo "[✓] Cuttlefish host tools installed"

# ─── Create Titan Cuttlefish directories ─────────────────────────────
TITAN_CVD="/opt/titan/cuttlefish"
mkdir -p "$TITAN_CVD/images"
mkdir -p "$TITAN_CVD/logs"
mkdir -p /opt/titan/data/devices

echo "[✓] Directories created:"
echo "     Images:  $TITAN_CVD/images"
echo "     Logs:    $TITAN_CVD/logs"
echo "     Devices: /opt/titan/data/devices"

# ─── Download Cuttlefish AOSP images ─────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  MANUAL STEP: Download Cuttlefish AOSP images"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Download the latest aosp_cf_x86_64_phone target:"
echo "  1. Go to https://ci.android.com/"
echo "  2. Search for branch: aosp-main"
echo "  3. Find target: aosp_cf_x86_64_phone-trunk_staging-userdebug"
echo "  4. Download: cvd-host_package.tar.gz + aosp_cf_x86_64_phone-img-*.zip"
echo "  5. Extract both to: $TITAN_CVD/images/"
echo ""
echo "Or use the OTA artifacts:"
echo "  wget https://ci.android.com/builds/latest/branches/aosp-main/targets/aosp_cf_x86_64_phone-trunk_staging-userdebug/view/cvd-host_package.tar.gz"
echo "  tar -xzf cvd-host_package.tar.gz -C $TITAN_CVD/images/"
echo ""

# ─── Add cuttlefish group ────────────────────────────────────────────
if ! getent group cvdnetwork >/dev/null 2>&1; then
    groupadd cvdnetwork 2>/dev/null || true
fi
if ! getent group kvm >/dev/null 2>&1; then
    groupadd kvm 2>/dev/null || true
fi
usermod -aG kvm,cvdnetwork root 2>/dev/null || true
echo "[✓] User groups configured"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Download AOSP Cuttlefish images to $TITAN_CVD/images/"
echo "  2. Set environment variables (or use defaults):"
echo "     export CVD_BIN_DIR=$TITAN_CVD/images/bin"
echo "     export CVD_IMAGES_DIR=$TITAN_CVD/images"
echo "     export CVD_HOME_BASE=$TITAN_CVD"
echo "  3. Start the Titan API server"
echo "  4. Create a device via API: POST /api/devices"
echo ""
