"""Pure rules for first path and sub-profession selection."""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content, resolve_content_key


def path_records(content: ContentBundle | None = None) -> list[dict[str, Any]]:
    bundle = content or bundled_content()
    records = bundle.list("path", include_locked=True)
    _validate_path_records(bundle, records)
    return [
        record
        for record in records
        if record.get("status") in {"active", "open"}
    ]


def path_name(path_key: str, content: ContentBundle | None = None) -> str:
    bundle = content or bundled_content()
    path_records(bundle)
    path = bundle.get("path", path_key, include_locked=False)
    if path is None:
        raise ContentError(f"unknown active path: {path_key}")
    name = path.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ContentError(f"path {path_key} has no display name")
    return name.strip()


def resolve_path(value: str, content: ContentBundle | None = None) -> str | None:
    bundle = content or bundled_content()
    path_records(bundle)
    try:
        return resolve_content_key(bundle, "path", value, include_locked=False)
    except ContentError:
        raise
    except ValueError:
        return None


def subprofession_records(
    path_key: str = "support",
    content: ContentBundle | None = None,
) -> list[dict[str, Any]]:
    bundle = content or bundled_content()
    path_records(bundle)
    path = bundle.get("path", path_key, include_locked=False)
    if path is None:
        raise ContentError(f"unknown active path: {path_key}")
    records = path.get("subprofessions")
    if not isinstance(records, list):
        if records is None and path_key != "support":
            return []
        raise ContentError(f"path {path_key} subprofessions must be a list")
    if path_key == "support" and not records:
        raise ContentError("path support subprofessions must not be empty")
    return records


def subprofession_name(
    subprofession_key: str,
    path_key: str = "support",
    content: ContentBundle | None = None,
) -> str:
    for record in subprofession_records(path_key, content):
        if record["key"] == subprofession_key:
            return record["name"].strip()
    raise ContentError(f"unknown sub-profession: {subprofession_key}")


def resolve_subprofession(
    value: str,
    path_key: str = "support",
    content: ContentBundle | None = None,
) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    matches = []
    for record in subprofession_records(path_key, content):
        selectors = (record["key"], record["name"].strip(), *record.get("aliases", []))
        if normalized in selectors:
            matches.append(record["key"])
    if len(matches) > 1:
        raise ContentError(f"ambiguous sub-profession: {value}")
    return matches[0] if matches else None


def reward_items(
    path_key: str,
    subprofession_key: str | None,
    content: ContentBundle | None = None,
) -> tuple[tuple[str, int], ...]:
    bundle = content or bundled_content()
    path_records(bundle)
    path = bundle.get("path", path_key, include_locked=False)
    if path is None:
        raise ContentError(f"unknown active path: {path_key}")
    skill_key = path.get("active_skill")
    if not isinstance(skill_key, str) or not bundle.has("skill", skill_key, include_locked=False):
        raise ContentError(f"path {path_key} references an unavailable active skill")

    item_rewards = path.get("entry_item_rewards")
    rows = _validated_rewards(item_rewards, path_key, bundle)
    if path_key == "support":
        subprofessions = subprofession_records(path_key, bundle)
        subprofession = next(
            (record for record in subprofessions if record["key"] == subprofession_key),
            None,
        )
        if subprofession is None:
            raise ContentError(f"path {path_key} has no entry rewards for {subprofession_key}")
        rows.extend(
            _validated_rewards(
                subprofession["entry_item_rewards"],
                f"{path_key}.{subprofession_key}",
                bundle,
            )
        )
    elif subprofession_key is not None:
        raise ContentError(f"path {path_key} cannot select a sub-profession")
    return (*rows[:1], (skill_key, 1), *rows[1:])


def _validate_path_records(
    bundle: ContentBundle,
    records: list[dict[str, Any]],
) -> None:
    selectors: dict[str, str] = {}
    for path in records:
        key = path.get("key")
        name = path.get("name")
        desc = path.get("desc")
        status = path.get("status")
        aliases = path.get("aliases")
        if not isinstance(key, str) or not key.strip():
            raise ContentError("path record has no stable key")
        if not isinstance(name, str) or not name.strip():
            raise ContentError(f"path {key} has no display name")
        if not isinstance(desc, str) or not desc.strip():
            raise ContentError(f"path {key} has no description")
        if not isinstance(status, str) or not status.strip():
            raise ContentError(f"path {key} has no status")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(f"path {key} aliases must be a string list")
        for selector in (key, name.strip(), *aliases):
            if selector in selectors:
                raise ContentError(
                    f"ambiguous path selector {selector!r}: "
                    f"{selectors[selector]} and {key}"
                )
            selectors[selector] = key

        active_skill = path.get("active_skill")
        if (
            not isinstance(active_skill, str)
            or not active_skill.strip()
            or not bundle.has("skill", active_skill, include_locked=False)
        ):
            raise ContentError(f"path {key} references an unavailable active skill")
        _validated_rewards(path.get("entry_item_rewards"), key, bundle)

        subprofessions = path.get("subprofessions")
        if subprofessions is None:
            if key == "support":
                raise ContentError("path support subprofessions must be a list")
            continue
        if key != "support":
            raise ContentError(f"path {key} cannot define subprofessions")
        if not isinstance(subprofessions, list):
            raise ContentError(f"path {key} subprofessions must be a list")
        if key == "support" and not subprofessions:
            raise ContentError("path support subprofessions must not be empty")
        _validate_subprofession_records(bundle, key, subprofessions)


def _validate_subprofession_records(
    bundle: ContentBundle,
    path_key: str,
    records: list[Any],
) -> None:
    selectors: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ContentError(f"path {path_key} has an invalid sub-profession")
        key = record.get("key")
        name = record.get("name")
        aliases = record.get("aliases")
        rewards = record.get("entry_item_rewards")
        if not isinstance(key, str) or not key.strip():
            raise ContentError(f"path {path_key} has a sub-profession without a key")
        if not isinstance(name, str) or not name.strip():
            raise ContentError(f"sub-profession {key} has no display name")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(f"sub-profession {key} aliases must be a string list")
        for selector in (key, name.strip(), *aliases):
            if selector in selectors:
                raise ContentError(
                    f"ambiguous sub-profession selector {selector!r}: "
                    f"{selectors[selector]} and {key}"
                )
            selectors[selector] = key
        _validated_rewards(rewards, f"{path_key}.{key}", bundle)


def _validated_rewards(
    rewards: Any,
    owner: str,
    bundle: ContentBundle,
) -> list[tuple[str, int]]:
    if not isinstance(rewards, list):
        raise ContentError(f"{owner} entry_item_rewards must be a list")
    rows: list[tuple[str, int]] = []
    for reward in rewards:
        if not isinstance(reward, dict):
            raise ContentError(f"{owner} has an invalid entry item reward")
        item_key = reward.get("item_key")
        quantity = reward.get("quantity")
        if (
            not isinstance(item_key, str)
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ContentError(f"{owner} has an invalid entry item reward")
        if not bundle.has("item", item_key, include_locked=False):
            raise ContentError(f"{owner} rewards an unavailable item: {item_key}")
        rows.append((item_key, quantity))
    return rows


__all__ = [
    "path_name",
    "path_records",
    "resolve_path",
    "resolve_subprofession",
    "reward_items",
    "subprofession_name",
    "subprofession_records",
]
