"""API authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from deepscout.config import get_settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """Authenticated API caller used for rate-limit partitioning."""

    key: str
    authenticated: bool


def _candidate(api_key: str | None, bearer: HTTPAuthorizationCredentials | None) -> str | None:
    if api_key:
        return api_key
    if bearer and bearer.scheme.lower() == "bearer":
        return bearer.credentials
    return None


async def require_api_principal(
    request: Request,
    api_key: Annotated[str | None, Security(_API_KEY_HEADER)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)],
) -> Principal:
    """Require the configured shared secret; stay open for local dev when unset."""

    configured = get_settings().api_key
    supplied = _candidate(api_key, bearer)
    if configured:
        if not supplied or not hmac.compare_digest(supplied, configured):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效或缺失的 API 凭据。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        fingerprint = hashlib.sha256(configured.encode("utf-8")).hexdigest()[:16]
        return Principal(key=f"key:{fingerprint}", authenticated=True)

    client = request.client.host if request.client else "unknown"
    return Principal(key=f"ip:{client}", authenticated=False)
