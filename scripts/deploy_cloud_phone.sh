#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Titan Cloud Phone — One-Command Deploy (Cuttlefish)
# Deploys a full cloud Android phone on any KVM VPS using Cuttlefish.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/.../deploy_cloud_phone.sh | bash
#   OR: bash deploy_cloud_phone.sh
#
# Requirements: Ubuntu 22.04/24.04, KVM VPS (not OpenVZ), 4+ cores, 8+ GB RAM
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

TITAN_DIR="${TITAN_DIR:-/opt/titan-v11.3-device}"
IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo "═══════════════════════════════════════════════════════"
echo "  TITAN CLOUD PHONE — One-Command Deploy"
echo "  Host: $(hostname) ($IP)"
echo "═══════════════════════════════════════════════════════"

# ─── Phase 1: System deps ─────────────────────────────────────
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq docker.io adb python3 python3-pip curl wget jq openssl 2>/dev/null

systemctl enable --now docker

# ─── Phase 2: Kernel modules for Cuttlefish ───────────────────────
echo "[2/6] Loading kernel modules for Cuttlefish..."
modprobe vhost_vsock 2>/dev/null || {
    echo "  ⚠ vhost_vsock not found — trying to install..."
    apt-get install -y -qq linux-modules-extra-$(uname -r) 2>/dev/null || true
    modprobe vhost_vsock 2>/dev/null || {
        echo "  ✗ FATAL: vhost_vsock not available. Cuttlefish needs KVM VPS, not OpenVZ."
        exit 1
    }
}
echo "vhost_vsock" >> /etc/modules-load.d/titan.conf 2>/dev/null || true
echo "  ✓ vhost_vsock loaded"

# ─── Phase 3: Setup Cuttlefish + supporting images ─────────────────
echo "[3/6] Setting up Cuttlefish + pulling supporting images..."
CVD_HOME=/opt/titan/cuttlefish/cf
mkdir -p "$CVD_HOME" /opt/titan/cuttlefish/images
if [ -f "${TITAN_DIR}/scripts/setup_cuttlefish.sh" ]; then
    bash "${TITAN_DIR}/scripts/setup_cuttlefish.sh"
fi
docker pull scavin/ws-scrcpy:latest
docker pull nginx:alpine

# ─── Phase 4: Install Python deps ────────────────────────────
echo "[4/6] Installing Python packages..."
pip3 install --break-system-packages -q fastapi uvicorn pydantic pillow 2>/dev/null || \
pip3 install -q fastapi uvicorn pydantic pillow 2>/dev/null

# ─── Phase 5: SSL certs ──────────────────────────────────────
echo "[5/6] Generating SSL certificates..."
SSL_DIR="$TITAN_DIR/docker/ssl"
mkdir -p "$SSL_DIR"
if [ ! -f "$SSL_DIR/cert.pem" ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$SSL_DIR/key.pem" -out "$SSL_DIR/cert.pem" \
        -subj "/CN=titan.cloud/O=Titan/C=US" 2>/dev/null
fi

# ─── Phase 6: Start services ───────────────────────────────────────
echo "[6/6] Starting cloud phone services..."

# Stop old containers (supporting services only)
docker rm -f titan-scrcpy titan-nginx 2>/dev/null || true

# Launch Cuttlefish Android VM
CVD_HOME=/opt/titan/cuttlefish/cf
if [ -x "$CVD_HOME/bin/launch_cvd" ]; then
    cd "$CVD_HOME" && HOME="$CVD_HOME" ./bin/stop_cvd 2>/dev/null || true
    cd "$CVD_HOME" && HOME="$CVD_HOME" ./bin/launch_cvd \
        --daemon --cpus=2 --memory_mb=4096 \
        --gpu_mode=guest_swiftshader \
        --start_webrtc=true \
        --report_anonymous_usage_stats=n &
    echo "  Waiting for Cuttlefish boot (30s)..."
    sleep 30
    adb connect 127.0.0.1:6520 2>/dev/null || true
else
    echo "  ⚠ launch_cvd not found at $CVD_HOME/bin/ — run setup_cuttlefish.sh first"
fi

# Start ws-scrcpy
docker run -d --name titan-scrcpy --network host \
    --restart unless-stopped \
    scavin/ws-scrcpy:latest

# Start Titan API
cd "$TITAN_DIR"
TITAN_DATA=/opt/titan/data \
CVD_BIN_DIR=$CVD_HOME/bin \
CVD_HOME_BASE=/opt/titan/cuttlefish \
CVD_IMAGES_DIR=/opt/titan/cuttlefish/images \
PYTHONPATH="$TITAN_DIR/server:$TITAN_DIR/core" \
nohup python3 -m uvicorn server.titan_api:app \
    --host 0.0.0.0 --port 8080 --workers 2 --loop uvloop --http httptools \
    > /tmp/titan_api.log 2>&1 &

sleep 3

# Start Nginx
docker run -d --name titan-nginx --network host \
    --restart unless-stopped \
    -v "$TITAN_DIR/docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$SSL_DIR:/etc/nginx/ssl:ro" \
    nginx:alpine

sleep 2

# ─── Verify ──────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
HEALTH=$(curl -sf http://localhost:8080/api/admin/health 2>/dev/null && echo " ✓" || echo " ✗")
SCRCPY=$(curl -sf http://localhost:8000/ > /dev/null 2>&1 && echo "✓" || echo "✗")
NGINX=$(curl -skf https://localhost/ > /dev/null 2>&1 && echo "✓" || echo "✗")

echo "  API:     $HEALTH"
echo "  Scrcpy:  $SCRCPY"
echo "  Nginx:   $NGINX"
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  CLOUD PHONE READY                          │"
echo "  │                                             │"
echo "  │  Phone:   https://$IP/scrcpy/       │"
echo "  │  Mobile:  https://$IP/mobile        │"
echo "  │  Console: https://$IP/              │"
echo "  │                                             │"
echo "  │  Next: bash scripts/bootstrap_device.sh     │"
echo "  │  (auto-patches + forges 100/100 trust)      │"
echo "  └─────────────────────────────────────────────┘"
echo "═══════════════════════════════════════════════════════"
