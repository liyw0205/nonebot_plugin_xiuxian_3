from __future__ import annotations

import os

import pytest

from scripts.performance_benchmark import _percentiles


def test_performance_percentiles_are_deterministic_and_bounded() -> None:
    result = _percentiles((1.0, 2.0, 3.0, 4.0))
    assert result.count == 4
    assert result.p50_ms == 2.0
    assert result.p95_ms == 4.0
    assert result.p99_ms == 4.0


@pytest.mark.performance
def test_opt_in_performance_benchmark_contract() -> None:
    if os.getenv("XIUXIAN_RUN_PERF") != "1":
        pytest.skip("set XIUXIAN_RUN_PERF=1 for the bounded temporary SQLite benchmark")
    from scripts.performance_benchmark import _run

    import asyncio

    report = asyncio.run(_run(users=1000, batch_size=250, total_requests=20, levels=(1, 10, 50)))
    assert report["users"] == 1000
    assert report["errors"] == 0
    assert report["temporary_database_cleaned"] is True
    assert not any("TEMP B-TREE" in detail for detail in report["explain_query_plan"]["idle_status"])
    assert not any("SCAN" in detail.upper() for detail in report["explain_query_plan"]["location_daily_travel"])
    assert not any("SCAN QUEST_PROGRESS" in detail.upper() for detail in report["explain_query_plan"]["location_requirement_state"])
    assert not any("SCAN MENTOR_RELATIONS" in detail.upper() for detail in report["explain_query_plan"]["location_requirement_state"])
    assert all(item["latency_ms"]["p99_ms"] >= item["latency_ms"]["p50_ms"] for item in report["levels"])
    assert all(
        set(item["command_errors"]) == {"我的状态", "挂机状态", "主线状态", "移动预览 玄天近郊"}
        and not any(item["command_errors"].values())
        for item in report["levels"]
    )
