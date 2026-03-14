#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Titan V11.3 — xRDP Performance Optimization
# Tunes xRDP for zero-lag remote desktop on OVH KS-4 bare-metal.
#
# Key optimizations:
#   - tcp_nodelay=true (disable Nagle — immediate packet send)
#   - crypt_level=low (biggest single perf boost)
#   - 4 MB TCP send buffer
#   - XFCE compositor disabled
#   - Screen blanker / DPMS disabled
#   - Solid dark wallpaper (no image decode overhead)
#
# Usage:  bash /opt/titan-v11.3-device/scripts/optimize_xrdp.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

log() { echo -e "\033[1;33m  → $1\033[0m"; }

# ─── xrdp.ini — Network + Encoding ─────────────────────────────────
XRDP_INI="/etc/xrdp/xrdp.ini"
if [ -f "$XRDP_INI" ]; then
  cp "$XRDP_INI" "${XRDP_INI}.bak.$(date +%s)"
  log "Tuning ${XRDP_INI}"

  # tcp_nodelay — disable Nagle's algorithm
  if grep -q "^tcp_nodelay=" "$XRDP_INI"; then
    sed -i 's/^tcp_nodelay=.*/tcp_nodelay=true/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a tcp_nodelay=true' "$XRDP_INI"
  fi

  # tcp_keepalive — keep connection alive during idle
  if grep -q "^tcp_keepalive=" "$XRDP_INI"; then
    sed -i 's/^tcp_keepalive=.*/tcp_keepalive=true/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a tcp_keepalive=true' "$XRDP_INI"
  fi

  # tcp_send_buffer_bytes — 4 MB send buffer
  if grep -q "^tcp_send_buffer_bytes=" "$XRDP_INI"; then
    sed -i 's/^tcp_send_buffer_bytes=.*/tcp_send_buffer_bytes=4194304/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a tcp_send_buffer_bytes=4194304' "$XRDP_INI"
  fi

  # crypt_level — low encryption (massive perf boost, server is private)
  if grep -q "^crypt_level=" "$XRDP_INI"; then
    sed -i 's/^crypt_level=.*/crypt_level=low/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a crypt_level=low' "$XRDP_INI"
  fi

  # max_bpp — 24-bit color (good balance between quality and bandwidth)
  if grep -q "^max_bpp=" "$XRDP_INI"; then
    sed -i 's/^max_bpp=.*/max_bpp=24/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a max_bpp=24' "$XRDP_INI"
  fi

  # new_cursors — faster cursor rendering
  if grep -q "^new_cursors=" "$XRDP_INI"; then
    sed -i 's/^new_cursors=.*/new_cursors=true/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a new_cursors=true' "$XRDP_INI"
  fi

  # allow_channels — enable clipboard, audio, etc.
  if grep -q "^allow_channels=" "$XRDP_INI"; then
    sed -i 's/^allow_channels=.*/allow_channels=true/' "$XRDP_INI"
  else
    sed -i '/^\[Globals\]/a allow_channels=true' "$XRDP_INI"
  fi

  echo "  ✅ xrdp.ini optimized"
else
  echo "  ⚠️  ${XRDP_INI} not found — install xrdp first"
fi

# ─── sesman.ini — Session Management ───────────────────────────────
SESMAN_INI="/etc/xrdp/sesman.ini"
if [ -f "$SESMAN_INI" ]; then
  cp "$SESMAN_INI" "${SESMAN_INI}.bak.$(date +%s)"
  log "Tuning ${SESMAN_INI}"

  # Kill disconnected sessions (free RAM immediately)
  if grep -q "^KillDisconnected=" "$SESMAN_INI"; then
    sed -i 's/^KillDisconnected=.*/KillDisconnected=true/' "$SESMAN_INI"
  else
    sed -i '/^\[Sessions\]/a KillDisconnected=true' "$SESMAN_INI"
  fi

  # No timeout for disconnected sessions (killed immediately by above)
  if grep -q "^DisconnectedTimeLimit=" "$SESMAN_INI"; then
    sed -i 's/^DisconnectedTimeLimit=.*/DisconnectedTimeLimit=0/' "$SESMAN_INI"
  else
    sed -i '/^\[Sessions\]/a DisconnectedTimeLimit=0' "$SESMAN_INI"
  fi

  # Max 2 concurrent sessions
  if grep -q "^MaxSessions=" "$SESMAN_INI"; then
    sed -i 's/^MaxSessions=.*/MaxSessions=2/' "$SESMAN_INI"
  else
    sed -i '/^\[Sessions\]/a MaxSessions=2' "$SESMAN_INI"
  fi

  echo "  ✅ sesman.ini optimized"
else
  echo "  ⚠️  ${SESMAN_INI} not found"
fi

# ─── XFCE4 — Disable Compositor (critical for RDP speed) ───────────
log "Disabling XFCE compositor + power management"
XFCE_CONF="/root/.config/xfce4/xfconf/xfce-perchannel-xml"
mkdir -p "$XFCE_CONF"

# Disable window compositor (eliminates GPU compositing overhead)
cat > "${XFCE_CONF}/xfwm4.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="cycle_draw_frame" type="bool" value="false"/>
    <property name="cycle_raise" type="bool" value="false"/>
    <property name="box_move" type="bool" value="true"/>
    <property name="box_resize" type="bool" value="true"/>
    <property name="zoom_desktop" type="bool" value="false"/>
    <property name="tile_on_move" type="bool" value="false"/>
    <property name="show_frame_shadow" type="bool" value="false"/>
    <property name="show_popup_shadow" type="bool" value="false"/>
  </property>
</channel>
XML

# Disable power management / screen blanker
cat > "${XFCE_CONF}/xfce4-power-manager.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="dpms-enabled" type="bool" value="false"/>
    <property name="blank-on-ac" type="int" value="0"/>
    <property name="dpms-on-ac-sleep" type="uint" value="0"/>
    <property name="dpms-on-ac-off" type="uint" value="0"/>
  </property>
</channel>
XML

# Solid dark wallpaper (Titan theme #0a0e17, no image decode)
cat > "${XFCE_CONF}/xfce4-desktop.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitorrdp0" type="empty">
        <property name="workspace0" type="empty">
          <property name="color-style" type="int" value="0"/>
          <property name="rgba1" type="array">
            <value type="double" value="0.039216"/>
            <value type="double" value="0.054902"/>
            <value type="double" value="0.090196"/>
            <value type="double" value="1.000000"/>
          </property>
          <property name="image-style" type="int" value="0"/>
        </property>
      </property>
    </property>
  </property>
</channel>
XML

# Disable screensaver
cat > "${XFCE_CONF}/xfce4-screensaver.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
  <property name="lock" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
</channel>
XML

echo "  ✅ XFCE compositor disabled"
echo "  ✅ Power management / DPMS disabled"
echo "  ✅ Screensaver disabled"
echo "  ✅ Solid dark wallpaper set"

# ─── Restart xRDP ──────────────────────────────────────────────────
log "Restarting xRDP services"
systemctl restart xrdp xrdp-sesman 2>/dev/null || true

echo ""
echo "  ✅ xRDP optimization complete"
echo "  Connect: mstsc.exe → 51.68.33.34:3389"
echo "  Use 24-bit color + LAN experience for best results"
echo ""
