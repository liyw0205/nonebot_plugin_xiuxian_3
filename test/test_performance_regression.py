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
def test_opt_in_performance_benchmark_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("XIUXIAN_RUN_PERF") != "1":
        pytest.skip("set XIUXIAN_RUN_PERF=1 for the bounded temporary SQLite benchmark")
    monkeypatch.setenv("XIUXIAN_PERF_PROFILE", "1")
    from scripts.performance_benchmark import _run

    import asyncio

    report = asyncio.run(_run(users=1000, batch_size=250, total_requests=20, levels=(1, 10, 50)))
    assert report["users"] == 1000
    assert report["errors"] == 0
    assert report["sql_profile_enabled"] is True
    assert report["sql_profile_status"] == "collected"
    assert report["seed"]["domain_front_rows"] == report["users"]
    assert report["seed"]["arena_matches"] == report["users"]
    assert report["temporary_database_cleaned"] is True
    assert not any("TEMP B-TREE" in detail for detail in report["explain_query_plan"]["idle_status"])
    evidence_plan = " ".join(report["explain_query_plan"]["mainline_evidence"]).upper()
    assert "SCAN DOMAIN_FRONT_PARTICIPANTS" not in evidence_plan
    assert "SCAN DOMAIN_FRONT_CONTRIBUTIONS" not in evidence_plan
    assert "SCAN DOMAIN_FRONT_CLAIMS" not in evidence_plan
    assert "IDX_DOMAIN_FRONT_PARTICIPANTS_PLAYER" in evidence_plan
    assert "IDX_DOMAIN_FRONT_CONTRIBUTIONS_PLAYER" in evidence_plan
    assert "IDX_DOMAIN_FRONT_CLAIMS_PLAYER" in evidence_plan
    assert "IDX_BATTLE_SESSIONS_PLAYER" in evidence_plan
    assert "IDX_VOID_ARCHIVE_UNLOCKS_PLAYER" in evidence_plan
    assert "IDX_TIME_FORT_MEMBER_QUOTA" in evidence_plan
    assert "IDX_LIVELIHOOD_PROJECT_REWARDS_PLAYER" in evidence_plan
    assert "SCAN DOMAIN_FRONT_BATTLE_LINKS" not in evidence_plan
    assert not any("SCAN" in detail.upper() for detail in report["explain_query_plan"]["location_daily_travel"])
    assert not any("SCAN QUEST_PROGRESS" in detail.upper() for detail in report["explain_query_plan"]["location_requirement_state"])
    assert not any("SCAN MENTOR_RELATIONS" in detail.upper() for detail in report["explain_query_plan"]["location_requirement_state"])
    assert all(item["latency_ms"]["p99_ms"] >= item["latency_ms"]["p50_ms"] for item in report["levels"])
    assert all(
        set(item["command_errors"])
        == {"我的状态", "挂机状态", "主线状态", "移动预览 玄天近郊", "竞技场赛季"}
        and not any(item["command_errors"].values())
        for item in report["levels"]
    )
    assert all(item["sql_queries"] > 0 for item in report["levels"])
    assert all(
        item["stage_latency_ms"]["arena_season_board"]["count"] > 0
        for item in report["levels"]
    )


def test_unprofiled_benchmark_does_not_report_zero_sql_queries() -> None:
    import asyncio

    from scripts.performance_benchmark import _run

    report = asyncio.run(
        _run(
            users=8,
            batch_size=8,
            total_requests=20,
            levels=(1,),
            profile_sql=False,
            commands=("主线状态",),
        )
    )
    assert report["sql_profile_enabled"] is False
    assert report["sql_profile_status"] == "not_collected"
    assert report["levels"][0]["sql_queries"] is None
    assert report["levels"][0]["requests"] == 20
    assert report["errors"] == 0


def test_profiled_benchmark_reports_executor_queue_and_workers() -> None:
    import asyncio

    from scripts.performance_benchmark import _run

    report = asyncio.run(
        _run(
            users=8,
            batch_size=8,
            total_requests=12,
            levels=(1, 10),
            profile_sql=True,
            commands=("我的状态",),
        )
    )
    assert report["errors"] == 0
    assert report["temporary_database_cleaned"] is True
    assert all(
        item["executor_queue_wait_ms"]["count"] > 0
        and 1 <= item["executor_worker_count"] <= 8
        and 1 <= item["executor_max_active_workers"] <= item["executor_worker_count"]
        and item["errors"] == 0
        for item in report["levels"]
    )
    assert all(
        item["stage_latency_ms"]["player_stat_snapshot"]["count"] == item["requests"]
        and item["stage_latency_ms"]["player_view_normalization"]["count"] == item["requests"]
        for item in report["levels"]
    )


def test_mainline_prerequisite_comparison_reuses_and_cleans_one_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_mainline_prerequisite_comparison

    report = asyncio.run(
        _run_mainline_prerequisite_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("主线状态",),
        )
    )
    before = report["comparison"]["before_per_stage_preparation"]
    after = report["comparison"]["after_shared_preparation"]
    assert report["errors"] == 0
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is True
    assert after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is True
    assert after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 2
    assert all(item["sql_queries"] > 0 and item["errors"] == 0 for item in before["levels"])
    assert all(item["sql_queries"] > 0 and item["errors"] == 0 for item in after["levels"])


def test_arena_season_comparison_reuses_one_fixture_and_removes_one_history_query() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_arena_season_event_comparison

    report = asyncio.run(
        _run_arena_season_event_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("竞技场赛季",),
        )
    )
    before = report["comparison"]["before_separate_window_history_reads"]
    after = report["comparison"]["after_shared_history_read"]
    assert report["errors"] == 0
    assert before["seed"] == after["seed"]
    assert before["seed"]["arena_matches"] == 8
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is True
    assert after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 2
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["sql_queries"] - new["sql_queries"] >= old["requests"]
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["竞技场赛季"] == new["command_errors"]["竞技场赛季"] == 0


def test_arena_season_cache_comparison_preserves_board_and_cleans_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_arena_season_cache_comparison

    report = asyncio.run(
        _run_arena_season_cache_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("竞技场赛季",),
        )
    )
    before = report["comparison"]["before_without_cache"]
    after = report["comparison"]["after_event_and_board_cache"]
    assert report["errors"] == 0
    assert report["board_outputs_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 2
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["竞技场赛季"] == new["command_errors"]["竞技场赛季"] == 0
        assert old["sql_queries"] >= new["sql_queries"] > 0
        assert old["stage_latency_ms"]["arena_season_board"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["arena_season_board"]["count"] == new["requests"]


def test_arena_season_top_n_comparison_preserves_board_and_cleans_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_arena_season_top_n_comparison

    report = asyncio.run(
        _run_arena_season_top_n_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("竞技场赛季",),
        )
    )
    before = report["comparison"]["before_full_sort_then_slice"]
    after = report["comparison"]["after_top_n_selection"]
    assert report["errors"] == 0
    assert report["board_results_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 2
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["竞技场赛季"] == new["command_errors"]["竞技场赛季"] == 0
        assert old["stage_latency_ms"]["arena_season_board"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["arena_season_board"]["count"] == new["requests"]
        assert old["sql_queries"] > 0 and new["sql_queries"] > 0


def test_player_stats_formula_cache_comparison_preserves_profile_and_cleans_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_player_stats_formula_cache_comparison

    report = asyncio.run(
        _run_player_stats_formula_cache_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("我的状态",),
        )
    )
    before = report["comparison"]["before_uncached_formula"]
    after = report["comparison"]["after_repository_formula_cache"]
    assert report["errors"] == 0
    assert report["profile_results_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 4
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["我的状态"] == new["command_errors"]["我的状态"] == 0
        assert old["stage_latency_ms"]["player_stat_snapshot"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["player_stat_snapshot"]["count"] == new["requests"]
        assert old["stage_latency_ms"]["player_stats_formula"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["player_stats_formula"]["count"] == 0
        # The first variant may open the executor's first SQLite connection;
        # that cold trace contributes one setup statement, not a query-path
        # difference. Keep the profile requirement while allowing that bound.
        assert old["sql_queries"] > 0 and new["sql_queries"] > 0
        assert abs(old["sql_queries"] - new["sql_queries"]) <= 1


def test_player_profile_projection_comparison_reuses_normalization_and_cleans_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_player_profile_projection_comparison

    report = asyncio.run(
        _run_player_profile_projection_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("我的状态",),
        )
    )
    before = report["comparison"]["before_repeated_profile_projection"]
    after = report["comparison"]["after_shared_profile_projection"]
    assert report["errors"] == 0
    assert report["profile_results_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 4
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["我的状态"] == new["command_errors"]["我的状态"] == 0
        assert old["player_value_normalization_calls"] == old["requests"] * 2
        assert new["player_value_normalization_calls"] == new["requests"]
        assert old["sql_queries"] > 0 and new["sql_queries"] > 0
        assert abs(old["sql_queries"] - new["sql_queries"]) <= 1


def test_mainline_player_projection_comparison_reuses_intro_projection() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_mainline_player_projection_comparison

    report = asyncio.run(
        _run_mainline_player_projection_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("主线状态",),
        )
    )
    before = report["comparison"]["before_duplicate_intro_projection"]
    after = report["comparison"]["after_shared_mainline_projection"]
    assert report["errors"] == 0
    assert report["profile_results_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 4
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["主线状态"] == new["command_errors"]["主线状态"] == 0
        assert old["mainline_intro_evidence_decodes"] == old["requests"]
        assert new["mainline_intro_evidence_decodes"] == 0
        assert old["sql_queries"] > 0 and new["sql_queries"] > 0


def test_equipment_definition_cache_comparison_preserves_previews_and_cleans_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_equipment_definition_cache_comparison

    report = asyncio.run(
        _run_equipment_definition_cache_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
        )
    )
    before = report["comparison"]["before_full_definition_build"]
    after = report["comparison"]["after_bundle_identity_cache"]
    assert report["errors"] == 0
    assert report["preview_outputs_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert before["item_records"] > before["equipment_definitions"] > 0
    assert len(before["levels"]) == len(after["levels"]) == 2
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert not any(old["command_errors"].values())
        assert not any(new["command_errors"].values())
        assert old["sql_queries"] == new["sql_queries"] == 0
        assert old["equipment_definition_build_count"] == old["requests"]
        assert new["equipment_definition_build_count"] == 1
        assert old["stage_latency_ms"]["equipment_definition_provider"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["equipment_definition_provider"]["count"] == new["requests"]


def test_void_material_item_cache_comparison_preserves_gate_response_and_cleans_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_void_material_item_cache_comparison

    report = asyncio.run(
        _run_void_material_item_cache_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("寄售物资 虚空晶体 1 100",),
        )
    )
    before = report["comparison"]["before_linear_item_alias_scan"]
    after = report["comparison"]["after_bundle_item_alias_cache"]
    assert report["errors"] == 0
    assert report["item_resolution_outputs_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert before["item_record_count"] > 0
    assert len(before["levels"]) == len(after["levels"]) == 2
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["寄售物资 虚空晶体 1 100"] == new["command_errors"]["寄售物资 虚空晶体 1 100"] == 0
        assert old["item_alias_cache_build_count"] == old["requests"]
        assert new["item_alias_cache_build_count"] == 1
        assert old["stage_latency_ms"]["item_resolution"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["item_resolution"]["count"] == new["requests"]


def test_void_material_item_alias_cache_rebuilds_when_content_bundle_changes() -> None:
    from types import SimpleNamespace

    from nonebot_plugin_xiuxian_3.xiuxian.economy.void_material_use_cases import VoidMaterialApplication

    class ContentStub:
        def __init__(self, items):
            self.items = items

        def list(self, kind, *, include_locked=True):
            assert kind == "item"
            return [dict(item) for item in self.items]

    first = ContentStub([{"key": "item.first", "name": "首物", "aliases": ["一"]}])
    second = ContentStub([{"key": "item.second", "name": "次物", "aliases": ["二"]}])
    repository = SimpleNamespace(content=first)
    application = VoidMaterialApplication(repository)
    assert application._resolve_item("一") == "item.first"
    assert application._resolve_item("二") is None
    assert application._item_alias_cache_build_count == 1
    repository.content = second
    assert application._resolve_item("一") is None
    assert application._resolve_item("二") == "item.second"
    assert application._item_alias_cache_build_count == 2


def test_arena_season_index_comparison_uses_one_clean_fixture() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_arena_season_index_comparison

    report = asyncio.run(
        _run_arena_season_index_comparison(
            users=8,
            batch_size=8,
            total_requests=6,
            levels=(1,),
            profile_sql=True,
            commands=("竞技场赛季",),
        )
    )
    before = report["comparison"]["before_without_covering_index"]
    after = report["comparison"]["after_with_covering_index"]
    assert report["errors"] == 0
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["index_bytes"] == 0
    assert after["index_bytes"] > 0
    assert after["index_build_ms"]
    assert any("SCAN arena_matches" in plan for plan in before["explain_query_plan"]["arena_season_events"])
    assert any(
        "COVERING INDEX IDX_ARENA_MATCHES_SETTLED_EVENTS" in plan.upper()
        for plan in after["explain_query_plan"]["arena_season_events"]
    )
    assert all(
        item["sql_queries"] > 0 and item["errors"] == 0
        for variant in (before, after)
        for item in variant["levels"]
    )


def test_idle_preview_comparison_reuses_one_fixture_and_shared_route_state() -> None:
    import asyncio

    from scripts.performance_benchmark import _run_idle_preview_comparison

    report = asyncio.run(
        _run_idle_preview_comparison(
            users=8,
            batch_size=8,
            total_requests=8,
            levels=(1,),
            profile_sql=True,
            commands=("挂机预览",),
        )
    )
    before = report["comparison"]["before_repeated_route_state_reads"]
    after = report["comparison"]["after_shared_preview_state"]
    assert report["errors"] == 0
    assert report["preview_records_equivalent"] is True
    assert before["seed"] == after["seed"]
    assert before["database_bytes_after_benchmark"] == after["database_bytes_after_benchmark"]
    assert before["temporary_database_cleaned"] is after["temporary_database_cleaned"] is True
    assert before["sql_profile_enabled"] is after["sql_profile_enabled"] is True
    assert len(before["levels"]) == len(after["levels"]) == 2
    assert before["seed"]["idle_preview_history_rows"] == 16
    assert before["seed"]["active_idle_rows_for_preview"] == 0
    assert not any(
        "SCAN IDLE_ASSIGNMENTS" in detail.upper()
        for detail in after["explain_query_plan"]["idle_daily_grouped"]
    )
    for old, new in zip(before["levels"], after["levels"], strict=True):
        assert old["sql_queries"] > new["sql_queries"] > 0
        assert old["errors"] == new["errors"] == 0
        assert old["command_errors"]["挂机预览"] == new["command_errors"]["挂机预览"] == 0
        assert old["stage_latency_ms"]["idle_preview"]["count"] == old["requests"]
        assert new["stage_latency_ms"]["idle_preview"]["count"] == new["requests"]
        assert old["executor_queue_wait_ms"]["count"] >= old["requests"]
        assert new["executor_queue_wait_ms"]["count"] >= new["requests"]
        assert old["executor_worker_count"] > 0
        assert new["executor_worker_count"] > 0


def test_thread_local_connection_reuse_skips_health_probe(tmp_path) -> None:
    import asyncio

    from nonebot_plugin_xiuxian_3.runtime import create_runtime

    async def exercise() -> list[str]:
        runtime = create_runtime(data_dir=tmp_path, adapters=())
        await runtime.initialize()
        connection = runtime.repository._connect()
        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        assert runtime.repository._connect() is connection
        await runtime.close()
        return statements

    assert asyncio.run(exercise()) == []
