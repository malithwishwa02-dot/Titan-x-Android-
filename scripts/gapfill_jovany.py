#!/usr/bin/env python3
"""Gap-fill: re-inject Chrome data, Google Pay wallet, Google account after device restart."""
import json, logging, os, sys, time, subprocess
sys.path.insert(0, '/opt/titan-v11.3-device/core')
sys.path.insert(0, '/opt/titan-v11.3-device/server')
sys.path.insert(0, '/root/titan-v11-release/core')
os.environ['TITAN_DATA'] = '/opt/titan/data'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('gapfill')

ADB_TARGET = '127.0.0.1:5555'
PROFILE_ID = 'TITAN-C6D545F0'

def adb_shell(cmd, timeout=15):
    try:
        r = subprocess.run(f'adb -s {ADB_TARGET} shell "{cmd}"', shell=True,
                          capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ''

# Ensure root + stop apps
subprocess.run(f'adb -s {ADB_TARGET} root', shell=True, capture_output=True, timeout=10)
time.sleep(2)
for pkg in ['com.android.chrome', 'com.google.android.gms',
            'com.android.vending', 'com.google.android.apps.walletnfcrel']:
    adb_shell(f'am force-stop {pkg}')
time.sleep(1)

# Load profile
from pathlib import Path
pf = Path('/opt/titan/data/profiles') / (PROFILE_ID + '.json')
profile = json.loads(pf.read_text())
logger.info('Loaded profile: %s', profile.get('persona_name', ''))

# ── 1. Chrome cookies ──
logger.info('=== Injecting Chrome cookies ===')
from profile_injector import ProfileInjector
injector = ProfileInjector(adb_target=ADB_TARGET)
injector._inject_cookies(profile.get('cookies', []))
logger.info('Cookies done')

# ── 2. Chrome history ──
logger.info('=== Injecting Chrome history ===')
injector._inject_history(profile.get('history', []))
logger.info('History done')

# ── 3. Chrome autofill ──
logger.info('=== Injecting Chrome autofill ===')
injector._inject_autofill(profile.get('autofill', {}))
logger.info('Autofill done')

# ── 4. Google Account ──
logger.info('=== Injecting Google Account ===')
from google_account_injector import GoogleAccountInjector
gai = GoogleAccountInjector(adb_target=ADB_TARGET)
acct = gai.inject_account(email='ranpatidewage62@gmail.com', display_name='Jovany Owens')
logger.info('Google Account: %d/8 targets', acct.success_count)

# ── 5. Wallet provisioning (Google Pay + Play Store + Chrome autofill CC) ──
logger.info('=== Wallet Provisioning ===')
from wallet_provisioner import WalletProvisioner
prov = WalletProvisioner(adb_target=ADB_TARGET)
wallet = prov.provision_card(
    card_number='4638512320340405',
    exp_month=8, exp_year=2029,
    cardholder='Jovany Owens', cvv='051',
    persona_email='ranpatidewage62@gmail.com',
    persona_name='Jovany Owens',
)
logger.info('Wallet: %d/3 targets', wallet.success_count)
logger.info('  Google Pay: %s', 'OK' if wallet.google_pay_ok else 'FAIL')
logger.info('  Play Store: %s', 'OK' if wallet.play_store_ok else 'FAIL')
logger.info('  Chrome Autofill: %s', 'OK' if wallet.chrome_autofill_ok else 'FAIL')
if wallet.errors:
    for e in wallet.errors:
        logger.warning('  Error: %s', e)

# ── 6. App data (SharedPrefs for social apps) ──
logger.info('=== Injecting App Data ===')
injector._inject_app_data(profile)
logger.info('App data done')

# ── 7. Play purchases ──
logger.info('=== Injecting Play Purchases ===')
injector._inject_play_purchases(profile)
logger.info('Play purchases done')

# ── 8. Trigger wallet app installs ──
logger.info('=== Triggering Wallet App Installs ===')
WALLET_APPS = [
    ('com.google.android.apps.walletnfcrel', 'Google Pay'),
    ('com.squareup.cash', 'Cash App'),
    ('com.venmo', 'Venmo'),
    ('com.paypal.android.p2pmobile', 'PayPal'),
    ('com.zellepay.zelle', 'Zelle'),
    ('com.chase.sig.android', 'Chase'),
    ('com.wf.wellsfargomobile', 'Wells Fargo'),
    ('com.onedebit.chime', 'Chime'),
    ('com.bankofamerica.cashpromobile', 'Bank of America'),
    ('com.sofi.mobile', 'SoFi'),
    ('com.klarna.android', 'Klarna'),
    ('com.afterpay.caportal', 'Afterpay'),
    ('com.affirm.central', 'Affirm'),
    ('com.quadpay.quadpay', 'Zip'),
    ('com.coinbase.android', 'Coinbase'),
    ('com.binance.dev', 'Binance'),
    ('com.transferwise.android', 'Wise'),
]

for pkg, name in WALLET_APPS:
    check = adb_shell(f'pm path {pkg}')
    if check and 'package:' in check:
        logger.info('  [INSTALLED] %s', name)
    else:
        adb_shell(f"am start -a android.intent.action.VIEW -d 'market://details?id={pkg}' com.android.vending")
        logger.info('  [TRIGGER]   %s → Play Store', name)
        time.sleep(2)

# ── 9. Final verification ──
logger.info('=== FINAL VERIFICATION ===')
checks = {}
checks['google_account'] = bool(adb_shell('ls /data/system_ce/0/accounts_ce.db 2>/dev/null'))
checks['google_pay'] = bool(adb_shell('ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null'))
checks['chrome_cookies'] = bool(adb_shell('ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null'))
checks['chrome_history'] = bool(adb_shell('ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null'))
checks['chrome_autofill'] = bool(adb_shell("ls '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null"))
checks['chrome_signin'] = bool(adb_shell('ls /data/data/com.android.chrome/app_chrome/Default/Preferences 2>/dev/null'))

sms_out = adb_shell('content query --uri content://sms --projection _id 2>/dev/null | wc -l')
try: checks['sms'] = int(sms_out.strip())
except: checks['sms'] = 0

calls_out = adb_shell('content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l')
try: checks['calls'] = int(calls_out.strip())
except: checks['calls'] = 0

contacts_out = adb_shell('content query --uri content://contacts/phones --projection _id 2>/dev/null | wc -l')
try: checks['contacts'] = int(contacts_out.strip())
except: checks['contacts'] = 0

gallery_out = adb_shell('ls /sdcard/DCIM/Camera/*.jpg 2>/dev/null | wc -l')
try: checks['gallery'] = int(gallery_out.strip())
except: checks['gallery'] = 0

play_lib = bool(adb_shell('ls /data/data/com.android.vending/databases/library.db 2>/dev/null'))
checks['play_library'] = play_lib

app_prefs = bool(adb_shell('ls /data/data/com.instagram.android/shared_prefs/ 2>/dev/null'))
checks['app_data'] = app_prefs

# Score
score = 0
if checks['google_account']: score += 15
if checks['contacts'] >= 5: score += 8
if checks['chrome_cookies']: score += 8
if checks['chrome_history']: score += 8
if checks['gallery'] >= 3: score += 5
if checks['google_pay']: score += 12
if checks['sms'] >= 5: score += 7
if checks['calls'] >= 10: score += 7
if checks['app_data']: score += 8
if checks['chrome_signin']: score += 5
if checks['chrome_autofill']: score += 5
if checks['play_library']: score += 8
# wifi
wifi = bool(adb_shell('ls /data/misc/wifi/WifiConfigStore.xml 2>/dev/null'))
if wifi: score += 4

grade = 'A+' if score >= 90 else 'A' if score >= 80 else 'B' if score >= 65 else 'C' if score >= 50 else 'D'

logger.info('')
for k, v in checks.items():
    if isinstance(v, bool):
        sym = 'OK' if v else '--'
    else:
        sym = 'OK' if v > 0 else '--'
    logger.info('  [%s] %s: %s', sym, k, v)
logger.info('  [%s] wifi: %s', 'OK' if wifi else '--', wifi)

logger.info('')
logger.info('TRUST SCORE: %d/100 (%s)', score, grade)
logger.info('Wallet: %d/3, Google Account: %d/8', wallet.success_count, acct.success_count)
logger.info('DONE')
