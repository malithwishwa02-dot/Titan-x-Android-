#!/usr/bin/env python3
"""Fix Chrome autofill_profiles gap — inject Jovany Owens address."""
import sqlite3, subprocess, tempfile, os, uuid, time, random

ADB = "127.0.0.1:5555"

def adb_cmd(args):
    r = subprocess.run(["adb", "-s", ADB] + args, capture_output=True, text=True, timeout=15)
    return r.returncode == 0, r.stdout.strip()

webdata_remote = "/data/data/com.android.chrome/app_chrome/Default/Web Data"
tmp = tempfile.mktemp(suffix=".db")
adb_cmd(["pull", webdata_remote, tmp])

conn = sqlite3.connect(tmp)
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS autofill_profiles (
    guid TEXT NOT NULL, company_name TEXT DEFAULT '',
    street_address TEXT DEFAULT '', dependent_locality TEXT DEFAULT '',
    city TEXT DEFAULT '', state TEXT DEFAULT '', zipcode TEXT DEFAULT '',
    sorting_code TEXT DEFAULT '', country_code TEXT DEFAULT '',
    date_modified INTEGER NOT NULL DEFAULT 0, origin TEXT DEFAULT '',
    language_code TEXT DEFAULT '', use_count INTEGER NOT NULL DEFAULT 0,
    use_date INTEGER NOT NULL DEFAULT 0
)""")
c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_names (
    guid TEXT NOT NULL, first_name TEXT DEFAULT '', middle_name TEXT DEFAULT '',
    last_name TEXT DEFAULT '', full_name TEXT DEFAULT ''
)""")
c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_emails (
    guid TEXT NOT NULL, email TEXT DEFAULT ''
)""")
c.execute("""CREATE TABLE IF NOT EXISTS autofill_profile_phones (
    guid TEXT NOT NULL, number TEXT DEFAULT ''
)""")

now_s = int(time.time())
profile_guid = str(uuid.uuid4())
date_mod = now_s - random.randint(30 * 86400, 90 * 86400)
use_count = random.randint(8, 25)
last_used = now_s - random.randint(0, 5 * 86400)

c.execute(
    "INSERT INTO autofill_profiles "
    "(guid, company_name, street_address, city, state, zipcode, country_code, "
    "date_modified, origin, language_code, use_count, use_date) "
    "VALUES (?, '', ?, ?, ?, ?, 'US', ?, 'https://www.amazon.com', 'en-US', ?, ?)",
    (profile_guid, "1866 W 11th St", "Los Angeles", "CA", "90006",
     date_mod, use_count, last_used),
)
c.execute(
    "INSERT INTO autofill_profile_names (guid, first_name, last_name, full_name) VALUES (?, ?, ?, ?)",
    (profile_guid, "Jovany", "Owens", "Jovany Owens"),
)
c.execute(
    "INSERT INTO autofill_profile_emails (guid, email) VALUES (?, ?)",
    (profile_guid, "ranpatidewage62@gmail.com"),
)
c.execute(
    "INSERT INTO autofill_profile_phones (guid, number) VALUES (?, ?)",
    (profile_guid, "+17078361915"),
)
conn.commit()

count = c.execute("SELECT COUNT(*) FROM autofill_profiles").fetchone()[0]
names = c.execute("SELECT full_name FROM autofill_profile_names").fetchall()
conn.close()

subprocess.run(["adb", "-s", ADB, "shell", "am force-stop com.android.chrome"],
               capture_output=True, timeout=10)
ok, _ = adb_cmd(["push", tmp, webdata_remote])
if ok:
    subprocess.run(["adb", "-s", ADB, "shell",
        "chown $(stat -c %U /data/data/com.android.chrome):$(stat -c %U /data/data/com.android.chrome) "
        "'/data/data/com.android.chrome/app_chrome/Default/Web Data'; "
        "chmod 660 '/data/data/com.android.chrome/app_chrome/Default/Web Data'"],
        capture_output=True, text=True, timeout=10)
    print(f"OK: autofill_profiles={count}, names={names}")
else:
    print("FAIL: could not push Web Data")
os.unlink(tmp)
