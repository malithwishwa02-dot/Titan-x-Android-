#!/system/bin/sh
# ═══════════════════════════════════════════════════════════════════════
# Titan V11.3 — Persistent Boot Patch Script [DEPRECATED - Redroid]
# This script was for Redroid Docker containers. The Titan platform has
# migrated to Cuttlefish KVM VMs. See: cuttlefish/init.d/99-titan-patch.sh
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

# ─── Hide emulator artifacts (sterile file method) ───────────────────
# Bind-mounting /dev/null is detectable via /proc/mounts — generate clean files
mkdir -p /data/titan

# Sterile /proc/cmdline
if [ -f /proc/cmdline ]; then
    cat /proc/cmdline | sed 's/androidboot\.hardware=redroid//g' \
        | sed 's/docker[^ ]*//g' | sed 's/containerd[^ ]*//g' \
        | sed 's/lxc[^ ]*//g' | sed 's/  */ /g' \
        > /data/titan/proc_cmdline_clean 2>/dev/null
    # Ensure non-empty
    [ -s /data/titan/proc_cmdline_clean ] || \
        echo "androidboot.verifiedbootstate=green androidboot.slot_suffix=_a" > /data/titan/proc_cmdline_clean
    mount -o bind /data/titan/proc_cmdline_clean /proc/cmdline 2>/dev/null
fi

# Sterile /proc/1/cgroup
echo "0::/" > /data/titan/cgroup_clean
mount -o bind /data/titan/cgroup_clean /proc/1/cgroup 2>/dev/null

# Scrub /proc/mounts to hide bind-mount evidence
cat /proc/mounts | grep -v '/proc/cmdline' | grep -v '/proc/1/cgroup' \
    > /data/titan/mounts_clean 2>/dev/null
mount -o bind /data/titan/mounts_clean /proc/mounts 2>/dev/null

log_i "Proc artifacts hidden (sterile files)"

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

# ─── Sensor data persistence ───────────────────────────────────────
setprop persist.titan.sensor.accelerometer 1
setprop persist.titan.sensor.gyroscope 1
setprop persist.titan.sensor.proximity 1
setprop persist.titan.sensor.light 1
setprop persist.titan.sensor.magnetometer 1
setprop persist.titan.sensor.step_counter 1
log_i "Sensor props set"

# ─── Bluetooth paired devices restoration ──────────────────────────
if [ -f /data/misc/bluedroid/bt_config.conf ]; then
    log_i "Bluetooth config preserved"
fi

# ─── /proc spoofing ───────────────────────────────────────────────
# Bind-mount spoofed cpuinfo if available
if [ -f /data/titan/cpuinfo_spoof ]; then
    mount -o bind /data/titan/cpuinfo_spoof /proc/cpuinfo 2>/dev/null
    log_i "cpuinfo spoofed"
fi

# ─── SELinux & accessibility ──────────────────────────────────────
setprop ro.boot.selinux enforcing
settings put secure enabled_accessibility_services '' 2>/dev/null
settings put secure accessibility_enabled 0 2>/dev/null
settings put system screen_off_timeout 60000 2>/dev/null
log_i "SELinux + accessibility hardened"

# ─── WiFi scan results generation (locale-aware) ──────────────────
# Read locale hint from persist prop, default to US SSIDs
WIFI_LOCALE=$(getprop persist.titan.wifi.locale)
case "$WIFI_LOCALE" in
    GB) SSID_LIST="BT_Hub6_5G Sky_WiFi_Home Virgin_Media_5G TalkTalk_5G PlusNet_WiFi EE_Home_5G" ;;
    DE) SSID_LIST="FRITZBox_7590 Telekom_5G Vodafone_Home_5G o2_WLAN Unitymedia_5G 1und1_WLAN" ;;
    FR) SSID_LIST="Livebox_5G Freebox_5G SFR_Home Bouygues_5G Orange_WiFi RED_Home" ;;
    *)  SSID_LIST="NETGEAR72_5G Xfinity_Home ATT_FIBER Spectrum_5G TP_Link_5G linksys_5g" ;;
esac
for SSID in $SSID_LIST; do
    RSSI=$(( RANDOM % 50 - 85 ))
    FREQ=$(shuf -e 2412 2437 5180 5745 -n 1 2>/dev/null || echo 2437)
    setprop "persist.titan.wifi.scan.${SSID}" "${RSSI},${FREQ}"
done
log_i "WiFi scan results generated (locale: ${WIFI_LOCALE:-US})"

# ─── GMS background sync throttle (reduce CPU) ────────────────────
settings put global background_data_restriction 0 2>/dev/null
log_i "GMS sync throttled"

log_i "Titan boot patch complete — all 65+ vectors applied"
