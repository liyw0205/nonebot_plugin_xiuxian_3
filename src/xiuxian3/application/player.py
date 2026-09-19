"""Registration and information use cases for the first playable slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

from ..domain.operation import Operation, OperationRecord, OperationStatus
from ..domain.player import Player
from ..domain.result import Error, ErrorCode, Result
from ..ports.id_generator import IdGenerator
from ..ports.unit_of_work import UnitOfWork


UnitOfWorkFactory = Callable[[], UnitOfWork]


@dataclass(frozen=True, slots=True)
class RegisterPlayerCommand:
    actor_id: str
    operation_id: str
    nickname: str | None = None


@dataclass(frozen=True, slots=True)
class GetPlayerInfoQuery:
    actor_id: str


def _digest(command: RegisterPlayerCommand) -> str:
    payload = json.dumps(
        {"actor_id": command.actor_id, "nickname": command.nickname},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _player_payload(player: Player) -> str:
    value = asdict(player)
    value["status"] = player.status.value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _player_from_payload(payload: str) -> Player:
    value = json.loads(payload)
    return Player.from_mapping(value)


def _result_from_record(record: OperationRecord) -> Result[Player]:
    if record.status is OperationStatus.APPLIED and record.result_payload is not None:
        return Result.success(_player_from_payload(record.result_payload))
    if record.error_code == ErrorCode.CONFLICT.value:
        return Result.failure(Error(ErrorCode.CONFLICT, "该 operation 已被拒绝"))
    return Result.failure(Error(ErrorCode.INTERNAL, "operation 仍在处理中", retryable=True))


class RegisterPlayer:
    def __init__(self, unit_of_work: UnitOfWorkFactory, *, clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    def execute(self, command: RegisterPlayerCommand) -> Result[Player]:
        if not command.actor_id or not command.operation_id:
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "身份和 operation_id 不能为空"))
        nickname = command.nickname or command.actor_id
        if not nickname.strip():
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "昵称不能为空"))
        operation = Operation(
            operation_id=command.operation_id,
            request_type="player.register",
            actor_id=command.actor_id,
            target_id=command.actor_id,
            input_digest=_digest(command),
            rule_version="player-registration-v1",
        )
        now = self._clock.now()
        with self._unit_of_work() as unit:
            claim = unit.operations.claim(operation, now)
            if claim.replay:
                return _result_from_record(claim.record)
            existing = unit.players.get_by_external_id(command.actor_id)
            if existing is not None:
                ended = self._clock.now()
                unit.operations.complete(
                    OperationRecord(
                        operation=operation,
                        status=OperationStatus.REJECTED,
                        started_at=claim.record.started_at,
                        ended_at=ended,
                        error_code=ErrorCode.CONFLICT.value,
                    )
                )
                return Result.failure(Error(ErrorCode.CONFLICT, "该身份已经注册"))
            player = Player.new(
                player_id=self._ids.new_id(),
                external_id=command.actor_id,
                nickname=nickname.strip(),
            )
            unit.players.add(player)
            unit.operations.complete(
                OperationRecord(
                    operation=operation,
                    status=OperationStatus.APPLIED,
                    started_at=claim.record.started_at,
                    ended_at=self._clock.now(),
                    result_digest=hashlib.sha256(_player_payload(player).encode("utf-8")).hexdigest(),
                    result_payload=_player_payload(player),
                )
            )
            return Result.success(player)


class GetPlayerInfo:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def execute(self, query: GetPlayerInfoQuery) -> Result[Player]:
        if not query.actor_id:
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "身份不能为空"))
        with self._unit_of_work() as unit:
            player = unit.players.get_by_external_id(query.actor_id)
        if player is None:
            return Result.failure(Error(ErrorCode.NOT_FOUND, "尚未注册修仙角色"))
        return Result.success(player)