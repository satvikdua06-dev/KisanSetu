"""Admin authentication for operator endpoints.

Admin endpoints are disabled (503) unless KISANSETU_ADMIN_KEY is set, and require the key in the
X-Admin-Key header. Replaced by role-based auth (phone OTP + JWT roles) when the auth module lands.
"""

import hmac
import os

from fastapi import Header, HTTPException


async def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("KISANSETU_ADMIN_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="admin endpoints are disabled: KISANSETU_ADMIN_KEY is not set")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="invalid admin key")
