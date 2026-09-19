"""Typed process configuration and redacted diagnostics."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """Raised when an environment value cannot be parsed safely."""


def _bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be positive")
    return value


def _csv(environ: Mapping[str, str], name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in environ.get(name, "").split(",") if value.strip())


def _capabilities(environ: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    raw = environ.get("XIUXIAN3_QQ_CAPABILITIES", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("XIUXIAN3_QQ_CAPABILITIES must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ConfigError("XIUXIAN3_QQ_CAPABILITIES must be a JSON object")
    result: dict[str, tuple[str, ...]] = {}
    for app_id, capabilities in value.items():
        if not isinstance(app_id, str) or not isinstance(capabilities, list):
            raise ConfigError("QQ capabilities must map strings to string lists")
        if not all(isinstance(item, str) for item in capabilities):
            raise ConfigError("QQ capability names must be strings")
        result[app_id] = tuple(capabilities)
    return result


def _load_or_create_secret(data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_path = data_dir / ".web_secret_key"
    try:
        value = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = ""
    if value:
        return value
    generated = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(secret_path, flags, 0o600)
    try:
        os.write(descriptor, generated.encode("utf-8"))
    finally:
        os.close(descriptor)
    return generated


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Validated configuration passed to the composition root."""

    data_dir: Path
    web_enabled: bool
    web_port: int
    web_secret_key: str | None
    web_allowed_hosts: tuple[str, ...]
    admin_ids: frozenset[str]
    timezone: str
    rate_user_per_minute: int
    rate_group_per_minute: int
    rate_global_per_minute: int
    qq_capabilities: dict[str, tuple[str, ...]]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeConfig":
        values = os.environ if environ is None else environ
        raw_data_dir = values.get("XIUXIAN3_DATA_DIR", "data").strip()
        if not raw_data_dir:
            raise ConfigError("XIUXIAN3_DATA_DIR cannot be empty")
        data_dir = Path(raw_data_dir).expanduser().resolve()
        web_enabled = _bool(values, "XIUXIAN3_WEB_ENABLED", False)
        web_port = _positive_int(values, "XIUXIAN3_WEB_PORT", 8080)
        if web_port > 65535:
            raise ConfigError("XIUXIAN3_WEB_PORT must be between 1 and 65535")
        secret = values.get("XIUXIAN3_WEB_SECRET_KEY")
        if web_enabled and not secret:
            secret = _load_or_create_secret(data_dir)
        return cls(
            data_dir=data_dir,
            web_enabled=web_enabled,
            web_port=web_port,
            web_secret_key=secret,
            web_allowed_hosts=_csv(values, "XIUXIAN3_WEB_ALLOWED_HOSTS") or ("127.0.0.1", "localhost"),
            admin_ids=frozenset(_csv(values, "XIUXIAN3_ADMIN_IDS")),
            timezone=values.get("XIUXIAN3_TIMEZONE", "UTC").strip() or "UTC",
            rate_user_per_minute=_positive_int(values, "XIUXIAN3_RATE_USER_PER_MINUTE", 30),
            rate_group_per_minute=_positive_int(values, "XIUXIAN3_RATE_GROUP_PER_MINUTE", 120),
            rate_global_per_minute=_positive_int(values, "XIUXIAN3_RATE_GLOBAL_PER_MINUTE", 600),
            qq_capabilities=_capabilities(values),
        )

    def redacted(self) -> dict[str, object]:
        """Return diagnostics safe for logs and health output."""

        return {
            "data_dir": str(self.data_dir),
            "web_enabled": self.web_enabled,
            "web_port": self.web_port,
            "web_secret_key_configured": self.web_secret_key is not None,
            "web_allowed_hosts": self.web_allowed_hosts,
            "admin_count": len(self.admin_ids),
            "timezone": self.timezone,
            "rate_user_per_minute": self.rate_user_per_minute,
            "rate_group_per_minute": self.rate_group_per_minute,
            "rate_global_per_minute": self.rate_global_per_minute,
            "qq_capability_app_count": len(self.qq_capabilities),
        }