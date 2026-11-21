"""One SQLite transaction owns both participants' consent and settlement."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentError
from ..persistence.errors import OperationResultMalformedError
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import change_player_state
from ..partner_cultivation_content import dual_cultivation_definition, personal_gain, validate_definition


class DualCultivationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class DualCultivationRepositoryMixin:
    async def dual_cultivation(self, *, platform: str, platform_user_id: str,
                               action: str, reference: str = "", operation_id: str = "") -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._dual_cultivation_once, platform, platform_user_id,
                                           action, reference.strip(), operation_id)

    def _dual_snapshot(self, invitation: Any) -> dict[str, Any]:
        try:
            snapshot = decode_json_strict(invitation["snapshot_json"])
            rule = validate_definition(snapshot, self._partner_content(), frozen=True)
            if self._request_hash("social.dual.snapshot", rule) != invitation["snapshot_hash"]:
                raise ValueError("snapshot hash mismatch")
            return rule
        except (ValueError, TypeError, KeyError) as exc:
            raise ContentError("partner cultivation snapshot is malformed") from exc

    @staticmethod
    def _dual_used(connection: Any, player_id: int, day: str) -> int:
        return int(connection.execute(
            "SELECT COUNT(*) FROM partner_cultivation_settlements WHERE player_id=? AND quota_day=?",
            (player_id, day),
        ).fetchone()[0])

    def _dual_pair(self, connection: Any, actor: Any, target: Any, rule: dict[str, Any],
                   day: str, *, location: str | None = None,
                   require_open_location: bool = True) -> tuple[Any, list[int]]:
        relation = connection.execute(
            "SELECT * FROM partner_relations WHERE status='active' AND "
            "((player_a_id=? AND player_b_id=?) OR (player_a_id=? AND player_b_id=?))",
            (actor["id"], target["id"], target["id"], actor["id"]),
        ).fetchone()
        if relation is None:
            raise DualCultivationError("RELATION")
        content = self._partner_content()
        place = str(actor["location_key"])
        if place != target["location_key"] or (location is not None and place != location) or (
            place not in rule["allowed_locations"] or (
                require_open_location and content.get("location", place, include_locked=False) is None
            )
        ):
            raise DualCultivationError("LOCATION")
        gains = []
        for player in (actor, target):
            if player["status"] != "active" or player["endgame_status"] in {
                "ascension_ready", "ascended", "remained_in_world"
            }:
                raise DualCultivationError("PLAYER")
            if self._has_active_long_action(connection, int(player["id"])):
                raise DualCultivationError("BUSY")
            gain = personal_gain(player, rule, content)
            if gain <= 0:
                raise DualCultivationError("PROGRESSION")
            if any(player[key] < cost for key, cost in rule["cost"].items()):
                raise DualCultivationError("COST")
            if self._dual_used(connection, int(player["id"]), day) >= rule["daily_limit"]:
                raise DualCultivationError("QUOTA")
            gains.append(gain)
        return relation, gains

    def _dual_payload(self, connection: Any, invitation: Any, *, status: str | None = None) -> dict[str, Any]:
        rule = self._dual_snapshot(invitation)
        names = [connection.execute("SELECT dao_name FROM players WHERE id=?", (invitation[key],)).fetchone()[0]
                 for key in ("initiator_id", "invitee_id")]
        return {
            "invitation_id": invitation["invitation_id"], "status": status or invitation["status"],
            "initiator": names[0], "invitee": names[1], "location_key": invitation["location_key"],
            "expires_at": invitation["expires_at"], "cost_each": rule["cost"],
            "snapshot_hash": invitation["snapshot_hash"],
        }

    def _dual_replay(self, connection: Any, payload: dict[str, Any], actor: Any,
                     operation_id: str) -> dict[str, Any]:
        invitation = connection.execute(
            "SELECT * FROM partner_cultivation_invitations WHERE invitation_id=? AND (initiator_id=? OR invitee_id=?)",
            (payload.get("invitation_id"), actor["id"], actor["id"]),
        ).fetchone()
        if invitation is None:
            raise OperationResultMalformedError("partner cultivation operation has no invitation")
        expected = self._dual_payload(connection, invitation, status=payload.get("status"))
        if payload.get("status") == "settled":
            stored = decode_json_strict(invitation["result_json"])
            settlements = connection.execute(
                "SELECT player_id,operation_id,cost_json,gain,before_json,after_json "
                "FROM partner_cultivation_settlements WHERE invitation_id=? ORDER BY player_id",
                (invitation["invitation_id"],),
            ).fetchall()
            expected_players = {int(invitation["initiator_id"]), int(invitation["invitee_id"])}
            gains = {"initiator": None, "invitee": None}
            expected_ledger = set()
            for settlement in settlements:
                player_id = int(settlement["player_id"])
                if player_id not in expected_players or settlement["operation_id"] != operation_id:
                    raise OperationResultMalformedError("partner cultivation settlement identity is invalid")
                if decode_json_strict(settlement["cost_json"]) != self._dual_snapshot(invitation)["cost"]:
                    raise OperationResultMalformedError("partner cultivation settlement cost differs from snapshot")
                before = decode_json_strict(settlement["before_json"])
                after = decode_json_strict(settlement["after_json"])
                if any(type(value) is not int or value < 0 for value in (*before.values(), *after.values())):
                    raise OperationResultMalformedError("partner cultivation settlement values are invalid")
                player = connection.execute("SELECT id FROM players WHERE id=?", (player_id,)).fetchone()
                if player is None or set(before) != {"spirit_stones", "energy", "cultivation", "total_cultivation"} or set(after) != set(before):
                    raise OperationResultMalformedError("partner cultivation settlement values are malformed")
                gain = int(settlement["gain"])
                is_initiator = player_id == int(invitation["initiator_id"])
                gains["initiator" if is_initiator else "invitee"] = gain
                expected_after = {
                    "spirit_stones": before["spirit_stones"] - int(self._dual_snapshot(invitation)["cost"]["spirit_stones"]),
                    "energy": before["energy"] - int(self._dual_snapshot(invitation)["cost"]["energy"]),
                    "cultivation": before["cultivation"] + gain,
                    "total_cultivation": before["total_cultivation"] + gain,
                }
                if after != expected_after or gain <= 0:
                    raise OperationResultMalformedError("partner cultivation settlement delta is malformed")
                for key, old_value in before.items():
                    new_value = after[key]
                    amount = abs(new_value - old_value)
                    expected_ledger.add((player_id, "currency" if key == "spirit_stones" else "resource",
                                         key, "credit" if new_value > old_value else "debit", amount,
                                         old_value, new_value, str(invitation["invitation_id"])))
            ledger = connection.execute(
                "SELECT player_id,asset_kind,asset_key,direction,amount,before_value,after_value,source_id "
                "FROM economy_ledger_entries WHERE operation_id=? AND reason='partner_cultivation'",
                (operation_id,),
            ).fetchall()
            actual_ledger = {tuple(row) for row in ledger}
            if (stored != payload or len(settlements) != 2 or len(ledger) != 8
                    or {int(row["player_id"]) for row in settlements} != expected_players
                    or gains != stored.get("gains") or actual_ledger != expected_ledger):
                raise OperationResultMalformedError("partner cultivation settlement is incomplete")
            expected["gains"] = stored.get("gains")
        if payload != expected or payload.get("status") not in {"invited", "settled", "expired", "rejected", "cancelled"}:
            raise OperationResultMalformedError("partner cultivation operation result is malformed")
        return dict(payload, idempotent_replay=True)

    def _dual_cultivation_once(self, platform: str, platform_user_id: str, action: str,
                               reference: str, operation_id: str) -> dict[str, Any]:
        if action not in {"preview", "status", "invite", "accept", "reject", "cancel"}:
            raise ValueError("unsupported partner cultivation action")
        now = self._now()
        now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
        now_text, day = serialize_datetime(now), now.date().isoformat()
        operation_name = f"social.dual.{action}"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id, "reference": reference,
        })
        with self._connect() as connection:
            connection.execute("BEGIN" if action in {"preview", "status"} else "BEGIN IMMEDIATE")
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            if action in {"preview", "status"}:
                return self._dual_status(connection, actor, day, now_text)
            replay = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(actor["id"]))
            if replay is not None:
                return self._dual_replay(connection, replay, actor, operation_id)
            if action == "invite":
                self._require_player(connection, platform, platform_user_id)
                rule = dual_cultivation_definition(self._partner_content())
                if rule["status"] != "active":
                    raise DualCultivationError("CLOSED")
                target = connection.execute("SELECT * FROM players WHERE dao_name=? AND dao_name<>''", (reference,)).fetchone()
                if target is None:
                    raise DualCultivationError("TARGET")
                if actor["id"] == target["id"]:
                    raise DualCultivationError("SELF")
                relation, _ = self._dual_pair(connection, actor, target, rule, day)
                connection.execute(
                    "UPDATE partner_cultivation_invitations SET status='expired', updated_at=? "
                    "WHERE relation_id=? AND status='invited' AND expires_at<=?",
                    (now_text, relation["relation_id"], now_text),
                )
                if connection.execute(
                    "SELECT 1 FROM partner_cultivation_invitations WHERE relation_id=? AND status='invited'",
                    (relation["relation_id"],),
                ).fetchone():
                    raise DualCultivationError("PENDING")
                invitation_id = f"dual-{uuid4().hex}"
                connection.execute(
                    "INSERT INTO partner_cultivation_invitations VALUES (?,?,?,?,?,'invited',?,?,?,?,?,NULL)",
                    (invitation_id, relation["relation_id"], actor["id"], target["id"], actor["location_key"],
                     now_text, serialize_datetime(now + timedelta(seconds=rule["invitation_ttl_seconds"])),
                     now_text, _json(rule), self._request_hash("social.dual.snapshot", rule)),
                )
                invitation = connection.execute(
                    "SELECT * FROM partner_cultivation_invitations WHERE invitation_id=?", (invitation_id,),
                ).fetchone()
                payload = self._dual_payload(connection, invitation)
            else:
                invitation = connection.execute(
                    "SELECT * FROM partner_cultivation_invitations WHERE invitation_id=? AND (initiator_id=? OR invitee_id=?)",
                    (reference, actor["id"], actor["id"]),
                ).fetchone()
                if invitation is None:
                    raise DualCultivationError("NOT_FOUND")
                owner = "initiator_id" if action == "cancel" else "invitee_id"
                if invitation[owner] != actor["id"]:
                    raise DualCultivationError("PERMISSION")
                rule = self._dual_snapshot(invitation)
                if invitation["status"] != "invited" and invitation["status"] != "expired":
                    raise DualCultivationError("STATE")
                if invitation["status"] == "expired" or now_text >= invitation["expires_at"]:
                    status = "expired"
                else:
                    status = {"accept": "settled", "reject": "rejected", "cancel": "cancelled"}[action]
                payload = self._dual_payload(connection, invitation, status=status)
                if status == "settled":
                    other_id = invitation["initiator_id"]
                    other = connection.execute("SELECT * FROM players WHERE id=?", (other_id,)).fetchone()
                    relation, gains = self._dual_pair(
                        connection, other, actor, rule, day, location=invitation["location_key"],
                        require_open_location=False,
                    )
                    if relation["relation_id"] != invitation["relation_id"]:
                        raise DualCultivationError("RELATION")
                    for player, gain in zip((other, actor), gains):
                        self._dual_settle_player(connection, player, gain, rule, day, reference, operation_id, now_text)
                    payload["gains"] = {"initiator": gains[0], "invitee": gains[1]}
                connection.execute(
                    "UPDATE partner_cultivation_invitations SET status=?, updated_at=?, result_json=? WHERE invitation_id=?",
                    (status, now_text, _json(payload) if status == "settled" else None, reference),
                )
            record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return dict(payload, idempotent_replay=False)

    @staticmethod
    def _dual_settle_player(connection: Any, player: Any, gain: int, rule: dict[str, Any],
                            day: str, invitation_id: str, operation_id: str, now_text: str) -> None:
        cost = rule["cost"]
        delta = {"spirit_stones": -cost["spirit_stones"], "energy": -cost["energy"],
                 "cultivation": gain, "total_cultivation": gain}
        before = {key: player[key] for key in delta}
        after = {key: before[key] + amount for key, amount in delta.items()}
        change_player_state(connection, player, updated_at=now_text,
                            asset_values={"spirit_stones": delta.pop("spirit_stones")}, value_delta=delta)
        for key, value in before.items():
            amount = after[key] - value
            connection.execute(
                "INSERT INTO economy_ledger_entries(operation_id,player_id,asset_kind,asset_key,reason,direction,"
                "amount,before_value,after_value,source_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, player["id"], "currency" if key == "spirit_stones" else "resource", key,
                 "partner_cultivation", "credit" if amount > 0 else "debit", abs(amount), value, after[key],
                 invitation_id, now_text),
            )
        connection.execute(
            "INSERT INTO partner_cultivation_settlements VALUES (?,?,?,?,?,?,?,?)",
            (invitation_id, player["id"], day, operation_id, _json(cost), gain, _json(before), _json(after)),
        )

    def _dual_status(self, connection: Any, actor: Any, day: str, now_text: str) -> dict[str, Any]:
        rule = dual_cultivation_definition(self._partner_content())
        relation = connection.execute(
            "SELECT * FROM partner_relations WHERE (player_a_id=? OR player_b_id=?) "
            "AND status IN ('active','dissolution_pending') ORDER BY id DESC LIMIT 1", (actor["id"], actor["id"]),
        ).fetchone()
        target = None
        reason = "RELATION"
        if relation is not None:
            target_id = relation["player_b_id"] if relation["player_a_id"] == actor["id"] else relation["player_a_id"]
            target = connection.execute("SELECT * FROM players WHERE id=?", (target_id,)).fetchone()
            try:
                self._dual_pair(connection, actor, target, rule, day)
                reason = "" if rule["status"] == "active" else "CLOSED"
            except DualCultivationError as exc:
                reason = exc.code
        invitations = connection.execute(
            "SELECT * FROM partner_cultivation_invitations WHERE initiator_id=? OR invitee_id=? ORDER BY created_at DESC, rowid DESC LIMIT 5",
            (actor["id"], actor["id"]),
        ).fetchall()
        records = []
        for invitation in invitations:
            status = "expired" if invitation["status"] == "invited" and invitation["expires_at"] <= now_text else invitation["status"]
            record = self._dual_payload(connection, invitation, status=status)
            record["role"] = "initiator" if invitation["initiator_id"] == actor["id"] else "invitee"
            if status == "settled":
                record["gains"] = decode_json_strict(invitation["result_json"])["gains"]
            records.append(record)
        return {"name": rule["name"], "description": rule["desc"], "partner": target["dao_name"] if target else None,
                "eligible": not reason, "reason": reason, "cost_each": rule["cost"],
                "gain": personal_gain(actor, rule, self._partner_content()), "gain_max": rule["gain_max"],
                "locations": [self._partner_content().label("location", key) for key in rule["allowed_locations"]],
                "daily_limit": rule["daily_limit"], "used_today": self._dual_used(connection, int(actor["id"]), day),
                "quota_day": day, "quota_timezone": "UTC", "invitations": records}
