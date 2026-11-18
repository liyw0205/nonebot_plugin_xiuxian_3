"""Frozen public-delivery requirements and owned settlement evidence."""

from __future__ import annotations

from datetime import datetime

from ..content import ContentError
from ..utils.json_cache import decode_json_strict


def commission_delivery_objective(objective, content=None):
    required = {"key", "type", "label", "commission_key"}
    if set(objective) not in (required, required | {"delivery_evidence"}):
        raise ContentError("mainline commission objective has an invalid shape")
    key = objective.get("commission_key")
    if not isinstance(key, str) or not key.strip():
        raise ContentError("mainline commission objective requires commission_key")
    evidence = objective.get("delivery_evidence")
    if "delivery_evidence" in objective:
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"inputs", "location_key", "fresh_acceptance"}
            or evidence["fresh_acceptance"] is not True
            or not isinstance(evidence["location_key"], str)
            or not evidence["location_key"].strip()
            or not isinstance(evidence["inputs"], dict)
            or not evidence["inputs"]
            or any(not isinstance(k, str) or not k.startswith("item.")
                   or type(v) is not int or v <= 0 for k, v in evidence["inputs"].items())
        ):
            raise ContentError("mainline commission delivery evidence is invalid")
    if content is not None:
        from ..livelihood.rules import town_commission_definitions

        commission = town_commission_definitions(content).get(key)
        if commission is None:
            raise ContentError("mainline objective references an inactive commission")
        if evidence is not None:
            if commission.inputs != evidence["inputs"]:
                raise ContentError("mainline delivery inputs differ from public commission")
            if not content.has("location", evidence["location_key"], include_locked=False):
                raise ContentError("mainline delivery location is not open")
    return dict(objective)


def has_commission_delivery(connection, player_id, objective, baseline, started_at):
    from ..livelihood.commission_repository import CommissionRepositoryMixin

    required = objective["delivery_evidence"]
    player = connection.execute("SELECT player_id FROM players WHERE id=?", (player_id,)).fetchone()
    rows = connection.execute(
        "SELECT cl.*, c.commission_key FROM town_commission_claims cl "
        "JOIN town_commissions c ON c.commission_id=cl.commission_id "
        "WHERE cl.player_id=? AND c.commission_key=? AND cl.status='delivered' "
        "AND cl.delivered_at>=?",
        (player_id, objective["commission_key"], started_at),
    ).fetchall()
    for row in rows:
        accepted = connection.execute(
            "SELECT rowid, result_json FROM operations WHERE operation_id=? AND player_id=? "
            "AND operation_name='livelihood.accept_commission'",
            (row["accept_operation_id"], player_id),
        ).fetchone()
        delivered = connection.execute(
            "SELECT rowid, result_json FROM operations WHERE operation_id=? AND player_id=? "
            "AND operation_name='livelihood.deliver_commission'",
            (row["deliver_operation_id"], player_id),
        ).fetchone()
        if accepted is None or delivered is None:
            raise ValueError("mainline delivery lacks owned commission receipts")
        if accepted["rowid"] <= baseline or row["accepted_at"] < started_at:
            continue
        if delivered["rowid"] <= accepted["rowid"]:
            raise ValueError("mainline commission receipt order is invalid")
        snapshot = CommissionRepositoryMixin._validated_snapshot(
            CommissionRepositoryMixin._snapshot_object(row["snapshot_json"]), claim=True,
        )
        result = decode_json_strict(row["result_json"])
        at_location = True
        for receipt, status in ((accepted, "accepted"), (delivered, "delivered")):
            payload = decode_json_strict(receipt["result_json"])
            CommissionRepositoryMixin._validate_payload(payload, status)
            if (
                payload["player"].get("player_id") != player["player_id"]
                or payload["claim_id"] != row["claim_id"]
                or payload["commission_id"] != row["commission_id"]
                or payload["commission_key"] != objective["commission_key"]
                or snapshot["commission_key"] != objective["commission_key"]
                or payload["inputs"] != snapshot["inputs"]
                or payload["expires_at"] != snapshot["expires_at"]
                or (status == "delivered" and payload["result"] != result)
            ):
                raise ValueError("mainline commission receipt disagrees with claim")
            at_location = at_location and payload["player"].get("location_key") == required["location_key"]
        if (
            snapshot["accepted_at"] != row["accepted_at"]
            or result["delivered_at"] != row["delivered_at"]
        ) or not (
            datetime.fromisoformat(row["accepted_at"])
            <= datetime.fromisoformat(row["delivered_at"])
            < datetime.fromisoformat(snapshot["expires_at"])
        ):
            raise ValueError("mainline delivery is outside the frozen deadline")
        if (
            snapshot["inputs"] == required["inputs"]
            and result["inputs"] == required["inputs"]
            and at_location
        ):
            return True
    return False
