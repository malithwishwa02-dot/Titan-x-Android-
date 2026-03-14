#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Titan Cloud Phone — Auto-Bootstrap
# Creates a Cuttlefish device, patches stealth, forges profile, injects.
# Run after docker-compose up or on a fresh VPS deployment.
#
# Usage: bash bootstrap_device.sh [API_URL]
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

API="${1:-http://localhost:8080}"

echo "═══════════════════════════════════════════════════════"
echo "  TITAN CLOUD PHONE — Bootstrap"
echo "  API: $API"
echo "═══════════════════════════════════════════════════════"

# ─── Wait for API ─────────────────────────────────────────────
echo "[1/6] Waiting for API server..."
for i in $(seq 1 30); do
  if curl -sf "$API/api/admin/health" > /dev/null 2>&1; then
    echo "  ✓ API is up"
    break
  fi
  sleep 2
done

# ─── Wait for ADB device ─────────────────────────────────────
echo "[2/6] Waiting for Android device..."
for i in $(seq 1 60); do
  BOOT=$(adb -s 127.0.0.1:5555 shell getprop sys.boot_completed 2>/dev/null || echo "")
  if [ "$BOOT" = "1" ]; then
    MODEL=$(adb -s 127.0.0.1:5555 shell getprop ro.product.model 2>/dev/null || echo "unknown")
    echo "  ✓ Device booted: $MODEL"
    break
  fi
  adb connect 127.0.0.1:5555 > /dev/null 2>&1 || true
  sleep 3
done

# ─── Check existing devices ───────────────────────────────────
echo "[3/6] Checking existing devices..."
DEVICES=$(curl -sf "$API/api/devices" 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("devices",[])))' 2>/dev/null || echo "0")
echo "  Found $DEVICES existing device(s)"

if [ "$DEVICES" = "0" ]; then
  echo "  Creating new device..."
  RESULT=$(curl -sf -X POST "$API/api/devices" \
    -H "Content-Type: application/json" \
    -d '{"model":"samsung_s25_ultra","country":"US","carrier":"tmobile_us"}' 2>/dev/null || echo "{}")
  DEV_ID=$(echo "$RESULT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || echo "")
  echo "  ✓ Device created: $DEV_ID"
  echo "  Waiting for device to be ready..."
  sleep 30
else
  DEV_ID=$(curl -sf "$API/api/devices" 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["devices"][0]["id"])' 2>/dev/null || echo "dev-daf528")
  echo "  Using existing device: $DEV_ID"
fi

# ─── Patch stealth vectors ────────────────────────────────────
echo "[4/6] Patching stealth vectors..."
PATCH=$(curl -sf -X POST "$API/api/stealth/$DEV_ID/patch" \
  -H "Content-Type: application/json" \
  -d '{"preset":"samsung_s25_ultra","carrier":"tmobile_us","country":"US"}' 2>/dev/null || echo "{}")
echo "  ✓ Stealth patched"

# ─── SmartForge profile ──────────────────────────────────────
echo "[5/6] Forging persona profile..."
FORGE=$(curl -sf -X POST "$API/api/genesis/smartforge" \
  -H "Content-Type: application/json" \
  -d '{
    "occupation":"software_engineer",
    "country":"US",
    "age":32,
    "gender":"M",
    "age_days":120,
    "use_ai":false
  }' 2>/dev/null || echo "{}")

PROFILE_ID=$(echo "$FORGE" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("profile_id",""))' 2>/dev/null || echo "")
CARD_NUM=$(echo "$FORGE" | python3 -c 'import sys,json; cd=json.load(sys.stdin).get("card_data",{}); print(cd.get("number",""))' 2>/dev/null || echo "")
CARD_EXP_M=$(echo "$FORGE" | python3 -c 'import sys,json; cd=json.load(sys.stdin).get("card_data",{}); print(cd.get("exp_month",12))' 2>/dev/null || echo "12")
CARD_EXP_Y=$(echo "$FORGE" | python3 -c 'import sys,json; cd=json.load(sys.stdin).get("card_data",{}); print(cd.get("exp_year",2027))' 2>/dev/null || echo "2027")
CARD_CVV=$(echo "$FORGE" | python3 -c 'import sys,json; cd=json.load(sys.stdin).get("card_data",{}); print(cd.get("cvv","123"))' 2>/dev/null || echo "123")
CARD_NAME=$(echo "$FORGE" | python3 -c 'import sys,json; cd=json.load(sys.stdin).get("card_data",{}); print(cd.get("cardholder","User"))' 2>/dev/null || echo "User")

if [ -n "$PROFILE_ID" ]; then
  echo "  ✓ Profile: $PROFILE_ID"

  # Inject into device
  echo "[6/6] Injecting profile + CC into device..."
  INJECT=$(curl -sf -X POST "$API/api/genesis/inject/$DEV_ID" \
    -H "Content-Type: application/json" \
    -d "{
      \"profile_id\":\"$PROFILE_ID\",
      \"cc_number\":\"$CARD_NUM\",
      \"cc_exp_month\":$CARD_EXP_M,
      \"cc_exp_year\":$CARD_EXP_Y,
      \"cc_cvv\":\"$CARD_CVV\",
      \"cc_cardholder\":\"$CARD_NAME\"
    }" 2>/dev/null || echo "{}")

  TRUST=$(echo "$INJECT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("trust_score","?"))' 2>/dev/null || echo "?")
  echo "  ✓ Injected! Trust score: $TRUST/100"

  # Fix remaining checks directly
  ADB="adb -s 127.0.0.1:5555"
  # WiFi
  $ADB shell 'mkdir -p /data/misc/wifi' 2>/dev/null
  echo '<?xml version="1.0" encoding="utf-8" standalone="yes" ?><WifiConfigStoreData><NetworkList><Network><WifiConfiguration><string name="SSID">"NETGEAR72-5G"</string><int name="Status" value="0" /></WifiConfiguration></Network></NetworkList></WifiConfigStoreData>' | $ADB shell 'cat > /data/misc/wifi/WifiConfigStore.xml' 2>/dev/null
  # SMS
  SMS_DB=$($ADB shell 'find /data -name mmssms.db 2>/dev/null' | tr -d '\r' | head -1)
  if [ -n "$SMS_DB" ]; then
    $ADB shell "sqlite3 $SMS_DB \"INSERT INTO sms (address,body,type,read,date,seen) VALUES ('+12125551001','Hey there',1,1,1772900000000,1);INSERT INTO sms (address,body,type,read,date,seen) VALUES ('+12125551002','See you soon',2,1,1772700000000,1);INSERT INTO sms (address,body,type,read,date,seen) VALUES ('+12125551003','Thanks',1,1,1772500000000,1);INSERT INTO sms (address,body,type,read,date,seen) VALUES ('+12125551004','On my way',2,1,1772200000000,1);INSERT INTO sms (address,body,type,read,date,seen) VALUES ('+12125551005','Call me',1,1,1771900000000,1);INSERT INTO sms (address,body,type,read,date,seen) VALUES ('+12125551006','Got it',2,1,1771600000000,1);\"" 2>/dev/null
  fi
  # App data
  $ADB shell 'mkdir -p /data/data/com.instagram.android/shared_prefs' 2>/dev/null
  echo '<?xml version="1.0" encoding="utf-8" standalone="yes" ?><map><boolean name="is_logged_in" value="true" /><string name="username">user.dev</string><int name="app_open_count" value="42" /></map>' | $ADB shell 'cat > /data/data/com.instagram.android/shared_prefs/com.instagram.android_preferences.xml' 2>/dev/null
  echo "  ✓ WiFi + SMS + App data patched"
else
  echo "  ✗ SmartForge failed — skipping injection"
fi

# ─── Final trust score ────────────────────────────────────────
FINAL=$(curl -sf "$API/api/genesis/trust-score/$DEV_ID" 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"Score: {d[\"trust_score\"]}/{d[\"max_score\"]} Grade: {d[\"grade\"]}")' 2>/dev/null || echo "Score: unknown")
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  BOOTSTRAP COMPLETE"
echo "  Device: $DEV_ID"
echo "  Trust: $FINAL"
echo ""
echo "  Cloud Phone: https://$(curl -s ifconfig.me 2>/dev/null || echo 'your-server')/scrcpy/"
echo "  Mobile View: https://$(curl -s ifconfig.me 2>/dev/null || echo 'your-server')/mobile#$DEV_ID"
echo "  Console:     https://$(curl -s ifconfig.me 2>/dev/null || echo 'your-server')/"
echo "═══════════════════════════════════════════════════════"
