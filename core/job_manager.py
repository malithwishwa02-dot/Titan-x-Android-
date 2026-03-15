"""
Titan V11.3 — Job Manager
Centralized job lifecycle management with TTL cleanup and optional JSON persistence.
Replaces bare dict stores (_inject_jobs, _provision_jobs) across routers.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("titan.job-manager")

_DEFAULT_TTL = 3600  # 1 hour
_CLEANUP_INTERVAL = 300  # 5 minutes


class JobManager:
    """Thread-safe job store with TTL expiration and optional disk persistence."""

    def __init__(self, namespace: str, ttl: int = _DEFAULT_TTL, persist: bool = True):
        self._namespace = namespace
        self._ttl = ttl
        self._persist = persist
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._persist_dir = Path(os.environ.get("TITAN_DATA", "/opt/titan/data")) / "jobs" / namespace
        if self._persist:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_persisted()
        self._start_cleanup()

    def _persist_path(self, job_id: str) -> Path:
        return self._persist_dir / f"{job_id}.json"

    def _load_persisted(self):
        """Load completed/failed jobs from disk on startup."""
        count = 0
        for f in self._persist_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                jid = data.get("job_id", f.stem)
                self._jobs[jid] = data
                count += 1
            except Exception:
                pass
        if count:
            logger.info(f"[{self._namespace}] Loaded {count} persisted jobs")

    def _save(self, job_id: str):
        if not self._persist:
            return
        try:
            self._persist_path(job_id).write_text(json.dumps(self._jobs[job_id], default=str))
        except Exception as e:
            logger.debug(f"Job persist failed for {job_id}: {e}")

    def create(self, job_id: str, initial: dict) -> dict:
        """Create a new job entry."""
        with self._lock:
            initial["job_id"] = job_id
            initial.setdefault("created_at", time.time())
            self._jobs[job_id] = initial
            self._save(job_id)
        return initial

    def get(self, job_id: str) -> Optional[dict]:
        """Get a job by ID, or None if not found / expired."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, patch: dict):
        """Update fields on an existing job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.update(patch)
                self._save(job_id)

    def list_jobs(self, limit: int = 50) -> list:
        """List recent jobs, newest first."""
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)
        return jobs[:limit]

    def _cleanup(self):
        """Remove expired jobs (completed/failed older than TTL)."""
        now = time.time()
        expired = []
        with self._lock:
            for jid, job in list(self._jobs.items()):
                completed = job.get("completed_at") or job.get("created_at", now)
                status = job.get("status", "")
                if status in ("completed", "failed") and (now - completed) > self._ttl:
                    expired.append(jid)
            for jid in expired:
                del self._jobs[jid]
                if self._persist:
                    try:
                        self._persist_path(jid).unlink(missing_ok=True)
                    except Exception:
                        pass
        if expired:
            logger.info(f"[{self._namespace}] Cleaned up {len(expired)} expired jobs")

    def _start_cleanup(self):
        def _loop():
            while True:
                time.sleep(_CLEANUP_INTERVAL)
                try:
                    self._cleanup()
                except Exception:
                    pass
        t = threading.Thread(target=_loop, daemon=True, name=f"job-cleanup-{self._namespace}")
        t.start()


# ── Singleton instances ──────────────────────────────────────────────
inject_jobs = JobManager("inject", ttl=3600)
provision_jobs = JobManager("provision", ttl=7200)
