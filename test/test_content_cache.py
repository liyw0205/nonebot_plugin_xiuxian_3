from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import (
    bundled_content,
    clear_bundled_content_cache,
)


def test_bundled_content_is_memoized_and_invalidatable() -> None:
    clear_bundled_content_cache()
    first = bundled_content()
    second = bundled_content()
    assert first is second
    assert first.root == Path.cwd().joinpath("data").resolve()

    route = first.require("dao_route", "route.dao_settlement.guard_world")
    route["bonus"]["value_bp"] = 1
    assert (
        first.require("dao_route", "route.dao_settlement.guard_world")["bonus"]["value_bp"]
        == 1000
    )

    clear_bundled_content_cache()
    third = bundled_content()
    assert third is not first
    assert third.root == first.root
    assert len(third._records) == len(first._records)


def test_explicit_data_dir_bypasses_the_bundled_cache() -> None:
    data_root = Path.cwd() / "data"
    clear_bundled_content_cache()
    first = bundled_content(data_root)
    second = bundled_content(data_root)
    assert first is not second
    assert first.root == second.root
