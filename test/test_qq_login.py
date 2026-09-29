from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("xiuxian3_qq_login", ROOT / "scripts/qq_login.py")
assert SPEC and SPEC.loader
qq_login = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qq_login)


def test_decrypt_bind_secret_round_trip() -> None:
    key = AESGCM.generate_key(bit_length=256)
    nonce = b"0123456789ab"
    encrypted = nonce + AESGCM(key).encrypt(nonce, b"secret-value", None)

    assert qq_login.decrypt_bind_secret(
        base64.b64encode(encrypted).decode(),
        base64.b64encode(key).decode(),
    ) == "secret-value"


def test_merge_env_supports_unquoted_json_and_makes_backup(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    original = 'HOST=0.0.0.0\nQQ_BOTS=[]\nPORT=8080\n'
    env_file.write_text(original, encoding="utf-8")

    replaced = qq_login.merge_qq_bots_env(env_file, "10001", "new-secret")

    assert replaced is True
    text = env_file.read_text(encoding="utf-8")
    payload = text.split("QQ_BOTS='\n", 1)[1].split("\n'", 1)[0]
    assert json.loads(payload)[0]["id"] == "10001"
    assert json.loads(payload)[0]["secret"] == "new-secret"
    assert "HOST=0.0.0.0" in text and "PORT=8080" in text
    assert (tmp_path / ".env.bak").read_text(encoding="utf-8") == original


def test_run_login_polls_decrypts_and_updates_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("QQ_BOTS=[]\n", encoding="utf-8")
    captured: dict[str, str] = {}

    def create(key: str) -> dict[str, object]:
        captured["key"] = key
        return {"retcode": 0, "data": {"task_id": "task/1"}}

    def poll(task_id: str) -> dict[str, object]:
        assert task_id == "task/1"
        key = base64.b64decode(captured["key"])
        nonce = b"abcdefghijkl"
        encrypted = nonce + AESGCM(key).encrypt(nonce, b"bound-secret", None)
        return {
            "retcode": 0,
            "data": {
                "status": 2,
                "bot_appid": "20002",
                "bot_encrypt_secret": base64.b64encode(encrypted).decode(),
            },
        }

    monkeypatch.setattr(qq_login, "create_bind_task", create)
    monkeypatch.setattr(qq_login, "poll_bind_result", poll)
    output: list[str] = []

    appid = qq_login.run_login(env_file, timeout=1, interval=0, output=output.append)

    assert appid == "20002"
    assert "task_id=task%2F1" in output[1]
    bots = json.loads(env_file.read_text(encoding="utf-8").split("QQ_BOTS='\n", 1)[1].split("\n'", 1)[0])
    assert bots[0]["token"] == "bound-secret"


def test_run_login_reports_expired_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(qq_login, "create_bind_task", lambda key: {"retcode": 0, "data": {"task_id": "task"}})
    monkeypatch.setattr(qq_login, "poll_bind_result", lambda task: {"retcode": 0, "data": {"status": 3}})

    with pytest.raises(RuntimeError, match="二维码已过期"):
        qq_login.run_login(tmp_path / ".env", timeout=1, interval=0)
