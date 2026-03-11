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

    def _check_limit(self, store: dict, ip: str, max_req: int, window: int):
        now = time.time()
        # Prune old entries
        store[ip] = [t for t in store[ip] if now - t < window]
        if len(store[ip]) >= max_req:
            return False
        store[ip].append(now)
        return True

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-API paths
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"

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
