"""Registration and information use cases for the first playable slice."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Callable

from ..domain.operation import Operation, OperationConflictError, OperationRecord, OperationStatus
from ..domain.player import Player
from ..domain.result import Error, ErrorCode, Result
from ..ports.id_generator import IdGenerator
from ..ports.random_source import RandomSource
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


@dataclass(frozen=True, slots=True)
class CreatePlayerCommand:
    platform: str
    platform_user_id: str
    scene: str
    nickname: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class StartSeekingCommand:
    player_id: str
    spirit_root: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class CompleteIntroCommand:
    player_id: str
    guide_key: str
    service_key: str | None
    operation_id: str


def _digest(command: RegisterPlayerCommand) -> str:
    payload = json.dumps(
        {"actor_id": command.actor_id, "nickname": command.nickname},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _create_digest(command: CreatePlayerCommand) -> str:
    payload = json.dumps(
        {
            "platform": command.platform,
            "platform_user_id": command.platform_user_id,
            "scene": command.scene,
            "nickname": command.nickname,
        },
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


class CreatePlayer:
    """Create only the new-user identity mapping required by the v0.1 contract."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, *, clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    def execute(self, command: CreatePlayerCommand) -> Result[Player]:
        if not command.platform or not command.platform_user_id or not command.operation_id:
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "平台、用户身份和 operation_id 不能为空"))
        if not command.scene or not command.nickname.strip():
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "场景和昵称不能为空"))
        operation = Operation(
            operation_id=command.operation_id,
            request_type="player.create",
            actor_id=f"{command.platform}:{command.platform_user_id}",
            target_id=f"{command.platform}:{command.platform_user_id}",
            input_digest=_create_digest(command),
            rule_version="player-onboarding-v0.1.0",
        )
        with self._unit_of_work() as unit:
            try:
                claim = unit.operations.claim(operation, self._clock.now())
            except OperationConflictError:
                return Result.failure(Error(ErrorCode.CONFLICT, "该 operation 已被不同请求占用"))
            if claim.replay:
                return _result_from_record(claim.record)
            existing = unit.players.get_by_platform_identity(
                command.platform,
                command.platform_user_id,
            )
            if existing is not None:
                payload = _player_payload(existing)
                unit.operations.complete(
                    OperationRecord(
                        operation=operation,
                        status=OperationStatus.APPLIED,
                        started_at=claim.record.started_at,
                        ended_at=self._clock.now(),
                        result_digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                        result_payload=payload,
                    )
                )
                return Result.success(existing)
            player = Player.new_identity(
                player_id=self._ids.new_id(),
                platform=command.platform,
                platform_user_id=command.platform_user_id,
                scene=command.scene,
                nickname=command.nickname.strip(),
            )
            unit.players.add(player)
            payload = _player_payload(player)
            unit.operations.complete(
                OperationRecord(
                    operation=operation,
                    status=OperationStatus.APPLIED,
                    started_at=claim.record.started_at,
                    ended_at=self._clock.now(),
                    result_digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    result_payload=payload,
                )
            )
            return Result.success(player)


class StartSeeking:
    """Run the one-time qualification ceremony and onboarding reward."""

    VALID_ROOTS = frozenset({"metal", "wood", "water", "fire", "earth"})
    QUALIFICATION_KEYS = ("body", "spirit", "insight", "root", "agility", "fortune")

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock,
        random_source: RandomSource,
        ids: IdGenerator | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._random = random_source
        self._ids = ids

    def get_player(self, player_id: str) -> Player:
        with self._unit_of_work() as unit:
            player = unit.players.get_by_player_id(player_id)
        if player is None:
            raise LookupError(player_id)
        return player

    def execute(self, command: StartSeekingCommand) -> Result[Player]:
        if command.spirit_root not in self.VALID_ROOTS or not command.operation_id:
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "灵根倾向或 operation_id 无效"))
        operation = Operation(
            operation_id=command.operation_id,
            request_type="player.start_seeking",
            actor_id=command.player_id,
            target_id=command.player_id,
            input_digest=hashlib.sha256(
                json.dumps(
                    {"player_id": command.player_id, "spirit_root": command.spirit_root},
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            rule_version="player-onboarding-v0.1.0",
        )
        with self._unit_of_work() as unit:
            try:
                claim = unit.operations.claim(operation, self._clock.now())
            except OperationConflictError:
                return Result.failure(Error(ErrorCode.CONFLICT, "该 operation 已被不同请求占用"))
            if claim.replay:
                return _result_from_record(claim.record)
            player = unit.players.get_by_player_id(command.player_id)
            if player is None:
                return Result.failure(Error(ErrorCode.NOT_FOUND, "角色不存在"))
            if player.stage != "new_user":
                return Result.failure(Error(ErrorCode.SEEKING_ALREADY_DONE, "角色已经完成寻仙问道"))

            values = {key: 5 for key in self.QUALIFICATION_KEYS}
            remaining = 30
            while remaining:
                available = [key for key in self.QUALIFICATION_KEYS if values[key] < 15]
                key = available[self._random.randbelow(len(available))]
                values[key] += 1
                remaining -= 1
            result_digest = hashlib.sha256(
                json.dumps(values, sort_keys=True).encode("utf-8")
            ).hexdigest()
            snapshot_id = (
                self._ids.new_id()
                if self._ids is not None
                else f"qualification:{command.operation_id}"
            )
            snapshot = {
                "snapshot_id": snapshot_id,
                "player_id": player.player_id,
                "spirit_root": command.spirit_root,
                **values,
                "random_pool": "qualification.v0.1",
                "result_digest": result_digest,
                "operation_id": command.operation_id,
                "rule_version": "player-onboarding-v0.1.0",
            }
            unit.players.add_qualification_snapshot(snapshot)
            updated = replace(
                player,
                stage="mortal",
                spirit_stones=100,
                stamina=30,
                energy=30,
                inventory_json=json.dumps(
                    {
                        "item.food.coarse_spirit_rice": 3,
                        "item.herb.blood_grass": 3,
                    },
                    sort_keys=True,
                ),
                qualification_snapshot_id=snapshot_id,
            )
            unit.players.update(updated)
            payload = _player_payload(updated)
            unit.operations.complete(
                OperationRecord(
                    operation=operation,
                    status=OperationStatus.APPLIED,
                    started_at=claim.record.started_at,
                    ended_at=self._clock.now(),
                    result_digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    result_payload=payload,
                )
            )
            return Result.success(updated)


class CompleteIntro:
    """Complete one mortal onboarding guide item, then enter seeker."""

    GUIDE_KEYS = frozenset({"read_world", "gather_blood_grass", "choose_service"})
    SERVICE_KEYS = frozenset({"alchemy", "artifice", "formation"})

    def __init__(self, unit_of_work: UnitOfWorkFactory, *, clock, random_source: RandomSource) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._random = random_source

    def execute(self, command: CompleteIntroCommand) -> Result[Player]:
        if command.guide_key not in self.GUIDE_KEYS or not command.operation_id:
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "引导键或 operation_id 无效"))
        if command.guide_key == "choose_service" and command.service_key not in self.SERVICE_KEYS:
            return Result.failure(Error(ErrorCode.INVALID_INPUT, "教学服务无效"))
        operation = Operation(
            operation_id=command.operation_id,
            request_type="player.complete_intro",
            actor_id=command.player_id,
            target_id=command.player_id,
            input_digest=hashlib.sha256(
                json.dumps(
                    {
                        "player_id": command.player_id,
                        "guide_key": command.guide_key,
                        "service_key": command.service_key,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            rule_version="player-onboarding-v0.1.0",
        )
        with self._unit_of_work() as unit:
            try:
                claim = unit.operations.claim(operation, self._clock.now())
            except OperationConflictError:
                return Result.failure(Error(ErrorCode.CONFLICT, "该 operation 已被不同请求占用"))
            if claim.replay:
                return _result_from_record(claim.record)
            player = unit.players.get_by_player_id(command.player_id)
            if player is None:
                return Result.failure(Error(ErrorCode.NOT_FOUND, "角色不存在"))
            if player.stage != "mortal":
                return Result.failure(Error(ErrorCode.PLAYER_STAGE_CONFLICT, "当前阶段不能完成凡人引导"))
            guide_state = json.loads(player.guide_state_json or "{}")
            if command.guide_key in guide_state:
                updated = player
            else:
                inventory = json.loads(player.inventory_json or "{}")
                stamina = player.stamina
                energy = player.energy
                if command.guide_key == "gather_blood_grass":
                    if stamina < 2:
                        return Result.failure(Error(ErrorCode.INSUFFICIENT_RESOURCE, "体力不足"))
                    stamina -= 2
                    inventory["item.herb.blood_grass"] = inventory.get("item.herb.blood_grass", 0) + 1 + self._random.randbelow(2)
                elif command.guide_key == "choose_service":
                    if energy < 2:
                        return Result.failure(Error(ErrorCode.INSUFFICIENT_RESOURCE, "精力不足"))
                    energy -= 2
                    guide_state["service_key"] = command.service_key
                guide_state[command.guide_key] = True
                stage = "seeker" if all(guide_state.get(key) for key in self.GUIDE_KEYS) else player.stage
                updated = replace(
                    player,
                    stage=stage,
                    stamina=stamina,
                    energy=energy,
                    inventory_json=json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    guide_state_json=json.dumps(guide_state, ensure_ascii=False, sort_keys=True),
                )
                unit.players.update(updated)
            payload = _player_payload(updated)
            unit.operations.complete(
                OperationRecord(
                    operation=operation,
                    status=OperationStatus.APPLIED,
                    started_at=claim.record.started_at,
                    ended_at=self._clock.now(),
                    result_digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    result_payload=payload,
                )
            )
            return Result.success(updated)


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
            try:
                claim = unit.operations.claim(operation, now)
            except OperationConflictError:
                return Result.failure(Error(ErrorCode.CONFLICT, "该 operation 已被不同请求占用"))
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
            player = unit.players.get_by_platform_identity("onebot_v11", query.actor_id)
            if player is None:
                player = unit.players.get_by_external_id(query.actor_id)
        if player is None:
            return Result.failure(Error(ErrorCode.NOT_FOUND, "尚未注册修仙角色"))
        return Result.success(player)