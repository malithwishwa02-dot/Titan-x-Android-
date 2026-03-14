#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Titan V11.3 — OVH KS-4 Desktop Deployment Setup
# One-shot script: installs XFCE4 + xRDP + system deps + Titan API
# + Electron desktop app + Ollama AI on OVH bare-metal server.
#
# Usage:  ssh root@51.68.33.34
#         bash /opt/titan-v11.3-device/scripts/setup_ovh_desktop.sh
#
# After completion: RDP into 51.68.33.34:3389 with root credentials
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

OVH_IP="51.68.33.34"
TITAN_ROOT="/opt/titan-v11.3-device"
TITAN_DATA="/opt/titan/data"
HOSTINGER_IP="72.62.72.48"

log() { echo -e "\n\033[1;36m══ $1\033[0m"; }

# ─── Phase 1: System Update ────────────────────────────────────────
log "Phase 1: System update + hostname"
hostnamectl set-hostname titan-ks4
apt update && apt upgrade -y

# ─── Phase 2: XFCE4 Desktop + xRDP ─────────────────────────────────
log "Phase 2: Installing XFCE4 + xRDP"
DEBIAN_FRONTEND=noninteractive apt install -y \
  xfce4 xfce4-goodies xfce4-terminal dbus-x11 \
  xrdp

usermod -aG ssl-cert xrdp

# Set XFCE as default session
cat > /root/.xsession << 'EOF'
xfce4-session
EOF
chmod +x /root/.xsession
echo "xfce4-session" > /etc/skel/.xsession

systemctl enable --now xrdp
systemctl enable --now xrdp-sesman

# ─── Phase 3: xRDP Performance Optimization ────────────────────────
log "Phase 3: Optimizing xRDP for zero-lag"
bash "${TITAN_ROOT}/scripts/optimize_xrdp.sh"

# ─── Phase 4: System Dependencies ──────────────────────────────────
log "Phase 4: System dependencies"
DEBIAN_FRONTEND=noninteractive apt install -y \
  python3-pip python3-venv git curl wget rsync \
  android-tools-adb sqlite3 tesseract-ocr ffmpeg \
  qemu-kvm libvirt-daemon-system \
  autossh openssh-client openssl

# Node.js 20 LTS (required for Electron 28)
if ! command -v node &>/dev/null || [[ "$(node -v)" != v20* ]]; then
  log "Installing Node.js 20 LTS"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt install -y nodejs
fi

# KVM kernel modules (persistent)
cat > /etc/modules-load.d/titan.conf << 'EOF'
kvm
kvm_intel
vhost_vsock
vhost_net
EOF
modprobe kvm kvm_intel vhost_vsock vhost_net 2>/dev/null || true

if [ -e /dev/kvm ]; then
  echo "  ✅ /dev/kvm available"
else
  echo "  ⚠️  /dev/kvm not found — Cuttlefish VMs won't work"
fi

# ─── Phase 5: Deploy Codebase + Python Env ─────────────────────────
log "Phase 5: Codebase + Python venv"
mkdir -p "$TITAN_DATA" "$TITAN_DATA/profiles" "$TITAN_DATA/devices" "$TITAN_DATA/config"

# Sync from Hostinger if codebase not present locally
if [ ! -f "${TITAN_ROOT}/server/titan_api.py" ]; then
  log "Syncing codebase from Hostinger (${HOSTINGER_IP})..."
  rsync -avz --exclude='.git' --exclude='desktop/node_modules' --exclude='venv' \
    "root@${HOSTINGER_IP}:/opt/titan-v11.3-device/" \
    "${TITAN_ROOT}/"
fi

# Sync data if not present
if [ ! -d "${TITAN_DATA}/profiles" ] || [ -z "$(ls -A ${TITAN_DATA}/profiles 2>/dev/null)" ]; then
  log "Syncing data from Hostinger..."
  rsync -avz "root@${HOSTINGER_IP}:/opt/titan/data/" "${TITAN_DATA}/" || true
fi

# Copy Vast.ai SSH key
if [ ! -f /root/.ssh/vastai_key ]; then
  rsync "root@${HOSTINGER_IP}:/root/.ssh/vastai_key" /root/.ssh/vastai_key 2>/dev/null || true
  chmod 600 /root/.ssh/vastai_key 2>/dev/null || true
fi

# Python virtual environment
if [ ! -d "${TITAN_ROOT}/venv" ]; then
  log "Creating Python venv..."
  cd "${TITAN_ROOT}"
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  pip install -r server/requirements.txt
  pip install ovh
else
  source "${TITAN_ROOT}/venv/bin/activate"
fi

# Create .env if not exists
if [ ! -f "${TITAN_ROOT}/.env" ]; then
  cp "${TITAN_ROOT}/.env.example" "${TITAN_ROOT}/.env"
  SECRET=$(openssl rand -hex 24)
  sed -i "s/change-me-to-a-secure-random-string/${SECRET}/" "${TITAN_ROOT}/.env"
  echo "  ✅ .env created with generated API secret"
fi

# ─── Phase 6: Titan API — Systemd Service ──────────────────────────
log "Phase 6: Titan API systemd service"
cat > /etc/systemd/system/titan-api.service << EOF
[Unit]
Description=Titan V11.3 API Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${TITAN_ROOT}/server
Environment=PYTHONPATH=${TITAN_ROOT}/server:${TITAN_ROOT}/core
Environment=TITAN_DATA=${TITAN_DATA}
Environment=TITAN_GPU_OLLAMA=http://127.0.0.1:11435
Environment=TITAN_CPU_OLLAMA=http://127.0.0.1:11434
ExecStart=${TITAN_ROOT}/venv/bin/uvicorn titan_api:app --host 127.0.0.1 --port 8080 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now titan-api
sleep 3

if curl -s http://127.0.0.1:8080/ >/dev/null 2>&1; then
  echo "  ✅ Titan API running on :8080"
else
  echo "  ⚠️  API not responding yet — check: journalctl -u titan-api -f"
fi

# ─── Phase 7: Desktop App (Electron) ───────────────────────────────
log "Phase 7: Electron desktop app"
cd "${TITAN_ROOT}/desktop"
npm install

# Auto-start on XFCE login
mkdir -p /root/.config/autostart
cat > /root/.config/autostart/titan-console.desktop << EOF
[Desktop Entry]
Type=Application
Name=Titan Console
Comment=Titan V11.3 Android Console
Exec=${TITAN_ROOT}/desktop/start.sh
Icon=${TITAN_ROOT}/desktop/assets/icon.png
Terminal=false
Categories=Development;
StartupNotify=true
X-GNOME-Autostart-enabled=true
EOF

echo "  ✅ Titan Console desktop app installed (auto-starts on login)"

# ─── Phase 8: Ollama AI (CPU fallback) ─────────────────────────────
log "Phase 8: Ollama AI engine"
if ! command -v ollama &>/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
systemctl enable --now ollama
sleep 2

# Pull minimum model in background (non-blocking)
echo "  Pulling qwen2.5:7b in background..."
nohup ollama pull qwen2.5:7b > /tmp/ollama-pull.log 2>&1 &

# Vast.ai GPU tunnel (if key exists)
if [ -f /root/.ssh/vastai_key ]; then
  if [ -f "/etc/systemd/system/titan-vastai-tunnel.service" ]; then
    log "Vast.ai tunnel service already present"
    systemctl enable --now titan-vastai-tunnel || true
  else
    # Try to copy from Hostinger
    rsync "root@${HOSTINGER_IP}:/etc/systemd/system/titan-vastai-tunnel.service" \
      /etc/systemd/system/titan-vastai-tunnel.service 2>/dev/null && {
      systemctl daemon-reload
      systemctl enable --now titan-vastai-tunnel
      echo "  ✅ Vast.ai GPU tunnel started"
    } || echo "  ℹ️  No tunnel service on Hostinger — configure manually later"
  fi
fi

# ─── Done ───────────────────────────────────────────────────────────
log "✅ SETUP COMPLETE"
echo ""
echo "  Server IP:    ${OVH_IP}"
echo "  RDP:          ${OVH_IP}:3389 (username: root)"
echo "  API:          http://127.0.0.1:8080 (localhost only)"
echo "  Ollama CPU:   http://127.0.0.1:11434"
echo "  Ollama GPU:   http://127.0.0.1:11435 (if tunnel active)"
echo ""
echo "  Connect via RDP → Titan Console auto-launches"
echo "  Model download running in background: tail -f /tmp/ollama-pull.log"
echo ""
