"""NoneBot Xiuxian 3 plugin package.

The package keeps the application and persistence layers independent from any
specific adapter. Optional integrations are loaded from ``adapters``.
"""

from .runtime import XiuxianRuntime, create_runtime

try:
    from nonebot.plugin import PluginMetadata

    __plugin_meta__ = PluginMetadata(
        name="修仙 3",
        description="可扩展的修仙文字游戏基础框架",
        usage="发送：开始修仙、寻仙问道、我的状态、修仙改名",
        type="application",
        supported_adapters={"~onebot.v11", "~qq"},
    )
except ImportError:  # pragma: no cover - optional NoneBot dependency
    __plugin_meta__ = None

# Only the NoneBot plugin loader owns matcher activation. Importing the package
# from tests, Web, or CLI code must remain side-effect free.
try:
    from nonebot.plugin.manager import _current_plugin
except ImportError:  # pragma: no cover - optional NoneBot dependency
    _current_plugin = None

if _current_plugin is not None and _current_plugin.get() is not None:
    from .plugin import matcher, matchers, runtime  # noqa: F401,E402

__all__ = ["XiuxianRuntime", "create_runtime"]
