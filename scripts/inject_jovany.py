#!/usr/bin/env python3
"""Inject Jovany Owens 500d profile + CC into dev-us1 device."""
import json, logging, os, sys, time, subprocess
sys.path.insert(0, '/opt/titan-v11.3-device/core')
sys.path.insert(0, '/opt/titan-v11.3-device/server')
sys.path.insert(0, '/root/titan-v11-release/core')
os.environ['TITAN_DATA'] = '/opt/titan/data'

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger('provision')

PROFILE_ID = 'TITAN-C6D545F0'
ADB_TARGET = '127.0.0.1:5555'
CARD_DATA = {
    'number': '4638512320340405',
    'exp_month': 8,
    'exp_year': 2029,
    'cvv': '051',
    'cardholder': 'Jovany Owens',
}

from pathlib import Path

# ── Load forged profile ──
pf = Path('/opt/titan/data/profiles') / (PROFILE_ID + '.json')
profile = json.loads(pf.read_text())
logger.info('Loaded profile: %s (%d days old)', profile.get('persona_name', ''), profile.get('age_days', 0))

# Gallery paths
gallery_dir = Path('/opt/titan/data/forge_gallery')
if gallery_dir.exists():
    jpgs = sorted(gallery_dir.glob('*.jpg'))[:25]
    profile['gallery_paths'] = [str(p) for p in jpgs]
    logger.info('Gallery: %d photos', len(jpgs))

# ── Step 1: Inject full profile + CC ──
logger.info('=' * 60)
logger.info('INJECTING PROFILE + CC INTO DEVICE')
logger.info('=' * 60)

from profile_injector import ProfileInjector
injector = ProfileInjector(adb_target=ADB_TARGET)
result = injector.inject_full_profile(profile, card_data=CARD_DATA)
logger.info('Profile injection trust score: %d/100', result.trust_score)

# ── Step 2: Extra wallet provisioning pass ──
logger.info('=' * 60)
logger.info('WALLET PROVISIONING (explicit pass)')
logger.info('=' * 60)

from wallet_provisioner import WalletProvisioner
prov = WalletProvisioner(adb_target=ADB_TARGET)
wallet = prov.provision_card(
    card_number=CARD_DATA['number'],
    exp_month=CARD_DATA['exp_month'],
    exp_year=CARD_DATA['exp_year'],
    cardholder=CARD_DATA['cardholder'],
    cvv=CARD_DATA['cvv'],
    persona_email='ranpatidewage62@gmail.com',
    persona_name='Jovany Owens',
)
logger.info('Wallet: %d/3 targets', wallet.success_count)
logger.info('  Google Pay: %s', 'OK' if wallet.google_pay_ok else 'FAIL')
logger.info('  Play Store: %s', 'OK' if wallet.play_store_ok else 'FAIL')
logger.info('  Chrome Autofill: %s', 'OK' if wallet.chrome_autofill_ok else 'FAIL')

# ── Step 3: Google Account injection ──
logger.info('=' * 60)
logger.info('GOOGLE ACCOUNT INJECTION')
logger.info('=' * 60)

from google_account_injector import GoogleAccountInjector
gai = GoogleAccountInjector(adb_target=ADB_TARGET)
acct = gai.inject_account(email='ranpatidewage62@gmail.com', display_name='Jovany Owens')
logger.info('Google Account: %d/8 targets', acct.success_count)

# ── Step 4: Trigger Play Store app installs ──
logger.info('=' * 60)
logger.info('TRIGGERING WALLET APP INSTALLS')
logger.info('=' * 60)

def adb_shell(cmd):
    try:
        r = subprocess.run(f'adb -s {ADB_TARGET} shell "{cmd}"', shell=True,
                          capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except:
        return ''

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
        logger.info('  [INSTALLED] %s (%s)', name, pkg)
    else:
        adb_shell(f"am start -a android.intent.action.VIEW -d 'market://details?id={pkg}' com.android.vending")
        logger.info('  [TRIGGER]   %s (%s) → Play Store opened', name, pkg)
        time.sleep(2)

# ── Step 5: Verify final state ──
logger.info('=' * 60)
logger.info('DEVICE VERIFICATION')
logger.info('=' * 60)

checks = {}
checks['model'] = adb_shell('getprop ro.product.model')
checks['google_acct'] = bool(adb_shell('ls /data/system_ce/0/accounts_ce.db 2>/dev/null'))
checks['tapandpay'] = bool(adb_shell('ls /data/data/com.google.android.apps.walletnfcrel/databases/tapandpay.db 2>/dev/null'))
checks['chrome_autofill'] = bool(adb_shell("ls '/data/data/com.android.chrome/app_chrome/Default/Web Data' 2>/dev/null"))
checks['chrome_cookies'] = bool(adb_shell('ls /data/data/com.android.chrome/app_chrome/Default/Cookies 2>/dev/null'))
checks['chrome_history'] = bool(adb_shell('ls /data/data/com.android.chrome/app_chrome/Default/History 2>/dev/null'))

sms_out = adb_shell('content query --uri content://sms --projection _id 2>/dev/null | wc -l')
try: checks['sms_count'] = int(sms_out.strip())
except: checks['sms_count'] = 0

calls_out = adb_shell('content query --uri content://call_log/calls --projection _id 2>/dev/null | wc -l')
try: checks['call_count'] = int(calls_out.strip())
except: checks['call_count'] = 0

contacts_out = adb_shell('content query --uri content://contacts/phones --projection _id 2>/dev/null | wc -l')
try: checks['contacts_count'] = int(contacts_out.strip())
except: checks['contacts_count'] = 0

score = 0
if checks['google_acct']: score += 15
if checks['contacts_count'] >= 5: score += 8
if checks['chrome_cookies']: score += 8
if checks['chrome_history']: score += 8
if checks['tapandpay']: score += 12
if checks['chrome_autofill']: score += 5
if checks['sms_count'] >= 5: score += 7
if checks['call_count'] >= 10: score += 7

grade = 'A+' if score >= 90 else 'A' if score >= 80 else 'B' if score >= 65 else 'C'

for k, v in checks.items():
    sym = 'OK' if (v if isinstance(v, bool) else v > 0) else '--'
    logger.info('  [%s] %s: %s', sym, k, v)

logger.info('')
logger.info('FINAL TRUST SCORE: %d/100 (%s)', score, grade)
logger.info('Profile: %s, Wallet: %d/3, Google Account: %d/8', PROFILE_ID, wallet.success_count, acct.success_count)
