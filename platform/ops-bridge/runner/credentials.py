from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re


class CredentialError(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class TemporaryTencentCredentials:
    secret_id: str = field(repr=False)
    secret_key: str = field(repr=False)
    session_token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self):
        if not re.fullmatch(r"AKID[A-Za-z0-9]{8,64}", self.secret_id or ""):
            raise CredentialError("Tencent temporary credential ID is invalid")
        if len(self.secret_key or "") < 32 or len(self.session_token or "") < 16:
            raise CredentialError("Tencent temporary credential set is incomplete")
        if self.expires_at.tzinfo is None or self.expires_at <= datetime.now(timezone.utc):
            raise CredentialError("Tencent temporary credentials are expired or lack timezone")


def credentials_from_environment(env=None):
    """Read a complete STS set without ever returning or logging partial values."""
    env = os.environ if env is None else env
    names = ("TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY", "TENCENTCLOUD_SESSION_TOKEN",
             "TENCENTCLOUD_CREDENTIAL_EXPIRES_AT")
    present = [bool(env.get(name)) for name in names]
    if not any(present):
        return None
    if not all(present):
        raise CredentialError("Incomplete Tencent temporary credential set")
    try:
        expiry = datetime.fromisoformat(env[names[3]].replace("Z", "+00:00"))
    except ValueError as error:
        raise CredentialError("Tencent credential expiry is invalid") from error
    return TemporaryTencentCredentials(env[names[0]], env[names[1]], env[names[2]], expiry)
