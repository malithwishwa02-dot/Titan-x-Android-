#!/usr/bin/env python3
"""Direct SQLite injection of SMS into Redroid mmssms.db."""
import os
import sqlite3
import subprocess
import tempfile
import time

ADB_TARGET = "127.0.0.1:5555"
SMS_DB = "/data/user_de/0/com.android.providers.telephony/databases/mmssms.db"

def adb_cmd(args, timeout=15):
    r = subprocess.run(
        ["adb", "-s", ADB_TARGET] + args,
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode == 0, r.stdout.strip()

def adb_shell(cmd, timeout=15):
    return adb_cmd(["shell", cmd], timeout)

def adb_pull(remote, local):
    return adb_cmd(["pull", remote, local])

def adb_push(local, remote):
    return adb_cmd(["push", local, remote])

# Stop telephony provider
adb_shell("am force-stop com.android.providers.telephony")
time.sleep(1)

# Pull existing DB
tmp = tempfile.mktemp(suffix=".db")
ok, out = adb_pull(SMS_DB, tmp)
if not ok:
    print(f"Failed to pull SMS DB: {out}")
    # Create fresh DB
    conn = sqlite3.connect(tmp)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS sms (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER DEFAULT 0,
        address TEXT,
        person INTEGER DEFAULT 0,
        date INTEGER DEFAULT 0,
        date_sent INTEGER DEFAULT 0,
        protocol INTEGER DEFAULT 0,
        read INTEGER DEFAULT 0,
        status INTEGER DEFAULT -1,
        type INTEGER DEFAULT 0,
        reply_path_present INTEGER DEFAULT 0,
        subject TEXT,
        body TEXT,
        service_center TEXT,
        locked INTEGER DEFAULT 0,
        sub_id INTEGER DEFAULT -1,
        error_code INTEGER DEFAULT 0,
        creator TEXT DEFAULT 'com.android.messaging',
        seen INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS threads (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        date INTEGER DEFAULT 0,
        message_count INTEGER DEFAULT 0,
        recipient_ids TEXT,
        snippet TEXT,
        snippet_cs INTEGER DEFAULT 0,
        read INTEGER DEFAULT 1,
        archived INTEGER DEFAULT 0,
        type INTEGER DEFAULT 0,
        error INTEGER DEFAULT 0,
        has_attachment INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS canonical_addresses (
        _id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT
    )""")
    conn.commit()
    conn.close()
else:
    print(f"Pulled SMS DB: {out}")

conn = sqlite3.connect(tmp)
c = conn.cursor()

now_ms = int(time.time() * 1000)

# Create canonical addresses and threads
addresses = {
    "+12133456789": 1,
    "+13234567890": 2,
    "33789": 3,
    "72000": 4,
    "+17078361999": 5,
    "+12133459876": 6,
}

for addr, addr_id in addresses.items():
    c.execute("INSERT OR IGNORE INTO canonical_addresses (_id, address) VALUES (?, ?)",
              (addr_id, addr))

# Create threads
threads = {
    1: ("+12133456789", "Yeah that last quarter was insane"),
    2: ("+13234567890", "Your appointment is tomorrow at 10 30 AM"),
    3: ("33789", "Transaction of 47.82 on card ending 0405 approved"),
    4: ("72000", "Your verification code is 847291"),
    5: ("+17078361999", "Yes I will be there around 2pm"),
    6: ("+12133459876", "Want to grab dinner at that new place on Main"),
}

for tid, (addr, snippet) in threads.items():
    c.execute("""INSERT OR REPLACE INTO threads
        (_id, date, message_count, recipient_ids, snippet, read, type)
        VALUES (?, ?, ?, ?, ?, 1, 0)""",
        (tid, now_ms - tid * 86400000, 3, str(addresses[addr]), snippet))

# SMS messages
messages = [
    # Friend chat
    (1, "+12133456789", "Hey are you free tonight", 1, now_ms - 86400000),
    (1, "+12133456789", "Yeah what time", 2, now_ms - 85800000),
    (1, "+12133456789", "Around 7 at the usual spot", 1, now_ms - 85200000),
    (1, "+12133456789", "Bro did you see the game last night", 1, now_ms - 604800000),
    (1, "+12133456789", "Yeah that last quarter was insane", 2, now_ms - 604200000),
    # Appointment
    (2, "+13234567890", "Your appointment is tomorrow at 10 30 AM", 1, now_ms - 172800000),
    (2, "+13234567890", "Thank you I will be there", 2, now_ms - 172200000),
    # Chase bank
    (3, "33789", "Chase Visa ending 0405 added to Google Pay", 1, now_ms - 259200000),
    (3, "33789", "Transaction of 47.82 on card ending 0405 approved", 1, now_ms - 345600000),
    (3, "33789", "Transaction of 12.99 on card ending 0405 at SPOTIFY approved", 1, now_ms - 691200000),
    # OTP
    (4, "72000", "Your verification code is 847291", 1, now_ms - 432000000),
    (4, "72000", "Your code is 529163 expires in 10 minutes", 1, now_ms - 864000000),
    # Family
    (5, "+17078361999", "Hi sweetie are you coming for dinner Sunday", 1, now_ms - 518400000),
    (5, "+17078361999", "Yes I will be there around 2pm", 2, now_ms - 517800000),
    (5, "+17078361999", "Love you", 1, now_ms - 517200000),
    # Another friend
    (6, "+12133459876", "Want to grab dinner at that new place on Main", 1, now_ms - 1209600000),
    (6, "+12133459876", "Sure 7pm works for me", 2, now_ms - 1209000000),
]

for tid, addr, body, stype, ts in messages:
    c.execute("""INSERT INTO sms
        (thread_id, address, date, date_sent, read, type, body, seen, creator)
        VALUES (?, ?, ?, ?, 1, ?, ?, 1, 'com.android.messaging')""",
        (tid, addr, ts, ts, stype, body))

conn.commit()

# Verify
c.execute("SELECT COUNT(*) FROM sms")
sms_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM threads")
thread_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM canonical_addresses")
addr_count = c.fetchone()[0]
conn.close()

print(f"SMS: {sms_count}, Threads: {thread_count}, Addresses: {addr_count}")

# Push back
ok, out = adb_push(tmp, SMS_DB)
if ok:
    # Fix ownership
    adb_shell("chown radio:radio " + SMS_DB)
    adb_shell("chmod 660 " + SMS_DB)
    # Also fix journal if exists
    adb_shell("chown radio:radio " + SMS_DB + "-journal 2>/dev/null")
    print("SMS DB pushed and ownership fixed")
else:
    print(f"Push failed: {out}")

os.unlink(tmp)

# Verify via content provider after restart
adb_shell("am force-stop com.android.providers.telephony")
time.sleep(1)
ok, count = adb_shell("content query --uri content://sms --projection _id | wc -l")
print(f"Content provider SMS count: {count}")
