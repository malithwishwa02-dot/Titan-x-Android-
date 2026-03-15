#!/usr/bin/env python3
"""
Titan V11.3 — E2E Pipeline Integration Test

Runs a lightweight end-to-end test of the core pipeline stages:
  1. Profile forge (mini profile)
  2. Profile injection
  3. Stealth patch (full 26 phases)
  4. Audit (44 vectors)
  5. Task verification
  6. Wallet verification (13 checks)

Usage:
  python3 test_e2e_pipeline.py [--device-id DEVICE] [--adb-target HOST:PORT]
                                [--min-audit 80] [--min-trust 70]

Exit codes:
  0 = all thresholds met
  1 = one or more thresholds failed
  2 = fatal error (ADB unreachable, import failure, etc.)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e_test")

# Ensure core/ and server/ are importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "server"))


def check_adb(target: str) -> bool:
    """Verify ADB connectivity."""
    try:
        r = subprocess.run(
            ["adb", "-s", target, "shell", "echo ok"],
            capture_output=True, text=True, timeout=10,
        )
        return "ok" in r.stdout
    except Exception as e:
        logger.error(f"ADB check failed: {e}")
        return False


def stage_forge() -> dict:
    """Stage 1: Generate a mini profile."""
    from android_profile_forge import AndroidProfileForge
    forge = AndroidProfileForge()
    profile = forge.generate(
        locale="en-US",
        age_days=30,
        num_contacts=8,
        num_calls=20,
        num_sms=10,
        num_history=30,
        num_cookies=15,
    )
    assert len(profile.get("contacts", [])) >= 5, "Forge: too few contacts"
    assert len(profile.get("call_logs", [])) >= 10, "Forge: too few call logs"
    assert len(profile.get("sms", [])) >= 5, "Forge: too few SMS"
    assert len(profile.get("browsing_history", [])) >= 20, "Forge: too few history"
    logger.info(f"  Forge: {len(profile['contacts'])} contacts, "
                f"{len(profile['call_logs'])} calls, {len(profile['sms'])} SMS, "
                f"{len(profile['browsing_history'])} history")
    return profile


def stage_inject(target: str, profile: dict) -> dict:
    """Stage 2: Inject profile into device."""
    from profile_injector import ProfileInjector
    injector = ProfileInjector(adb_target=target)
    result = injector.inject_full_profile(profile)
    result_dict = result.to_dict()
    logger.info(f"  Inject: trust={result.trust_score}, "
                f"cookies={result.cookies_injected}, contacts={result.contacts_injected}, "
                f"errors={len(result.errors)}")
    return result_dict


def stage_patch(target: str, preset: str = "samsung_s24_ultra",
                carrier: str = "att", location: str = "new_york") -> dict:
    """Stage 3: Run full stealth patch."""
    from anomaly_patcher import AnomalyPatcher
    patcher = AnomalyPatcher(adb_target=target)
    report = patcher.full_patch(preset, carrier, location)
    logger.info(f"  Patch: {report.passed}/{report.total} passed, "
                f"score={report.score}, elapsed={report.elapsed_sec:.1f}s")
    return {
        "passed": report.passed, "total": report.total,
        "score": report.score, "elapsed": report.elapsed_sec,
    }


def stage_audit(target: str) -> dict:
    """Stage 4: Run 44-vector forensic audit."""
    from anomaly_patcher import AnomalyPatcher
    patcher = AnomalyPatcher(adb_target=target)
    result = patcher.audit()
    passed = result["passed"]
    total = result["total"]
    score = result["score"]
    failed_checks = [k for k, v in result["checks"].items() if not v]
    logger.info(f"  Audit: {passed}/{total} passed, score={score}")
    if failed_checks:
        logger.info(f"  Audit failures: {', '.join(failed_checks)}")
    return result


def stage_wallet_verify(target: str) -> dict:
    """Stage 5: Deep wallet verification."""
    from wallet_verifier import WalletVerifier
    wv = WalletVerifier(adb_target=target)
    report = wv.verify()
    logger.info(f"  Wallet: {report.passed}/{report.total} ({report.grade})")
    failed = [c.name for c in report.checks if not c.passed]
    if failed:
        logger.info(f"  Wallet failures: {', '.join(failed)}")
    return report.to_dict()


def main():
    parser = argparse.ArgumentParser(description="Titan E2E Pipeline Integration Test")
    parser.add_argument("--device-id", default="test-e2e")
    parser.add_argument("--adb-target", default="127.0.0.1:6520")
    parser.add_argument("--min-audit", type=int, default=80,
                        help="Minimum audit score to pass (default: 80)")
    parser.add_argument("--min-trust", type=int, default=60,
                        help="Minimum trust score to pass (default: 60)")
    parser.add_argument("--min-wallet", type=int, default=50,
                        help="Minimum wallet score to pass (default: 50)")
    parser.add_argument("--preset", default="samsung_s24_ultra")
    parser.add_argument("--carrier", default="att")
    parser.add_argument("--location", default="new_york")
    parser.add_argument("--output", default="",
                        help="Path to write JSON results (optional)")
    args = parser.parse_args()

    logger.info(f"═══ Titan E2E Pipeline Test ═══")
    logger.info(f"Target: {args.adb_target} | Preset: {args.preset}")
    logger.info(f"Thresholds: audit≥{args.min_audit}, trust≥{args.min_trust}, wallet≥{args.min_wallet}")

    # Pre-check: ADB
    if not check_adb(args.adb_target):
        logger.error("FATAL: ADB not reachable")
        sys.exit(2)

    results = {"device_id": args.device_id, "adb_target": args.adb_target,
               "timestamp": time.time(), "stages": {}, "passed": False}
    t_start = time.time()

    try:
        # Stage 1: Forge
        logger.info("Stage 1/5: Profile Forge")
        profile = stage_forge()
        results["stages"]["forge"] = {"ok": True, "contacts": len(profile.get("contacts", []))}

        # Stage 2: Inject
        logger.info("Stage 2/5: Profile Injection")
        inject_result = stage_inject(args.adb_target, profile)
        trust_score = inject_result.get("trust_score", 0)
        results["stages"]["inject"] = {"ok": True, "trust_score": trust_score}

        # Stage 3: Patch
        logger.info("Stage 3/5: Stealth Patch (26 phases)")
        patch_result = stage_patch(args.adb_target, args.preset, args.carrier, args.location)
        results["stages"]["patch"] = patch_result

        # Stage 4: Audit
        logger.info("Stage 4/5: Forensic Audit (44 vectors)")
        audit_result = stage_audit(args.adb_target)
        audit_score = audit_result["score"]
        results["stages"]["audit"] = {
            "score": audit_score,
            "passed": audit_result["passed"],
            "total": audit_result["total"],
            "failures": [k for k, v in audit_result["checks"].items() if not v],
        }

        # Stage 5: Wallet
        logger.info("Stage 5/5: Wallet Verification (13 checks)")
        wallet_result = stage_wallet_verify(args.adb_target)
        wallet_score = wallet_result.get("score", 0)
        results["stages"]["wallet"] = {
            "score": wallet_score,
            "grade": wallet_result.get("grade", "?"),
            "passed": wallet_result.get("passed", 0),
            "total": wallet_result.get("total", 0),
        }

    except Exception as e:
        logger.error(f"FATAL: Pipeline failed — {e}")
        results["error"] = str(e)
        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2)
        sys.exit(2)

    elapsed = time.time() - t_start
    results["elapsed_sec"] = round(elapsed, 1)

    # Threshold checks
    audit_ok = audit_score >= args.min_audit
    trust_ok = trust_score >= args.min_trust
    wallet_ok = wallet_score >= args.min_wallet

    results["thresholds"] = {
        "audit": {"score": audit_score, "min": args.min_audit, "ok": audit_ok},
        "trust": {"score": trust_score, "min": args.min_trust, "ok": trust_ok},
        "wallet": {"score": wallet_score, "min": args.min_wallet, "ok": wallet_ok},
    }
    results["passed"] = audit_ok and trust_ok and wallet_ok

    # Summary
    logger.info(f"")
    logger.info(f"═══ RESULTS ({elapsed:.1f}s) ═══")
    logger.info(f"  Audit:  {audit_score}% {'✓' if audit_ok else '✗ FAIL'} (min {args.min_audit}%)")
    logger.info(f"  Trust:  {trust_score}% {'✓' if trust_ok else '✗ FAIL'} (min {args.min_trust}%)")
    logger.info(f"  Wallet: {wallet_score}% {'✓' if wallet_ok else '✗ FAIL'} (min {args.min_wallet}%)")
    logger.info(f"  Overall: {'PASS ✓' if results['passed'] else 'FAIL ✗'}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results written to {args.output}")

    sys.exit(0 if results["passed"] else 1)


if __name__ == "__main__":
    main()
