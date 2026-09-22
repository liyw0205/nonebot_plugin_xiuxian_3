"""Verification of externally signed billing receipts.

The game stores only a receipt digest. Payment secrets and private signing keys
remain in the external billing service.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:  # Optional dependency; deployments without billing keep the feature closed.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - exercised only in minimal deployments
    InvalidSignature = Exception  # type: ignore[misc,assignment]
    Ed25519PublicKey = None  # type: ignore[assignment,misc]


class BillingReceiptError(ValueError):
    """The external receipt is malformed or cannot be verified."""


@dataclass(frozen=True, slots=True)
class BillingReceipt:
    receipt_id: str
    subject: str
    contract_key: str
    amount: int
    currency: str
    issued_at: datetime
    valid_until: datetime | None
    payload_hash: str


def _decode_part(value: str) -> bytes:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise BillingReceiptError("invalid receipt encoding") from exc


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise BillingReceiptError(f"receipt {field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BillingReceiptError(f"receipt {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise BillingReceiptError(f"receipt {field} must include timezone")
    return parsed.astimezone(timezone.utc)


def verify_receipt(token: str, public_key_b64: str) -> BillingReceipt:
    """Verify ``base64url(payload).base64url(signature)`` with Ed25519."""

    if not public_key_b64 or Ed25519PublicKey is None:
        raise BillingReceiptError("billing verification is not configured")
    if not isinstance(token, str) or token.count(".") != 1:
        raise BillingReceiptError("receipt format is invalid")
    payload_part, signature_part = token.split(".", 1)
    payload_bytes = _decode_part(payload_part)
    signature = _decode_part(signature_part)
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BillingReceiptError("receipt payload is invalid") from exc
    if not isinstance(payload, dict):
        raise BillingReceiptError("receipt payload must be an object")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(_decode_part(public_key_b64))
        public_key.verify(signature, canonical)
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise BillingReceiptError("receipt signature is invalid") from exc

    receipt_id = payload.get("receipt_id")
    subject = payload.get("subject")
    contract_key = payload.get("contract_key")
    currency = payload.get("currency")
    amount = payload.get("amount")
    if not all(isinstance(value, str) and value for value in (receipt_id, subject, contract_key, currency)):
        raise BillingReceiptError("receipt identity fields are required")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise BillingReceiptError("receipt amount is invalid")
    if len(receipt_id) > 160 or len(subject) > 320 or len(contract_key) > 160:
        raise BillingReceiptError("receipt identity fields are too long")
    valid_until_value = payload.get("valid_until")
    valid_until = _parse_datetime(valid_until_value, "valid_until") if valid_until_value else None
    return BillingReceipt(
        receipt_id=receipt_id,
        subject=subject,
        contract_key=contract_key,
        amount=amount,
        currency=currency,
        issued_at=_parse_datetime(payload.get("issued_at"), "issued_at"),
        valid_until=valid_until,
        payload_hash=hashlib.sha256(canonical).hexdigest(),
    )


__all__ = ["BillingReceipt", "BillingReceiptError", "verify_receipt"]
