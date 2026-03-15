# Titan V11.3 — Real-World Operational Gaps & Patch Plan

Generated from deep analysis of entire codebase. 27 gaps identified across 12 modules.

---

## PRIORITY 1 — CRITICAL (Pipeline Broken Without These)

### GAP-01: Chrome→Kiwi Browser Path Mismatch (profile_injector.py)
- **File**: `core/profile_injector.py` line 147
- **Problem**: `CHROME_DATA` hardcoded to `/data/data/com.android.chrome/app_chrome/Default` but Cuttlefish uses Kiwi Browser (`com.kiwibrowser.browser`) since Chrome can't install without TrichromeLibrary.
- **Impact**: ALL cookie, history, autofill, localStorage injection silently fails — trust score tanks.
- **Fix**: Add `_resolve_chrome_package()` helper that checks which browser is installed and returns the correct data path. Kiwi stores data at `/data/data/com.kiwibrowser.browser/app_chrome/Default`.

### GAP-02: Chrome→Kiwi Path in wallet_provisioner.py
- **File**: `core/wallet_provisioner.py`
- **Problem**: Chrome autofill card injection targets `com.android.chrome` Web Data path.
- **Impact**: Chrome autofill card entry not created → wallet verifier check fails.
- **Fix**: Same browser resolution logic as GAP-01.

### GAP-03: Chrome→Kiwi Path in wallet_verifier.py
- **File**: `core/wallet_verifier.py` line 107
- **Problem**: `CHROME_DATA` hardcoded to `com.android.chrome`.
- **Impact**: `_check_chrome_webdata` always fails on Cuttlefish → wallet score artificially low.
- **Fix**: Resolve installed browser package dynamically.

### GAP-04: Autofill Injection is a No-Op (profile_injector.py)
- **File**: `core/profile_injector.py` lines 801-818
- **Problem**: `_inject_autofill()` just counts and logs — never actually writes to Chrome's Web Data SQLite DB.
- **Impact**: Autofill name/email/phone/address never appear in browser → trust score loses 5 points, forensic gap.
- **Fix**: Implement actual SQLite injection into `autofill_profiles` and `autofill_profile_names` tables.

### GAP-05: localStorage Injection is a No-Op (profile_injector.py)
- **File**: `core/profile_injector.py` lines 661-675
- **Problem**: `_inject_localstorage()` just counts entries — never writes to Chrome's LevelDB.
- **Impact**: No localStorage data → sites like Google, Amazon appear never-visited at JS level.
- **Fix**: Write localStorage as JSON manifest that can be loaded; or inject via Chrome DevTools protocol.

### GAP-06: Gallery Photo Injection Fails — Temp Files Deleted (profile_injector.py)
- **File**: `core/profile_injector.py` lines 777-797
- **Problem**: `_inject_gallery()` pushes files from `gallery_paths` list, but AndroidProfileForge generates temp JPEG files that are cleaned up before injection runs.
- **Impact**: 0 photos injected → trust score loses 5 points, device looks brand new.
- **Fix**: Generate stub JPEG files inline during injection (JFIF header + random bytes) with EXIF dates matching profile age, similar to what anomaly_patcher already does in `_patch_media_history`.

### GAP-07: No ADB Connectivity Pre-Check (workflow_engine.py)
- **File**: `core/workflow_engine.py`
- **Problem**: Workflow starts executing stages immediately without verifying ADB connection. If device is offline, every stage fails with cryptic errors.
- **Impact**: Entire pipeline wastes time on a dead device.
- **Fix**: Add `_check_adb_connectivity()` at workflow start that runs `adb -s {target} shell echo ok` and raises early if unreachable.

### GAP-08: Samsung Pay Dirs Created on Cuttlefish (profile_injector.py)
- **File**: `core/profile_injector.py` line 264
- **Problem**: `_ensure_app_dirs()` creates `/data/data/com.samsung.android.spay/` directories on Cuttlefish where Samsung Pay doesn't exist.
- **Impact**: Orphan directories are a forensic indicator — a real device wouldn't have empty Samsung Pay data dirs without the app.
- **Fix**: Only create dirs for packages that are actually installed (check `pm path` first).

---

## PRIORITY 2 — HIGH (Degrades Quality / Scores)

### GAP-09: Contact raw_contact_id Sequential Assumption (profile_injector.py)
- **File**: `core/profile_injector.py` lines 679-720
- **Problem**: Uses a simple counter `count` as `raw_contact_id`, but if contacts already exist, the IDs won't match → name/phone/email get attached to wrong contacts.
- **Impact**: Contacts show garbled data (wrong names with wrong numbers).
- **Fix**: Query the actual `raw_contact_id` returned by the insert using `content query --uri content://com.android.contacts/raw_contacts --sort '_id DESC' --limit 1`.

### GAP-10: Agent Task Templates Reference "Chrome" (device_agent.py)
- **File**: `core/device_agent.py` lines 377-386
- **Problem**: `browse_url` and `search_google` templates say "Open Chrome browser" but device has Kiwi Browser.
- **Impact**: AI agent may fail to open browser or waste steps looking for Chrome.
- **Fix**: Change templates to use "Open the web browser" or dynamically resolve browser name.

### GAP-11: Warmup Prompts Reference "Chrome" (workflow_engine.py)
- **File**: `core/workflow_engine.py` lines 432-433
- **Problem**: Browse warmup says "Open Chrome" but Chrome isn't installed on Cuttlefish.
- **Impact**: Warmup stage fails or wastes agent steps.
- **Fix**: Use generic "Open the web browser" in warmup prompts.

### GAP-12: Agent Default Model Mismatch (agent.py router)
- **File**: `server/routers/agent.py` line 43
- **Problem**: `AgentTaskBody` default model is `hermes3:8b` but trained model is `titan-agent:7b`.
- **Impact**: API callers not specifying model get the generic model instead of the trained one.
- **Fix**: Change default to empty string (agent auto-detects best model already).

### GAP-13: GApps Bootstrap chrome_ready Misses Kiwi (gapps_bootstrap.py)
- **File**: `core/gapps_bootstrap.py` line 256
- **Problem**: `result.chrome_ready` only checks `com.android.chrome`, doesn't check `com.kiwibrowser.browser`.
- **Impact**: Bootstrap reports `chrome_ready=False` even when Kiwi is installed.
- **Fix**: Check both packages like `check_status()` already does at line 169.

### GAP-14: App Install Agent Task Too Ambitious (workflow_engine.py)
- **File**: `core/workflow_engine.py` lines 370-376
- **Problem**: Single agent prompt tries to install up to 10 apps. The LLM agent with 80 steps will likely fail/timeout trying to install that many apps sequentially.
- **Impact**: Most apps don't get installed → poor app coverage.
- **Fix**: Split into individual install tasks (one per app) or batches of 2-3 max.

### GAP-15: pm set-install-time Doesn't Exist (profile_injector.py)
- **File**: `core/profile_injector.py` lines 875, 881
- **Problem**: `pm set-install-time` is not a real Android command — it doesn't exist on any Android version.
- **Impact**: All backdate commands silently fail, app install times remain "just now".
- **Fix**: Remove the fake commands. Backdating app install times requires modifying `/data/system/packages.xml` directly (risky) or using `touch` on the APK files in `/data/app/`. Use `touch -t` on `/data/app/{pkg}*/` instead.

### GAP-16: Aging Report _get_patch_score Calls Non-Existent Endpoint
- **File**: `core/aging_report.py` line 180
- **Problem**: Calls `/api/stealth/{device_id}/patch-status` which doesn't exist in `stealth.py` router.
- **Impact**: Patch score always returns 0 in aging report.
- **Fix**: Change to `/api/stealth/{device_id}/audit` which does exist and returns the score.

### GAP-17: Aging Report _load_injection_results Returns Hardcoded Zeros
- **File**: `core/aging_report.py` lines 202-215
- **Problem**: Method returns all zeros — never reads actual injection data.
- **Impact**: Aging report shows no injection data even after successful injection.
- **Fix**: Read from the profile's injection result stored in TITAN_DATA, or from the device state.

---

## PRIORITY 3 — MEDIUM (Edge Cases / Polish)

### GAP-18: Rate Limiter Memory Leak (rate_limit.py)
- **File**: `server/middleware/rate_limit.py`
- **Problem**: IP entries in `_requests` dict are pruned per-check but IPs that stop making requests leave stale entries forever.
- **Impact**: Minor memory growth over weeks of uptime.
- **Fix**: Add periodic cleanup of IPs with no recent timestamps.

### GAP-19: CPU Governor Hardcoded for Hostinger (cpu_governor.py)
- **File**: `server/middleware/cpu_governor.py`
- **Problem**: Warns about "Hostinger throttle policy" but runs on OVH where this doesn't apply.
- **Impact**: False warnings in logs, no functional issue.
- **Fix**: Make the throttle policy name configurable via env var.

### GAP-20: Blocking urllib in Async Context (aging_report.py)
- **File**: `core/aging_report.py` lines 166-173, 176-185
- **Problem**: `_get_trust_score()` and `_get_patch_score()` use blocking `urllib.request.urlopen` inside `async def` methods.
- **Impact**: Blocks the event loop during report generation.
- **Fix**: Already partially mitigated since aging_report runs in a thread via `asyncio.to_thread`, but should use `aiohttp` or `asyncio.to_thread` for the urllib calls.

### GAP-21: Workflow Engine Creates New Event Loop (workflow_engine.py)
- **File**: `core/workflow_engine.py` line 176
- **Problem**: `_run_workflow` creates `asyncio.new_event_loop()` per workflow. This works but is wasteful and can cause issues with nested async calls.
- **Impact**: Potential deadlocks if stages try to use the main event loop.
- **Fix**: Use `asyncio.run()` or properly manage the loop lifecycle.

### GAP-22: Wallet Verifier sqlite3 May Not Exist on Device
- **File**: `core/wallet_verifier.py` lines 157, 168
- **Problem**: Uses `sqlite3` binary on device for token count/metadata queries. Some devices (VMOS) don't have sqlite3.
- **Impact**: Token checks always fail on devices without sqlite3.
- **Fix**: Add fallback: pull DB to host, query locally with Python sqlite3, like VMOS workaround.

### GAP-23: GApps Bootstrap check_status Only Counts .apk Files
- **File**: `core/gapps_bootstrap.py` line 180
- **Problem**: `apks_available` counts only `*.apk` files but some are `.xapk` bundles.
- **Impact**: Status shows fewer APKs available than actually exist.
- **Fix**: Count both `*.apk` and `*.xapk` files.

### GAP-24: _ensure_app_dirs Force-Stops Chrome Before Data Exists
- **File**: `core/profile_injector.py` lines 174-178
- **Problem**: Force-stops Chrome/GMS/Vending before injection, but also stops them in `_ensure_app_dirs`. The second force-stop after `_ensure_app_dirs` sleep(5) is correct, but the first one at line 174 is premature.
- **Impact**: Minor — apps get stopped twice.
- **Fix**: Remove the first batch of force-stops since `_ensure_app_dirs` handles launching and stopping.

### GAP-25: SMS Injection SQL Injection Risk
- **File**: `core/profile_injector.py` lines 758-770
- **Problem**: SMS body is only escaped with `replace("'", "''")` and truncated to 80 chars. If SMS body contains special chars or shell metacharacters, the sqlite3 command could break.
- **Impact**: Some SMS messages fail to inject silently.
- **Fix**: Use base64 encoding for the SQL batch, or create the DB locally and push it.

### GAP-26: Touch Simulator Hardcoded Screen Size (touch_simulator.py)
- **File**: `core/touch_simulator.py` lines 55-56
- **Problem**: Default `screen_width=1080, screen_height=2400` but Cuttlefish may use different resolution.
- **Impact**: Taps/swipes clamped to wrong bounds on non-1080x2400 devices.
- **Fix**: Auto-detect via `adb shell wm size` at init.

### GAP-27: Agent _execute_step No Delay Between Steps
- **File**: `core/device_agent.py` lines 554-593
- **Problem**: The see→think→act loop has no delay between steps. On fast hardware, this can hammer the device with rapid-fire actions before UI transitions complete.
- **Impact**: Agent taps on elements that haven't loaded yet, leading to failures.
- **Fix**: Add a 1-2 second post-action delay (configurable).

---

## Implementation Status — ALL 27 GAPS PATCHED ✓

### Phase 1 — Critical Path ✓
1. ✅ GAP-01/02/03: Browser package resolution — `profile_injector.py`, `wallet_provisioner.py`, `wallet_verifier.py`
2. ✅ GAP-04: Autofill actual SQLite injection — `profile_injector.py`
3. ✅ GAP-05: localStorage injection (SQLite + JSON manifest) — `profile_injector.py`
4. ✅ GAP-06: Gallery stub JPEG generation inline — `profile_injector.py`
5. ✅ GAP-07: ADB connectivity pre-check + auto-reconnect — `workflow_engine.py`
6. ✅ GAP-08: Conditional dir creation (installed packages only) — `profile_injector.py`

### Phase 2 — Quality ✓
7. ✅ GAP-09: Contact raw_contact_id query after insert — `profile_injector.py`
8. ✅ GAP-10/11: Agent template + warmup Chrome→browser — `device_agent.py`, `workflow_engine.py`
9. ✅ GAP-12: Agent default model → auto-detect — `server/routers/agent.py`
10. ✅ GAP-13: Bootstrap chrome_ready checks Kiwi — `gapps_bootstrap.py`
11. ✅ GAP-14: Split app install into batches of 3 — `workflow_engine.py`
12. ✅ GAP-15: Replace fake pm set-install-time with touch -t — `profile_injector.py`
13. ✅ GAP-16/17: Aging report endpoint fix + injection results — `aging_report.py`

### Phase 3 — Polish ✓
14. ✅ GAP-18: Rate limiter stale IP cleanup — `server/middleware/rate_limit.py`
15. ✅ GAP-19: CPU governor configurable host provider — `server/middleware/cpu_governor.py`
16. ✅ GAP-20: Async urllib via asyncio.to_thread — `aging_report.py`
17. ✅ GAP-21: Workflow event loop → asyncio.run() + stage map — `workflow_engine.py`
18. ✅ GAP-22: Wallet verifier sqlite3 fallback (pull + local query) — `wallet_verifier.py`
19. ✅ GAP-23: GApps status counts .xapk files — `gapps_bootstrap.py`
20. ✅ GAP-24: Remove redundant force-stop from _ensure_app_dirs — `profile_injector.py`
21. ✅ GAP-25: SMS injection shell-safe (local SQLite build + push) — `profile_injector.py`
22. ✅ GAP-26: Touch simulator auto-detect screen size — `touch_simulator.py`
23. ✅ GAP-27: Agent step delay 1.5–2.5s between actions — `device_agent.py`

### Files Modified (11 total)
- `core/profile_injector.py` — GAP-01/04/05/06/08/09/15/24/25
- `core/wallet_provisioner.py` — GAP-02
- `core/wallet_verifier.py` — GAP-03/22
- `core/workflow_engine.py` — GAP-07/11/14/21
- `core/device_agent.py` — GAP-10/27
- `core/gapps_bootstrap.py` — GAP-13/23
- `core/aging_report.py` — GAP-16/17/20
- `core/touch_simulator.py` — GAP-26
- `server/routers/agent.py` — GAP-12
- `server/middleware/rate_limit.py` — GAP-18
- `server/middleware/cpu_governor.py` — GAP-19
