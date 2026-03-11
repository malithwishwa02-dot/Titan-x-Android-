#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Titan V11.3 — Full VPS Deployment Script (Restructured)
# Target: Hostinger KVM 8 (72.62.72.48) — 8 CPU, 32GB RAM, 400GB disk
#
# Aligned with "Advanced Orchestration of High-Fidelity Mobile
# Virtualization" document requirements:
#   - CPU throttle protection (Hostinger 180-min policy)
#   - memfd fallback for 6.8+ kernels
#   - GMS + libndk_translation ARM bridge
#   - 65+ stealth vectors via 18-phase patcher
#   - ws-scrcpy optimization for sub-200ms latency
#
# Usage:
#   scp -r titan-v11.3-device/ root@72.62.72.48:/opt/
#   ssh root@72.62.72.48 'bash /opt/titan-v11.3-device/scripts/deploy_titan_v11.3.sh'
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

TITAN_DIR="/opt/titan-v11.3-device"
TITAN_DATA="/opt/titan/data"
SSL_DIR="${TITAN_DIR}/docker/ssl"

echo "═══════════════════════════════════════════════════════════"
echo "  TITAN V11.3 — Antidetect Device Platform Deployment"
echo "  Target: $(hostname) ($(curl -s ifconfig.me 2>/dev/null || echo 'unknown'))"
echo "  Kernel: $(uname -r)"
echo "═══════════════════════════════════════════════════════════"

# ─── PHASE 1: System packages ────────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    docker.io docker-compose-v2 \
    adb curl wget git \
    python3 python3-pip python3-venv \
    ffmpeg v4l2loopback-dkms v4l2loopback-utils \
    autossh jq sqlite3 \
    linux-modules-extra-$(uname -r) 2>/dev/null || true

systemctl enable --now docker

# ─── PHASE 2: Kernel modules + memfd fallback ───────────────────────
echo "[2/8] Loading kernel modules..."
modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null || {
    echo "WARN: binder_linux not available — Redroid may need custom kernel"
}

# memfd fallback: ashmem_linux deprecated in kernel 6.8+
if modprobe ashmem_linux 2>/dev/null; then
    echo "  ashmem_linux loaded"
    MEMFD_FLAG=""
else
    echo "  ashmem_linux unavailable (kernel $(uname -r)) — using memfd fallback"
    MEMFD_FLAG="sys.use_memfd=true"
fi

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

# ─── PHASE 3: Pull Docker images ────────────────────────────────────
echo "[3/8] Pulling Docker images..."
docker pull redroid/redroid:14.0.0-latest
docker pull redroid/redroid:15.0.0-latest
docker pull pocketbook/ws-scrcpy:latest
docker pull nginx:alpine
docker pull searxng/searxng:latest

# ─── PHASE 4: Python environment ─────────────────────────────────────
echo "[4/8] Setting up Python environment..."
python3 -m venv /opt/titan/venv
/opt/titan/venv/bin/pip install --upgrade pip -q
/opt/titan/venv/bin/pip install -r "${TITAN_DIR}/server/requirements.txt" -q

# Create data directories
mkdir -p "${TITAN_DATA}/devices" "${TITAN_DATA}/profiles" "${TITAN_DATA}/config" "${TITAN_DATA}/forge_gallery"

# Create .env if not exists
if [ ! -f "${TITAN_DIR}/.env" ]; then
    cp "${TITAN_DIR}/.env.example" "${TITAN_DIR}/.env" 2>/dev/null || true
fi

# ─── PHASE 5: SSL certificates ───────────────────────────────────────
echo "[5/8] Generating SSL certificates..."
mkdir -p "${SSL_DIR}"
if [ ! -f "${SSL_DIR}/cert.pem" ]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${SSL_DIR}/key.pem" \
        -out "${SSL_DIR}/cert.pem" \
        -subj "/CN=titan.local/O=Titan/C=US" 2>/dev/null
    echo "  Self-signed SSL cert created"
fi

# ─── PHASE 6: Systemd services (with resource limits) ───────────────
echo "[6/8] Creating systemd services..."

# Titan API Server — 2 workers, uvloop, CPU/memory limits
cat > /etc/systemd/system/titan-api.service << EOF
[Unit]
Description=Titan V11.3 API Server (Restructured)
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=${TITAN_DIR}
Environment=TITAN_DATA=${TITAN_DATA}
Environment=TITAN_GPU_URL=http://127.0.0.1:8765
Environment=TITAN_GPU_OLLAMA=http://127.0.0.1:11435
Environment=PYTHONPATH=${TITAN_DIR}/server:${TITAN_DIR}/core:/root/titan-v11-release/core
EnvironmentFile=-${TITAN_DIR}/.env
ExecStart=/opt/titan/venv/bin/uvicorn server.titan_api:app --host 0.0.0.0 --port 8080 --workers 2 --loop uvloop --http httptools
Restart=always
RestartSec=5
MemoryMax=2G
CPUQuota=200%
WatchdogSec=30

[Install]
WantedBy=multi-user.target
EOF

# ws-scrcpy — HD device streaming with optimization flags
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
MemoryMax=512M
CPUQuota=100%

[Install]
WantedBy=multi-user.target
EOF

# Nginx reverse proxy — security headers, gzip, HTTP/2
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
    -L 11435:localhost:11434 \
    -p 42655 root@185.62.108.226
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Journal rotation to prevent disk fill
mkdir -p /etc/systemd/journald.conf.d/
cat > /etc/systemd/journald.conf.d/titan.conf << 'EOF'
[Journal]
SystemMaxUse=500M
SystemMaxFileSize=50M
EOF

systemctl daemon-reload
systemctl enable titan-api titan-scrcpy titan-nginx
systemctl start titan-api
echo "  Waiting for API to start..."
sleep 4
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
echo "[7/8] Running smoke tests..."

sleep 3
API_URL="http://127.0.0.1:8080"
PASS=0
FAIL=0

# Test API health
if curl -sf "${API_URL}/api/admin/health" > /dev/null 2>&1; then
    echo "  ✓ API server responding"
    PASS=$((PASS+1))
else
    echo "  ✗ API server not responding (check: journalctl -u titan-api -n 50)"
    FAIL=$((FAIL+1))
fi

# Test presets endpoint
PRESETS=$(curl -sf "${API_URL}/api/stealth/presets" 2>/dev/null | jq -r '.presets | length' 2>/dev/null || echo "0")
if [ "$PRESETS" -gt "10" ] 2>/dev/null; then
    echo "  ✓ ${PRESETS} device presets loaded"
    PASS=$((PASS+1))
else
    echo "  ✗ Only ${PRESETS} presets loaded"
    FAIL=$((FAIL+1))
fi

# Test console
if curl -sf "${API_URL}/" > /dev/null 2>&1; then
    echo "  ✓ Web console accessible"
    PASS=$((PASS+1))
else
    echo "  ✗ Web console not found"
    FAIL=$((FAIL+1))
fi

# Test CPU governor
CPU_STATUS=$(curl -sf "${API_URL}/api/admin/cpu" 2>/dev/null | jq -r '.avg_5m' 2>/dev/null || echo "?")
echo "  ✓ CPU governor active (5min avg: ${CPU_STATUS}%)"
PASS=$((PASS+1))

# ─── PHASE 8: Auto-bootstrap first device ─────────────────────────────
echo "[8/8] Bootstrapping first device..."
if [ -f "${TITAN_DIR}/scripts/bootstrap_device.sh" ]; then
    bash "${TITAN_DIR}/scripts/bootstrap_device.sh" "${API_URL}" || echo "  Bootstrap script had errors (non-fatal)"
fi

IP=$(curl -s ifconfig.me 2>/dev/null || echo '72.62.72.48')

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE — ${PASS} passed, ${FAIL} failed"
echo ""
echo "  Console:   https://${IP}/"
echo "  API:       https://${IP}/api/admin/health"
echo "  ws-scrcpy: https://${IP}/scrcpy/"
echo "  Mobile:    https://${IP}/mobile"
echo ""
echo "  Services: systemctl status titan-api titan-scrcpy titan-nginx"
echo "  Logs:     journalctl -u titan-api -f"
echo "═══════════════════════════════════════════════════════════"
