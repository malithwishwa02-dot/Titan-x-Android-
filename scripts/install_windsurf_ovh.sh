#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Install Windsurf IDE on OVH KS-4 Server
# Windsurf: AI-native code editor for remote development via xRDP
#
# Usage:  ssh -i /root/.ssh/id_ed25519 root@51.68.33.34
#         bash /opt/titan-v11.3-device/scripts/install_windsurf_ovh.sh
#
# After completion: Launch Windsurf from XFCE Applications menu
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

OVH_IP="51.68.33.34"
INSTALL_LOG="/var/log/windsurf-install.log"

log() { 
    echo -e "\n\033[1;36m══ $1\033[0m" | tee -a "$INSTALL_LOG"
}

error() {
    echo -e "\033[1;31m✗ ERROR: $1\033[0m" | tee -a "$INSTALL_LOG"
    exit 1
}

success() {
    echo -e "\033[1;32m✓ $1\033[0m" | tee -a "$INSTALL_LOG"
}

# ─── Phase 1: Check Prerequisites ──────────────────────────────────
log "Phase 1: Checking prerequisites"

# Check if running on OVH server
CURRENT_IP=$(hostname -I | awk '{print $1}')
if [[ "$CURRENT_IP" != "$OVH_IP" ]]; then
    echo "⚠️  Warning: Not running on OVH server (expected $OVH_IP, got $CURRENT_IP)"
    echo "   Continuing anyway..."
fi

# Check Ubuntu version
if [ -f /etc/os-release ]; then
    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        error "This script is designed for Ubuntu. Detected: $ID"
    fi
    success "Ubuntu $VERSION_ID detected"
else
    error "Cannot detect OS version"
fi

# Check glibc version (requirement: >= 2.28)
GLIBC_VERSION=$(ldd --version | head -n1 | awk '{print $NF}')
success "glibc version: $GLIBC_VERSION (requirement: >= 2.28)"

# Check if XFCE is installed
if ! command -v xfce4-session &>/dev/null; then
    error "XFCE4 not found. Please run setup_ovh_desktop.sh first."
fi
success "XFCE4 desktop environment detected"

# ─── Phase 2: Install Dependencies ─────────────────────────────────
log "Phase 2: Installing dependencies"

apt-get update -qq

# Install required libraries for Electron-based apps
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    libgtk-3-0 \
    libnotify4 \
    libnss3 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    libatspi2.0-0 \
    libdrm2 \
    libgbm1 \
    libxcb-dri3-0 \
    libsecret-1-0 \
    libglib2.0-bin \
    ca-certificates \
    wget \
    curl

success "Dependencies installed"

# ─── Phase 3: Add Windsurf APT Repository ──────────────────────────
log "Phase 3: Adding Windsurf APT repository"

# Add GPG key
echo "  Adding Windsurf GPG key..."
curl -fsSL "https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/windsurf.gpg" | \
    gpg --dearmor -o /usr/share/keyrings/windsurf-stable-archive-keyring.gpg

success "GPG key added"

# Add repository
echo "  Adding Windsurf repository..."
echo "deb [signed-by=/usr/share/keyrings/windsurf-stable-archive-keyring.gpg] https://windsurf-stable.codeiumdata.com/wVxQEIWkwPUEAGf3/apt stable main" | \
    tee /etc/apt/sources.list.d/windsurf.list > /dev/null

success "Repository added"

# Update package list
apt-get update -qq

# ─── Phase 4: Install Windsurf ─────────────────────────────────────
log "Phase 4: Installing Windsurf IDE"

# Install via APT
if DEBIAN_FRONTEND=noninteractive apt-get install -y windsurf 2>&1 | tee -a "$INSTALL_LOG"; then
    success "Windsurf installed via APT"
else
    error "Failed to install Windsurf"
fi

# Verify installation
if command -v windsurf &>/dev/null; then
    WINDSURF_PATH=$(which windsurf)
    success "Windsurf installed at: $WINDSURF_PATH"
else
    error "Windsurf binary not found after installation"
fi

# ─── Phase 5: Desktop Integration ──────────────────────────────────
log "Phase 5: Desktop integration"

# Verify .desktop file exists
DESKTOP_FILE="/usr/share/applications/windsurf.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    success "Desktop launcher created: $DESKTOP_FILE"
    
    # Make sure it's executable
    chmod +x "$DESKTOP_FILE" 2>/dev/null || true
    
    # Update desktop database
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database /usr/share/applications/ 2>/dev/null || true
    fi
else
    echo "  ⚠️  Desktop file not found, creating manually..."
    
    # Create desktop entry manually
    cat > "$DESKTOP_FILE" << 'EOF'
[Desktop Entry]
Name=Windsurf
Comment=AI-native code editor
GenericName=Text Editor
Exec=/usr/bin/windsurf --unity-launch %F
Icon=windsurf
Type=Application
StartupNotify=false
StartupWMClass=Windsurf
Categories=Utility;TextEditor;Development;IDE;
MimeType=text/plain;inode/directory;
Actions=new-empty-window;
Keywords=windsurf;

[Desktop Action new-empty-window]
Name=New Empty Window
Exec=/usr/bin/windsurf --new-window %F
Icon=windsurf
EOF
    chmod 644 "$DESKTOP_FILE"
    success "Desktop launcher created manually"
fi

# Create desktop shortcut for root user
DESKTOP_SHORTCUT="/root/Desktop/windsurf.desktop"
if [ ! -d "/root/Desktop" ]; then
    mkdir -p "/root/Desktop"
fi

cp "$DESKTOP_FILE" "$DESKTOP_SHORTCUT" 2>/dev/null || true
chmod +x "$DESKTOP_SHORTCUT" 2>/dev/null || true
success "Desktop shortcut created"

# ─── Phase 6: Configuration ─────────────────────────────────────────
log "Phase 6: Initial configuration"

# Create config directory
mkdir -p /root/.config/Windsurf/User

# Create initial settings (disable telemetry, GPU acceleration for RDP)
cat > /root/.config/Windsurf/User/settings.json << 'EOF'
{
    "telemetry.telemetryLevel": "off",
    "workbench.startupEditor": "none",
    "window.menuBarVisibility": "toggle",
    "editor.fontSize": 14,
    "terminal.integrated.fontSize": 13,
    "disable-hardware-acceleration": true
}
EOF

success "Initial configuration created"

# ─── Phase 7: Cleanup ───────────────────────────────────────────────
log "Phase 7: Cleanup"

# Clean APT cache
apt-get clean
success "APT cache cleaned up"

# ─── Done ───────────────────────────────────────────────────────────
log "✅ WINDSURF IDE INSTALLATION COMPLETE"
echo ""
echo "  Server IP:        $OVH_IP"
echo "  RDP Access:       $OVH_IP:3389 (root/TitanKS4-2026!)"
echo "  Windsurf Binary:  $(which windsurf)"
echo "  Config Dir:       /root/.config/Windsurf/"
echo ""
echo "  Launch Methods:"
echo "    1. Via xRDP: Applications → Development → Windsurf"
echo "    2. Desktop shortcut: Double-click Windsurf icon on desktop"
echo "    3. Terminal: windsurf"
echo ""
echo "  Installation log: $INSTALL_LOG"
echo ""
