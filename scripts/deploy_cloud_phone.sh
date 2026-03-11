#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Titan Cloud Phone — One-Command Deploy
# Deploys a full cloud Android phone on any KVM VPS with Docker.
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

# ─── Phase 2: Kernel modules ─────────────────────────────────
echo "[2/6] Loading kernel modules for Redroid..."
modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null || {
    echo "  ⚠ binder_linux not found — trying to install..."
    apt-get install -y -qq linux-modules-extra-$(uname -r) 2>/dev/null || true
    modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null || {
        echo "  ✗ FATAL: binder_linux not available. Redroid needs KVM VPS, not OpenVZ."
        exit 1
    }
}
echo "binder_linux" >> /etc/modules-load.d/titan.conf 2>/dev/null || true
echo "  ✓ binder_linux loaded"

# ─── Phase 3: Pull Docker images ─────────────────────────────
echo "[3/6] Pulling Docker images (~6GB)..."
docker pull redroid/redroid:14.0.0-latest
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

# ─── Phase 6: Start services ─────────────────────────────────
echo "[6/6] Starting cloud phone services..."

# Stop old containers
docker rm -f titan-android titan-scrcpy titan-api titan-nginx 2>/dev/null || true

# Start Redroid Android
docker run -d --name titan-android --privileged \
    --restart unless-stopped \
    --memory=3g --cpus=2 \
    -p 5555:5555 \
    -v titan-android-data:/data \
    redroid/redroid:14.0.0-latest \
    "androidboot.redroid_gpu_mode=guest" \
    "androidboot.redroid_width=1080" \
    "androidboot.redroid_height=2400" \
    "androidboot.redroid_fps=30" \
    "androidboot.redroid_dpi=420"

echo "  Waiting for Android boot (40s)..."
sleep 40
adb connect 127.0.0.1:5555 2>/dev/null || true

# Start ws-scrcpy
docker run -d --name titan-scrcpy --network host \
    --restart unless-stopped \
    scavin/ws-scrcpy:latest

# Start Titan API
cd "$TITAN_DIR"
TITAN_DATA=/opt/titan/data \
PYTHONPATH="$TITAN_DIR/server:$TITAN_DIR/core" \
nohup python3 -m uvicorn server.titan_api:app \
    --host 0.0.0.0 --port 8080 --workers 1 \
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
