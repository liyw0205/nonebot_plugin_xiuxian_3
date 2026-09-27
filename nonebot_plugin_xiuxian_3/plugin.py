"""Optional standard NoneBot plugin entry point.

NoneBot installations can load this module explicitly. The import remains
safe in environments where NoneBot is not installed, which is important for
Web/CLI deployments and unit tests.
"""

from __future__ import annotations

from .adapters.nonebot import install
from .runtime import create_runtime

runtime = create_runtime()

try:
    matchers = install(runtime)
    from nonebot import get_driver

    driver = get_driver()
    driver.on_startup(runtime.initialize)
    driver.on_shutdown(runtime.close)
    matcher = matchers[0] if matchers else None
except (ImportError, RuntimeError, ValueError):
    matchers = ()
    matcher = None

__all__ = ["matcher", "matchers", "runtime"]
