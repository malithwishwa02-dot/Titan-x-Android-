"""
Titan V11.3 — API Authentication Middleware
Bearer token auth using TITAN_API_SECRET environment variable.
"""

import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# Paths that don't require authentication
PUBLIC_PATHS = {"/", "/mobile", "/static", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer token on all /api/* endpoints."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public paths and static files
        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # Skip auth if no secret configured (dev mode)
        secret = os.environ.get("TITAN_API_SECRET", "")
        if not secret:
            return await call_next(request)

        # Require auth for /api/* endpoints
        if path.startswith("/api/") or path.startswith("/ws/"):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                raise HTTPException(401, "Missing Bearer token")
            token = auth_header[7:]
            if token != secret:
                raise HTTPException(403, "Invalid API token")

        return await call_next(request)
