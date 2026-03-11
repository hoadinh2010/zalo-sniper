import secrets
from datetime import datetime, timedelta
from typing import Dict

import bcrypt

SESSION_TTL_HOURS = 24


class AuthManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, datetime] = {}  # token → expires_at

    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify_password(self, password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), hashed.encode())
        except Exception:
            return False

    def create_session(self) -> str:
        token = secrets.token_hex(32)  # 64-char hex string
        self._sessions[token] = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)
        return token

    def validate_session(self, token: str) -> bool:
        expires = self._sessions.get(token)
        if not expires:
            return False
        if datetime.utcnow() > expires:
            del self._sessions[token]
            return False
        return True

    def invalidate_session(self, token: str) -> None:
        self._sessions.pop(token, None)
