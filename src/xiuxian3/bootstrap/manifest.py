"""Declarative feature manifests and collision-safe activation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


class ManifestError(ValueError):
    """Raised when feature declarations cannot be activated safely."""


@dataclass(frozen=True, slots=True)
class FeatureContext:
    """Stable, deliberately small context available to feature hooks."""

    feature_id: str


Hook = Callable[[FeatureContext], None]


@dataclass(frozen=True, slots=True)
class FeatureManifest:
    feature_id: str
    display_name: str
    commands: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    permission: str = "user"
    config_flag: str | None = None
    migration_version: int | None = None
    task_ids: tuple[str, ...] = ()
    web_routes: tuple[str, ...] = ()
    required_ports: tuple[str, ...] = ()
    enabled_by_default: bool = True
    on_start: Hook | None = None
    on_stop: Hook | None = None

    def __post_init__(self) -> None:
        if not self.feature_id or not self.display_name:
            raise ManifestError("feature_id and display_name are required")
        if self.permission not in {"user", "group", "admin", "superuser"}:
            raise ManifestError(f"unsupported permission: {self.permission}")
        if self.migration_version is not None and self.migration_version < 0:
            raise ManifestError("migration_version cannot be negative")
        command_keys = tuple(_key(value) for value in (*self.commands, *self.aliases))
        if len(command_keys) != len(set(command_keys)):
            raise ManifestError(f"duplicate command or alias in feature: {self.feature_id}")
        task_keys = tuple(_key(value) for value in self.task_ids)
        if len(task_keys) != len(set(task_keys)):
            raise ManifestError(f"duplicate task id in feature: {self.feature_id}")

    @property
    def command_keys(self) -> tuple[str, ...]:
        return tuple(_key(value) for value in (*self.commands, *self.aliases))


def _key(value: str) -> str:
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        raise ManifestError("commands, aliases and task IDs cannot be empty")
    return normalized


class FeatureRegistry:
    """Collect manifests before startup and activate each one at most once."""

    def __init__(
        self,
        enabled_flags: dict[str, bool] | None = None,
        available_ports: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._enabled_flags = enabled_flags or {}
        self._available_ports = frozenset(available_ports or ())
        self._manifests: dict[str, FeatureManifest] = {}
        self._activated: list[str] = []
        self._sealed = False

    def register(self, manifest: FeatureManifest) -> None:
        if self._sealed:
            raise ManifestError("feature registry is sealed")
        if manifest.feature_id in self._manifests:
            raise ManifestError(f"duplicate feature id: {manifest.feature_id}")
        missing_ports = set(manifest.required_ports) - self._available_ports
        if missing_ports:
            raise ManifestError(
                f"feature {manifest.feature_id} requires unavailable ports: "
                f"{', '.join(sorted(missing_ports))}"
            )
        self._check_unique(manifest)
        self._manifests[manifest.feature_id] = manifest

    def register_many(self, manifests: Iterable[FeatureManifest]) -> None:
        for manifest in manifests:
            self.register(manifest)

    def _check_unique(self, candidate: FeatureManifest) -> None:
        existing_commands = {
            key
            for manifest in self._manifests.values()
            for key in manifest.command_keys
        }
        for command in candidate.command_keys:
            if command in existing_commands:
                raise ManifestError(f"command or alias collision: {command}")
        existing_tasks = {
            _key(task_id)
            for manifest in self._manifests.values()
            for task_id in manifest.task_ids
        }
        for task_id in candidate.task_ids:
            if _key(task_id) in existing_tasks:
                raise ManifestError(f"task id collision: {task_id}")

    def activate(self) -> tuple[str, ...]:
        self._sealed = True
        for manifest in self._manifests.values():
            if not self._is_enabled(manifest) or manifest.feature_id in self._activated:
                continue
            if manifest.on_start is not None:
                manifest.on_start(FeatureContext(manifest.feature_id))
            self._activated.append(manifest.feature_id)
        return tuple(self._activated)

    def deactivate(self) -> tuple[str, ...]:
        for feature_id in reversed(self._activated):
            manifest = self._manifests[feature_id]
            if manifest.on_stop is not None:
                manifest.on_stop(FeatureContext(feature_id))
        activated = tuple(self._activated)
        self._activated.clear()
        return activated

    def _is_enabled(self, manifest: FeatureManifest) -> bool:
        if manifest.config_flag is None:
            return manifest.enabled_by_default
        return self._enabled_flags.get(manifest.config_flag, manifest.enabled_by_default)

    @property
    def manifests(self) -> tuple[FeatureManifest, ...]:
        return tuple(self._manifests.values())

    @property
    def activated(self) -> tuple[str, ...]:
        return tuple(self._activated)