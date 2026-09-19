"""Empty runtime feature used to prove manifest activation without gameplay."""

from ..bootstrap.manifest import FeatureManifest


def core_manifest() -> FeatureManifest:
    return FeatureManifest(
        feature_id="runtime.core",
        display_name="Runtime core",
        required_ports=("clock", "random", "ids"),
    )