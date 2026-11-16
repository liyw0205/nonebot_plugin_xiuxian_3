"""Run the bounded performance correctness and comparison layers once each.

The caller owns the shared lock and resource limits, for example::

    timeout 360s flock -w 600 /tmp/nonebot-project-validation.lock \
      /bin/bash -lc 'ulimit -v 4194304; /home/nonebot-shared-venv/bin/python \
      scripts/performance_validation.py --phase all'

This is a development/test entry point. It never changes Linux installation or
runtime defaults, which remain the repository's ``/root/myenv`` convention.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = "/home/nonebot-shared-venv/bin/python"
CORRECTNESS_TARGETS = (
    "test/test_documentation.py",
    "test/test_player_interaction.py",
    "test/test_content.py",
    "test/test_void_material.py",
    "test/test_arena_season_settlement.py",
    "test/test_stat_integration.py",
    "test/test_stats.py",
    "test/test_stat_rules.py",
    "test/test_breakthrough.py",
    "test/test_bounty_batch.py",
    "test/test_bounty_idle_claims.py",
    "test/test_status_query_performance.py",
    "test/test_performance_regression.py",
)
CORRECTNESS_DESELECT = (
    "test/test_performance_regression.py::test_arena_season_top_n_comparison_preserves_board_and_cleans_fixture",
    "test/test_performance_regression.py::test_player_stats_formula_cache_comparison_preserves_profile_and_cleans_fixture",
)
BENCHMARK_ARGS = (
    "scripts/performance_benchmark.py",
    "--users",
    "100",
    "--batch-size",
    "50",
    "--requests",
    "60",
    "--concurrency",
    "1",
    "10",
    "50",
    "--command",
    "我的状态",
    "--profile-sql",
    "--compare-player-stats-formula-cache",
)


def _python() -> str:
    value = os.getenv("XIUXIAN_TEST_PYTHON", DEFAULT_PYTHON)
    if not Path(value).is_file():
        raise SystemExit(f"test interpreter not found: {value}")
    return value


def _run(label: str, command: list[str], *, env: dict[str, str] | None = None) -> None:
    started = time.perf_counter()
    print(f"[{label}] {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=env)
    elapsed = time.perf_counter() - started
    print(f"[{label}] exit={completed.returncode} elapsed={elapsed:.3f}s", flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("correctness", "performance", "all"),
        default="correctness",
        help="run one layer, or both layers in order",
    )
    args = parser.parse_args()
    interpreter = _python()
    if args.phase in {"correctness", "all"}:
        _run(
            "correctness",
            [
                interpreter,
                "-m",
                "pytest",
                "-q",
                "-m",
                "not performance",
                *CORRECTNESS_TARGETS,
                *(
                    argument
                    for node_id in CORRECTNESS_DESELECT
                    for argument in ("--deselect", node_id)
                ),
            ],
        )
    if args.phase in {"performance", "all"}:
        environment = os.environ.copy()
        environment["XIUXIAN_PERF_PROFILE"] = "1"
        _run("performance", [interpreter, *BENCHMARK_ARGS], env=environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
