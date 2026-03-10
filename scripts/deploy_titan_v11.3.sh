#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Titan V11.3 — Full VPS Deployment Script
# Target: Hostinger KVM 8 (72.62.72.48) — 8 CPU, 32GB RAM, 400GB disk
#
# Usage:
#   scp -r titan-v11.3-device/ root@72.62.72.48:/opt/
#   ssh root@72.62.72.48 'bash /opt/titan-v11.3-device/scripts/deploy_titan_v11.3.sh'
#
# What it does:
#   1. Install Docker + kernel modules + dependencies
#   2. Pull Redroid image + ws-scrcpy
#   3. Deploy Titan API server + console
#   4. Configure Nginx + self-signed SSL
#   5. Create systemd services
#   6. Set up GPU tunnel (if Vast.ai is configured)
#   7. Run smoke tests
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

TITAN_DIR="/opt/titan-v11.3-device"
TITAN_DATA="/opt/titan/data"
SSL_DIR="${TITAN_DIR}/docker/ssl"

echo "═══════════════════════════════════════════════════════════"
echo "  TITAN V11.3 — Antidetect Device Platform Deployment"
echo "  Target: $(hostname) ($(curl -s ifconfig.me 2>/dev/null || echo 'unknown'))"
echo "═══════════════════════════════════════════════════════════"

# ─── PHASE 1: System packages ────────────────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    docker.io docker-compose-v2 \
    adb curl wget git nginx \
    python3 python3-pip python3-venv \
    ffmpeg v4l2loopback-dkms v4l2loopback-utils \
    autossh jq \
    linux-modules-extra-$(uname -r) 2>/dev/null || true

# Enable Docker
systemctl enable --now docker

# ─── PHASE 2: Kernel modules for Redroid ─────────────────────────────
echo "[2/7] Loading kernel modules..."
modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null || {
    echo "WARN: binder_linux not available — Redroid may need custom kernel"
}
modprobe ashmem_linux 2>/dev/null || true
modprobe v4l2loopback devices=4 video_nr=10,11,12,13 \
    card_label="TitanCam0,TitanCam1,TitanCam2,TitanCam3" \
    exclusive_caps=1 2>/dev/null || true

# Persist modules
cat > /etc/modules-load.d/titan.conf << 'EOF'
binder_linux
ashmem_linux
v4l2loopback
EOF

cat > /etc/modprobe.d/titan-v4l2.conf << 'EOF'
options binder_linux devices=binder,hwbinder,vndbinder
options v4l2loopback devices=4 video_nr=10,11,12,13 card_label="TitanCam0,TitanCam1,TitanCam2,TitanCam3" exclusive_caps=1
EOF

# ─── PHASE 3: Pull Redroid + images ──────────────────────────────────
echo "[3/7] Pulling Docker images..."
docker pull redroid/redroid:14.0.0-latest
docker pull redroid/redroid:15.0.0-latest
docker pull nginx:alpine
docker pull searxng/searxng:latest

# ─── PHASE 4: Python environment ─────────────────────────────────────
echo "[4/7] Setting up Python environment..."
python3 -m venv /opt/titan/venv
/opt/titan/venv/bin/pip install --upgrade pip
/opt/titan/venv/bin/pip install -r "${TITAN_DIR}/server/requirements.txt"

# Create data directories
mkdir -p "${TITAN_DATA}/devices" "${TITAN_DATA}/profiles" "${TITAN_DATA}/config"

# ─── PHASE 5: SSL certificates ───────────────────────────────────────
echo "[5/7] Generating SSL certificates..."
mkdir -p "${SSL_DIR}"
if [ ! -f "${SSL_DIR}/cert.pem" ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${SSL_DIR}/key.pem" \
        -out "${SSL_DIR}/cert.pem" \
        -subj "/CN=titan.local/O=Titan/C=US" 2>/dev/null
    echo "  Self-signed SSL cert created"
fi

# ─── PHASE 6: Systemd services ───────────────────────────────────────
echo "[6/7] Creating systemd services..."

# Titan API Server
cat > /etc/systemd/system/titan-api.service << EOF
[Unit]
Description=Titan V11.3 API Server
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=${TITAN_DIR}
Environment=TITAN_DATA=${TITAN_DATA}
Environment=TITAN_GPU_URL=http://127.0.0.1:8765
Environment=PYTHONPATH=${TITAN_DIR}/server:${TITAN_DIR}/core:/root/titan-v11-release/core
ExecStart=/opt/titan/venv/bin/uvicorn server.titan_api:app --host 0.0.0.0 --port 8080 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ws-scrcpy (for HD device streaming)
cat > /etc/systemd/system/titan-scrcpy.service << EOF
[Unit]
Description=ws-scrcpy for Titan device streaming
After=docker.service

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker rm -f titan-scrcpy
ExecStart=/usr/bin/docker run --rm --name titan-scrcpy \
    --network host \
    -v /root/.android:/root/.android \
    pocketbook/ws-scrcpy:latest
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Nginx reverse proxy
cat > /etc/systemd/system/titan-nginx.service << EOF
[Unit]
Description=Titan Nginx Reverse Proxy
After=titan-api.service

[Service]
Type=simple
ExecStartPre=-/usr/bin/docker rm -f titan-nginx
ExecStart=/usr/bin/docker run --rm --name titan-nginx \
    --network host \
    -v ${TITAN_DIR}/docker/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
    -v ${SSL_DIR}:/etc/nginx/ssl:ro \
    nginx:alpine
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# GPU tunnel (optional — requires Vast.ai)
cat > /etc/systemd/system/titan-gpu-tunnel.service << 'EOF'
[Unit]
Description=Titan GPU Tunnel to Vast.ai
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/autossh -M 0 -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=no \
    -i /root/.ssh/vastai_key \
    -L 8765:localhost:8765 \
    -p 42655 root@185.62.108.226
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable titan-api titan-scrcpy titan-nginx
systemctl start titan-api
echo "  Waiting for API to start..."
sleep 3
systemctl start titan-scrcpy titan-nginx

# GPU tunnel (start only if key exists)
if [ -f /root/.ssh/vastai_key ]; then
    systemctl enable titan-gpu-tunnel
    systemctl start titan-gpu-tunnel
    echo "  GPU tunnel started"
else
    echo "  GPU tunnel skipped (no vastai_key)"
fi

# ─── PHASE 7: Smoke tests ────────────────────────────────────────────
echo "[7/7] Running smoke tests..."

sleep 2
API_URL="http://127.0.0.1:8080"

# Test API health
if curl -sf "${API_URL}/api/admin/health" > /dev/null 2>&1; then
    echo "  ✓ API server responding"
else
    echo "  ✗ API server not responding (check: journalctl -u titan-api)"
fi

# Test presets endpoint
PRESETS=$(curl -sf "${API_URL}/api/stealth/presets" 2>/dev/null | jq -r '.presets | length' 2>/dev/null || echo "0")
echo "  ✓ ${PRESETS} device presets loaded"

# Test console
if curl -sf "${API_URL}/" > /dev/null 2>&1; then
    echo "  ✓ Web console accessible"
else
    echo "  ✗ Web console not found"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE"
echo ""
echo "  Console:  https://$(curl -s ifconfig.me 2>/dev/null || echo '72.62.72.48')/"
echo "  API:      https://$(curl -s ifconfig.me 2>/dev/null || echo '72.62.72.48')/api/admin/health"
echo "  ws-scrcpy: http://$(curl -s ifconfig.me 2>/dev/null || echo '72.62.72.48'):8000/"
echo ""
echo "  Next: Open the console and create your first device!"
echo "═══════════════════════════════════════════════════════════"
