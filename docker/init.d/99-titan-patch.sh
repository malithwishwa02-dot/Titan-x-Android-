#!/system/bin/sh
# ═══════════════════════════════════════════════════════════════════════
# Titan V11.3 — Persistent Boot Patch Script
# Runs inside Redroid container on every boot via /system/etc/init.d/
# Re-applies non-persist properties that reset on reboot (gsm.*, battery, etc.)
# ═══════════════════════════════════════════════════════════════════════

LOG_TAG="TitanPatch"
log_i() { log -t "$LOG_TAG" -p i "$1"; }

log_i "Titan boot patch starting..."

# Wait for boot to complete
TIMEOUT=120
ELAPSED=0
while [ "$(getprop sys.boot_completed)" != "1" ] && [ $ELAPSED -lt $TIMEOUT ]; do
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done
log_i "Boot completed after ${ELAPSED}s"

# ─── Re-apply non-persist GSM/SIM props ──────────────────────────────
# These are wiped on every reboot — must be re-applied from persist.* source
MODEM_OPERATOR=$(getprop persist.sys.cloud.modem.operator)
MODEM_MCC=$(getprop persist.sys.cloud.modem.mcc)
MODEM_MNC=$(getprop persist.sys.cloud.modem.mnc)
MODEM_IMEI=$(getprop persist.sys.cloud.modem.imei)

if [ -n "$MODEM_OPERATOR" ]; then
    setprop gsm.sim.operator.alpha "$MODEM_OPERATOR"
    setprop gsm.sim.operator.numeric "${MODEM_MCC}${MODEM_MNC}"
    setprop gsm.operator.alpha "$MODEM_OPERATOR"
    setprop gsm.operator.numeric "${MODEM_MCC}${MODEM_MNC}"
    setprop gsm.sim.state "READY"
    setprop gsm.network.type "LTE"
    setprop gsm.current.phone-type "1"
    setprop gsm.nitz.time "$(date +%s)000"
    log_i "GSM props restored: $MODEM_OPERATOR ($MODEM_MCC/$MODEM_MNC)"
fi

# ─── Anti-emulator props ─────────────────────────────────────────────
setprop ro.kernel.qemu 0
setprop ro.hardware.virtual 0
setprop ro.boot.qemu 0
setprop ro.secure 1
setprop ro.debuggable 0
setprop ro.adb.secure 1
setprop ro.allow.mock.location 0
setprop ro.build.selinux 1
setprop ro.boot.verifiedbootstate green
setprop ro.boot.vbmeta.device_state locked
setprop ro.boot.flash.locked 1
log_i "Anti-emulator props set"

# ─── Hide emulator artifacts ─────────────────────────────────────────
mount -o bind /dev/null /proc/cmdline 2>/dev/null
mount -o bind /dev/null /proc/1/cgroup 2>/dev/null
log_i "Proc artifacts hidden"

# ─── Network: rename eth0 → wlan0 ────────────────────────────────────
ip link set eth0 down 2>/dev/null
ip link set eth0 name wlan0 2>/dev/null
ip link set wlan0 up 2>/dev/null

# Apply saved MAC if available
SAVED_MAC=$(getprop persist.titan.wifi.mac)
if [ -n "$SAVED_MAC" ]; then
    ip link set wlan0 address "$SAVED_MAC" 2>/dev/null
fi
log_i "Network interface renamed to wlan0"

# ─── RASP: hide root/debug artifacts ─────────────────────────────────
for SU_PATH in /system/bin/su /system/xbin/su /sbin/su /su/bin/su; do
    if [ -e "$SU_PATH" ]; then
        chmod 000 "$SU_PATH" 2>/dev/null
        mount -o bind /dev/null "$SU_PATH" 2>/dev/null
    fi
done

for HIDE_PATH in /sbin/.magisk /data/adb/magisk /cache/.disable_magisk \
                  /dev/goldfish_pipe /dev/qemu_pipe /dev/socket/qemud \
                  /system/lib/libc_malloc_debug_qemu.so; do
    mount -o bind /dev/null "$HIDE_PATH" 2>/dev/null
done

# Block Frida ports
iptables -C INPUT -p tcp --dport 27042 -j DROP 2>/dev/null || \
    iptables -A INPUT -p tcp --dport 27042 -j DROP 2>/dev/null
iptables -C INPUT -p tcp --dport 27043 -j DROP 2>/dev/null || \
    iptables -A INPUT -p tcp --dport 27043 -j DROP 2>/dev/null
log_i "RASP hardening applied"

# ─── Settings hardening ──────────────────────────────────────────────
settings put global adb_enabled 0
settings put global development_settings_enabled 0
settings put secure mock_location 0
settings put global captive_portal_detection_enabled 0
settings put system time_12_24 12
log_i "Settings hardened"

# ─── Battery simulation ──────────────────────────────────────────────
BATT_LEVEL=$(( RANDOM % 26 + 62 ))  # 62-87%
dumpsys battery set level $BATT_LEVEL 2>/dev/null
dumpsys battery set status 3 2>/dev/null  # not charging
dumpsys battery set ac 0 2>/dev/null
dumpsys battery set usb 0 2>/dev/null
log_i "Battery set to ${BATT_LEVEL}%"

log_i "Titan boot patch complete — all vectors applied"
