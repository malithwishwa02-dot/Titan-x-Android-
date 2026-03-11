#!/usr/bin/env python3
"""Inject SMS messages to fill gap and verify final trust score."""
import subprocess
import time

ADB_TARGET = "127.0.0.1:5555"

def adb_shell(cmd, timeout=10):
    try:
        r = subprocess.run(
            ["adb", "-s", ADB_TARGET, "shell", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)

now_ms = int(time.time() * 1000)

messages = [
    ("+12133456789", "Hey are you free tonight", 1, now_ms - 86400000),
    ("+12133456789", "Yeah what time", 2, now_ms - 85800000),
    ("+13234567890", "Your appointment is tomorrow at 10 30 AM", 1, now_ms - 172800000),
    ("33789", "Chase Visa ending 0405 added to Google Pay", 1, now_ms - 259200000),
    ("33789", "Transaction of 47.82 on card ending 0405 approved", 1, now_ms - 345600000),
    ("72000", "Your verification code is 847291", 1, now_ms - 432000000),
    ("+17078361999", "Hi sweetie are you coming for dinner Sunday", 1, now_ms - 518400000),
    ("+17078361999", "Yes I will be there around 2pm", 2, now_ms - 517800000),
    ("+12133456789", "Bro did you see the game last night", 1, now_ms - 604800000),
    ("+12133456789", "Yeah that last quarter was insane", 2, now_ms - 604200000),
]

ok = 0
for addr, body, stype, ts in messages:
    cmd = (
        f"content insert --uri content://sms "
        f"--bind address:s:{addr} "
        f"--bind body:s:{body} "
        f"--bind type:i:{stype} "
        f"--bind date:l:{ts} "
        f"--bind read:i:1 "
        f"--bind seen:i:1"
    )
    success, out = adb_shell(cmd)
    if success:
        ok += 1
        print(f"  OK: {addr} -> {body[:40]}")
    else:
        print(f"  FAIL: {addr} -> {out[:60]}")

print(f"\nInjected {ok}/10 SMS")

# Verify
_, count = adb_shell("content query --uri content://sms --projection _id | wc -l")
print(f"Total SMS on device: {count}")
