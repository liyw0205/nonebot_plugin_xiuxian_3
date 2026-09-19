"""Framework-neutral Web security contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from ...infrastructure.paths import PathBoundaryError, RuntimePaths
from ...ports.clock import Clock
from ...ports.id_generator import IdGenerator


class WebPermission(str, Enum):
    READ = "read"
    GAME_WRITE = "game_write"
    MESSAGE = "message"
    SCHEDULER = "scheduler"
    BACKUP = "backup"
    UPDATE = "update"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class JsonEnvelope:
    ok: bool
    data: Any
    error: dict[str, Any] | None
    request_id: str

    @classmethod
    def success(cls, data: Any, *, request_id: str) -> "JsonEnvelope":
        return cls(ok=True, data=data, error=None, request_id=request_id)

    @classmethod
    def failure(
        cls,
        *,
        code: str,
        message: str,
        request_id: str,
        retryable: bool,
        fields: dict[str, str] | None = None,
    ) -> "JsonEnvelope":
        return cls(
            ok=False,
            data=None,
            error={
                "code": code,
                "message": message,
                "retryable": retryable,
                "fields": fields or {},
            },
            request_id=request_id,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class WebSession:
    session_id: str
    admin_id: str
    csrf_token: str
    permissions: frozenset[WebPermission]
    expires_at: datetime


class SessionStore:
    """Process-local session store intended for tests and a future server adapter."""

    def __init__(self, clock: Clock, ids: IdGenerator, *, ttl: timedelta = timedelta(hours=8)) -> None:
        if ttl <= timedelta(0):
            raise ValueError("session ttl must be positive")
        self._clock = clock
        self._ids = ids
        self._ttl = ttl
        self._sessions: dict[str, WebSession] = {}

    def create(self, admin_id: str, permissions: set[WebPermission] | frozenset[WebPermission]) -> WebSession:
        if not admin_id:
            raise ValueError("admin_id cannot be empty")
        session = WebSession(
            session_id=self._ids.new_id(),
            admin_id=admin_id,
            csrf_token=self._ids.new_id(),
            permissions=frozenset(permissions),
            expires_at=self._clock.now() + self._ttl,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> WebSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if self._clock.now() >= session.expires_at:
            self._sessions.pop(session_id, None)
            return None
        return session

    def revoke(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


@dataclass(frozen=True, slots=True)
class WebRequest:
    session_id: str | None
    permission: WebPermission
    method: str
    csrf_token: str | None = None
    idempotency_key: str | None = None


class WebSecurityError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AuthorizedRequest:
    admin_id: str
    permission: WebPermission
    idempotency_key: str | None


class WebSecurity:
    WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    def require(self, request: WebRequest) -> AuthorizedRequest:
        session = self._sessions.get(request.session_id or "")
        if session is None:
            raise WebSecurityError("unauthenticated", "管理员会话无效或已过期")
        if request.permission not in session.permissions:
            raise WebSecurityError("forbidden", "管理员会话没有所需权限")
        is_write = request.method.upper() in self.WRITE_METHODS
        if is_write and request.csrf_token != session.csrf_token:
            raise WebSecurityError("csrf_required", "写请求需要有效 CSRF token")
        if is_write and not request.idempotency_key:
            raise WebSecurityError("idempotency_key_required", "写请求需要 Idempotency-Key")
        return AuthorizedRequest(session.admin_id, request.permission, request.idempotency_key)


class SafeFileResolver:
    """Resolve only existing regular files beneath a runtime root."""

    def __init__(self, root: Path) -> None:
        self._paths = RuntimePaths.from_root(root)

    def resolve(self, identifier: str | Path) -> Path:
        candidate = self._paths.resolve(identifier)
        if candidate.is_symlink() or not candidate.is_file():
            raise PathBoundaryError("file identifier must resolve to a regular file")
        return candidate