#!/usr/bin/env python3
"""Bind a QQ official bot from the terminal and update a NoneBot .env file."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CREATE_URL = "https://q.qq.com/lite/create_bind_task"
POLL_URL = "https://q.qq.com/lite/poll_bind_result"
CONNECT_URL = (
    "https://q.qq.com/qqbot/openclaw/connect.html"
    "?task_id={task_id}&source=xiuxian&_wv=2"
)
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
        "Chrome/109.0.5414.118 Mobile Safari/537.36"
    ),
    "Origin": "https://q.qq.com",
    "Referer": "https://q.qq.com/",
}
_QQ_BOTS_PREFIX = re.compile(r"(?m)^[ \t]*QQ_BOTS[ \t]*=[ \t]*")


def post_json(url: str, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=HEADERS,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"QQ 接口返回 HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接 QQ 接口：{exc.reason}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("QQ 接口返回格式无效")
    return result


def create_bind_task(key_b64: str, timeout: float = 15.0) -> dict[str, Any]:
    return post_json(CREATE_URL, {"key": key_b64}, timeout)


def poll_bind_result(task_id: str, timeout: float = 15.0) -> dict[str, Any]:
    return post_json(POLL_URL, {"task_id": task_id}, timeout)


def bind_page_url(task_id: str) -> str:
    return CONNECT_URL.format(task_id=quote(str(task_id), safe=""))


def _response_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("QQ 接口返回的 data 格式无效")
    return data


def decrypt_bind_secret(encrypted_b64: str, key_b64: str) -> str:
    try:
        encrypted = base64.b64decode(encrypted_b64, validate=True)
        key = base64.b64decode(key_b64, validate=True)
    except ValueError as exc:
        raise ValueError("绑定密文不是有效的 Base64") from exc
    if len(encrypted) < 29 or len(key) != 32:
        raise ValueError("绑定密文或密钥长度无效")
    nonce, body = encrypted[:12], encrypted[12:]
    try:
        return AESGCM(key).decrypt(nonce, body, None).decode("utf-8")
    except Exception as exc:
        raise ValueError("无法解密 QQ Secret，请重新扫码") from exc


def _assignment_value(text: str) -> tuple[list[dict[str, Any]], tuple[int, int] | None]:
    prefix = _QQ_BOTS_PREFIX.search(text)
    if prefix is None:
        return [], None
    start = prefix.start()
    position = prefix.end()
    if position < len(text) and text[position] in "'\"":
        delimiter = text[position]
        position += 1
        value_start = position
        escaped = False
        while position < len(text):
            char = text[position]
            if delimiter == '"' and char == "\\" and not escaped:
                escaped = True
                position += 1
                continue
            if char == delimiter and not escaped:
                break
            escaped = False
            position += 1
        if position >= len(text):
            raise ValueError("QQ_BOTS 引号未闭合")
        raw = text[value_start:position]
        end = position + 1
        if delimiter == '"':
            try:
                decoded = json.loads('"' + raw + '"')
            except json.JSONDecodeError as exc:
                raise ValueError("QQ_BOTS 双引号值无效") from exc
            raw = decoded
    else:
        value_start = position
        end = text.find("\n", position)
        if end < 0:
            end = len(text)
        raw = text[value_start:end].strip()

    try:
        bots = json.loads(raw.strip() or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("QQ_BOTS 必须是 JSON 对象列表") from exc
    if isinstance(bots, dict):
        bots = [bots]
    if not isinstance(bots, list) or not all(isinstance(item, dict) for item in bots):
        raise ValueError("QQ_BOTS 必须是机器人对象列表")
    return bots, (start, end)


def merge_qq_bots_env(env_file: Path, appid: str, secret: str) -> bool:
    appid = str(appid).strip()
    secret = str(secret).strip()
    if not appid or not secret:
        raise ValueError("绑定结果缺少 AppID 或 Secret")

    env_file = Path(env_file)
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    bots, span = _assignment_value(text)
    selected = next(
        (dict(bot) for bot in bots if str(bot.get("id") or "").strip() == appid),
        None,
    )
    replaced = span is not None
    bot = selected or {"id": appid}
    bot.update({"id": appid, "token": secret, "secret": secret, "use_websocket": True})
    intent = bot.get("intent")
    if not isinstance(intent, dict):
        intent = {}
    intent.update({"c2c_group_at_messages": True, "direct_message": True})
    bot["intent"] = intent
    bots = [bot]

    assignment = "QQ_BOTS='\n" + json.dumps(bots, ensure_ascii=False, indent=2) + "\n'"
    if span is None:
        updated = text.rstrip() + ("\n" if text.strip() else "") + assignment + "\n"
    else:
        updated = text[: span[0]] + assignment + text[span[1] :]
        if not updated.endswith("\n"):
            updated += "\n"

    env_file.parent.mkdir(parents=True, exist_ok=True)
    if env_file.exists():
        shutil.copy2(env_file, env_file.with_name(env_file.name + ".bak"))
    fd, temporary = tempfile.mkstemp(prefix=env_file.name + ".", dir=env_file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, env_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return replaced


def run_login(
    env_file: Path,
    *,
    timeout: float = 600.0,
    interval: float = 2.0,
    output: Callable[[str], None] = print,
) -> str:
    if timeout <= 0:
        raise ValueError("等待时间必须大于 0")
    if interval < 0:
        raise ValueError("轮询间隔不能小于 0")
    key_b64 = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    result = create_bind_task(key_b64)
    if result.get("retcode") != 0:
        raise RuntimeError(str(result.get("msg") or "创建扫码绑定任务失败"))
    data = _response_data(result)
    task_id = str(data.get("task_id") or "")
    if not task_id:
        raise RuntimeError("创建扫码绑定任务失败：响应缺少 task_id")
    output("请使用 QQ 扫描或打开以下链接完成官方机器人授权：")
    output(bind_page_url(task_id))
    output(f"等待授权，最长 {int(timeout)} 秒；完成后会自动更新 {Path(env_file).name}。")

    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        result = poll_bind_result(task_id)
        if result.get("retcode") != 0:
            raise RuntimeError(str(result.get("msg") or "查询绑定结果失败"))
        data = _response_data(result)
        status = str(data.get("status") or "")
        if status == "3":
            raise RuntimeError("二维码已过期，请重新执行 xiu3 login")
        if status == "2":
            appid = str(data.get("bot_appid") or "")
            encrypted = str(data.get("bot_encrypt_secret") or "")
            if not appid or not encrypted:
                raise RuntimeError("绑定结果缺少 AppID 或 Secret")
            secret = decrypt_bind_secret(encrypted, key_b64)
            replaced = merge_qq_bots_env(Path(env_file), appid, secret)
            output(f"QQ 官方机器人 {appid} 授权成功，配置已写入 {env_file}")
            if replaced:
                output("已有 QQ_BOTS 配置已备份为 .env.bak，并更新为本次授权机器人。")
            return appid
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raise TimeoutError("等待 QQ 授权超时，请重新执行 xiu3 login")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QQ 官方机器人扫码授权")
    parser.add_argument("--env", type=Path, default=Path.cwd() / ".env")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args(argv)
    try:
        run_login(args.env, timeout=args.timeout, interval=args.interval)
    except KeyboardInterrupt:
        print("已取消 QQ 授权。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[xiu3] QQ 登录失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
