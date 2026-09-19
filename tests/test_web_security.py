from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from xiuxian3.adapters.web.security import (
    JsonEnvelope,
    SafeFileResolver,
    SessionStore,
    WebPermission,
    WebRequest,
    WebSecurity,
    WebSecurityError,
)
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator
from xiuxian3.infrastructure.paths import PathBoundaryError


class WebSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        self.ids = SequenceIdGenerator(["session-1", "csrf-1"])
        self.sessions = SessionStore(self.clock, self.ids, ttl=timedelta(minutes=10))
        self.session = self.sessions.create("admin-1", {WebPermission.READ, WebPermission.GAME_WRITE})
        self.security = WebSecurity(self.sessions)

    def test_json_envelope_has_stable_success_and_error_shapes(self) -> None:
        success = JsonEnvelope.success({"status": "ok"}, request_id="req-1")
        failure = JsonEnvelope.failure(
            code="forbidden",
            message="permission denied",
            request_id="req-2",
            retryable=False,
            fields={"permission": "game_write"},
        )
        self.assertEqual(
            success.as_dict(),
            {"ok": True, "data": {"status": "ok"}, "error": None, "request_id": "req-1"},
        )
        self.assertEqual(
            failure.as_dict(),
            {
                "ok": False,
                "data": None,
                "error": {
                    "code": "forbidden",
                    "message": "permission denied",
                    "retryable": False,
                    "fields": {"permission": "game_write"},
                },
                "request_id": "req-2",
            },
        )

    def test_permission_and_csrf_are_required_for_writes(self) -> None:
        request = WebRequest(session_id="session-1", permission=WebPermission.GAME_WRITE, method="POST")
        with self.assertRaisesRegex(WebSecurityError, "CSRF") as csrf_error:
            self.security.require(request)
        self.assertEqual(csrf_error.exception.code, "csrf_required")

        authorized = self.security.require(
            request.__class__(
                session_id=request.session_id,
                permission=request.permission,
                method=request.method,
                csrf_token="csrf-1",
                idempotency_key="op-1",
            )
        )
        self.assertEqual(authorized.admin_id, "admin-1")

    def test_write_requires_idempotency_key_but_read_does_not(self) -> None:
        read = WebRequest(session_id="session-1", permission=WebPermission.READ, method="GET")
        self.assertEqual(self.security.require(read).admin_id, "admin-1")
        write = WebRequest(
            session_id="session-1",
            permission=WebPermission.GAME_WRITE,
            method="POST",
            csrf_token="csrf-1",
        )
        with self.assertRaisesRegex(WebSecurityError, "Idempotency") as error:
            self.security.require(write)
        self.assertEqual(error.exception.code, "idempotency_key_required")

    def test_expired_or_underprivileged_sessions_are_rejected(self) -> None:
        self.clock.value += timedelta(minutes=11)
        request = WebRequest(session_id="session-1", permission=WebPermission.READ, method="GET")
        with self.assertRaises(WebSecurityError) as expired:
            self.security.require(request)
        self.assertEqual(expired.exception.code, "unauthenticated")

        fresh_ids = SequenceIdGenerator(["session-2", "csrf-2"])
        sessions = SessionStore(FixedClock(datetime(2026, 1, 1, tzinfo=UTC)), fresh_ids)
        sessions.create("reader", {WebPermission.READ})
        security = WebSecurity(sessions)
        with self.assertRaises(WebSecurityError) as forbidden:
            security.require(
                WebRequest(
                    session_id="session-2",
                    permission=WebPermission.BACKUP,
                    method="GET",
                )
            )
        self.assertEqual(forbidden.exception.code, "forbidden")

    def test_safe_file_resolver_rejects_escape_symlink_and_non_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "good.txt").write_text("ok", encoding="utf-8")
            (Path(outside) / "secret.txt").write_text("secret", encoding="utf-8")
            (root / "link.txt").symlink_to(Path(outside) / "secret.txt")
            resolver = SafeFileResolver(root)
            self.assertEqual(resolver.resolve("good.txt"), root / "good.txt")
            for identifier in ("../secret.txt", "/etc/passwd", "link.txt"):
                with self.subTest(identifier=identifier):
                    with self.assertRaises(PathBoundaryError):
                        resolver.resolve(identifier)
            (root / "folder").mkdir()
            with self.assertRaises(PathBoundaryError):
                resolver.resolve("folder")
