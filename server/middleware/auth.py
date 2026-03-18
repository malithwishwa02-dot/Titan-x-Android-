"""
Titan V11.3 — API Authentication Middleware
Bearer token auth using TITAN_API_SECRET environment variable.
"""

import os
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Paths that don't require authentication
PUBLIC_PATHS = {"/", "/mobile", "/static", "/docs", "/openapi.json", "/redoc",
                "/ready", "/live", "/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token on all /api/* endpoints."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public paths and static files
        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # Skip auth entirely if no secret is configured (dev mode / first deploy)
        secret = os.environ.get("TITAN_API_SECRET", "").strip()
        if not secret or secret == "change-me-to-a-secure-random-string":
            return await call_next(request)

        # Require auth for /api/* and /ws/* endpoints
        if path.startswith("/api/") or path.startswith("/ws/"):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing Bearer token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = auth_header[7:]
            if token != secret:
                raise HTTPException(403, "Invalid API token")

        return await call_next(request)
