"""
Titan V11.3 — Rate Limiting Middleware
Per-IP rate limiting to prevent abuse.
"""

import time
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# Rate limits: (max_requests, window_seconds)
RATE_LIMITS = {
    "default": (100, 60),       # 100 req/min for general API
    "create": (10, 60),         # 10 req/min for device/profile creation
}

CREATE_PATHS = {"/api/devices", "/api/genesis/create", "/api/genesis/smartforge"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory per-IP rate limiter."""

    def __init__(self, app):
        super().__init__(app)
        self._requests = defaultdict(list)  # ip -> [timestamps]
        self._create_requests = defaultdict(list)
        self._request_count = 0
        self._cleanup_interval = 100  # purge stale IPs every N requests

    def _check_limit(self, store: dict, ip: str, max_req: int, window: int):
        now = time.time()
        # Prune old entries
        store[ip] = [t for t in store[ip] if now - t < window]
        if len(store[ip]) >= max_req:
            return False
        store[ip].append(now)
        return True

    def _cleanup_stale_ips(self):
        """Remove IPs with no recent timestamps to prevent memory growth."""
        now = time.time()
        max_window = max(w for _, w in RATE_LIMITS.values())
        for store in (self._requests, self._create_requests):
            stale = [ip for ip, ts in store.items() if not ts or now - ts[-1] > max_window * 2]
            for ip in stale:
                del store[ip]

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-API paths
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"

        # Periodic cleanup of stale IP entries
        self._request_count += 1
        if self._request_count % self._cleanup_interval == 0:
            self._cleanup_stale_ips()

        # Check creation-specific rate limit
        if request.method == "POST" and request.url.path in CREATE_PATHS:
            max_req, window = RATE_LIMITS["create"]
            if not self._check_limit(self._create_requests, ip, max_req, window):
                raise HTTPException(429, "Rate limit exceeded for creation endpoints")

        # Check general rate limit
        max_req, window = RATE_LIMITS["default"]
        if not self._check_limit(self._requests, ip, max_req, window):
            raise HTTPException(429, "Rate limit exceeded")

        return await call_next(request)
