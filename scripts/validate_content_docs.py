#!/usr/bin/env python3
"""Validate xiuxian3 versioned game-content documentation.

This validator intentionally checks high-value release contracts rather than
attempting to parse all Markdown prose as a complete content DSL. It protects
version identifiers, required headers, local links, known cross-domain gates,
and the endgame's documented reachability.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONTENT_FILES = sorted(DOCS.rglob("content-v*.md"))
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
CONTENT_NAME = re.compile(r"content-v0\.([1-6])\.md$")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def check_content_headers(errors: list[str]) -> None:
    if len(CONTENT_FILES) != 121:
        fail(errors, f"expected 121 versioned content files, found {len(CONTENT_FILES)}")
    for path in CONTENT_FILES:
        match = CONTENT_NAME.search(path.name)
        if match is None:
            fail(errors, f"unparseable content filename: {path.relative_to(ROOT)}")
            continue
        version = match.group(1)
        text = path.read_text(encoding="utf-8")
        if "版本内容开发合同" not in text:
            fail(errors, f"missing development contract: {path.relative_to(ROOT)}")
        expected = f"content-0.{version}"
        accepted_version_forms = (
            f"content_version={expected}",
            f"`content_version`：`{expected}`",
            f"content_version: {expected}",
        )
        if not any(form in text for form in accepted_version_forms):
            fail(errors, f"wrong/missing content_version={expected}: {path.relative_to(ROOT)}")
        if "rule_version" not in text:
            fail(errors, f"missing rule_version: {path.relative_to(ROOT)}")


def check_links(errors: list[str]) -> None:
    for path in sorted(DOCS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0] if raw_target.strip() else ""
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            local_target = target.split("#", 1)[0]
            if not local_target:
                continue
            resolved = (path.parent / local_target).resolve()
            if resolved.is_dir():
                resolved /= "README.md"
            if not resolved.exists() or (DOCS not in resolved.parents and resolved != DOCS):
                fail(errors, f"broken local link: {path.relative_to(ROOT)} -> {target}")


def require(errors: list[str], relative: str, *terms: str) -> None:
    text = read(relative)
    for term in terms:
        if term not in text:
            fail(errors, f"{relative}: missing required term {term!r}")


def check_release_contracts(errors: list[str]) -> None:
    require(
        errors,
        "docs/extensions/content/content-v0.1.md",
        "open_realms: [mortal, qi_sensing, qi_gathering, foundation]",
        "registered_placeholders: [golden_core, nascent_soul]",
        "location_placeholder",
    )
    require(
        errors,
        "docs/foundation/player/content-v0.1.md",
        "`stage_key`",
        "`status_key=suspended`",
        "`content_version`：`content-0.1`",
        "skill.body.heavy_strike",
        "skill.support.quick_assessment",
    )
    require(
        errors,
        "docs/foundation/items/content-v0.1.md",
        "item.mat.wood",
        "item.array.gathering_basic",
        "item.food.spirit_rice",
        "item.cave_pass_basic",
    )
    require(
        errors,
        "docs/foundation/items/content-v0.2.md",
        "item.pill.core_condense",
        "item.array.mist_barrier",
    )
    require(
        errors,
        "docs/foundation/items/content-v0.3.md",
        "item.pill.soul_condense",
        "item.pill.soul_restore",
        "item.array.boundary_gate",
    )
    require(
        errors,
        "docs/foundation/items/content-v0.5.md",
        "item.void_power_crystal",
        "item.array.void_route",
        "item.array.time_accelerator",
    )
    require(errors, "docs/foundation/items/content-v0.6.md", "item.tribulation_guard")
    require(
        errors,
        "docs/gameplay/events/content-v0.2.md",
        "quest.demon_intro",
        "quest.beast_intro",
    )
    require(
        errors,
        "docs/gameplay/events/content-v0.3.md",
        "quest.rebuild_path",
        "quest.demon_main_1",
        "quest.break_void_intro",
    )
    require(
        errors,
        "docs/gameplay/events/content-v0.4.md",
        "quest.soul_transformation",
        "item.domain_core_fragment",
    )
    require(
        errors,
        "docs/gameplay/events/content-v0.5.md",
        "quest.break_void",
        "task.archive_fragment.alpha",
        "task.archive_fragment.beta",
        "task.archive_fragment.gamma",
    )
    require(
        errors,
        "docs/gameplay/events/content-v0.6.md",
        "quest.dao_union",
        "task.dao_origin.guard",
        "task.dao_origin.build",
        "task.dao_origin.teach",
        "resource.ascension_merit",
    )
    require(errors, "docs/gameplay/world/content-v0.6.md", "location.final_arena")
    if "season.final_arena" in read("docs/gameplay/world/content-v0.6.md"):
        fail(errors, "world v0.6 still uses season.final_arena as a location")


def check_monotonicity_and_endgame(errors: list[str]) -> None:
    require(errors, "docs/gameplay/social/content-v0.3.md", "成员上限 80", "队伍上限 5")
    require(errors, "docs/gameplay/social/content-v0.4.md", "成员上限保持 80", "队伍上限保持 5")
    require(errors, "docs/gameplay/social/content-v0.5.md", "成员上限 120")
    require(
        errors,
        "docs/extensions/content/content-v0.6.md",
        "三试炼 + 三道源任务合计道果 1000",
        "resource.ascension_merit` 1000",
        "task.dao_origin.guard",
    )
    require(
        errors,
        "docs/foundation/stats/content-v0.6.md",
        "resource.dao_fruit_progress",
        "resource.tribulation_debt",
        "resource.ascension_merit",
    )


def check_ten_layer_and_scope(errors: list[str]) -> None:
    require(
        errors,
        "docs/foundation/progression/layers.md",
        "realm_key + realm_layer",
        "层数 1–3 为 `entry`（入门）",
        "4–6 为 `stable`（稳固）",
        "7–9 为 `perfect`（圆满）",
        "10 为 `hunyuan`（混元）",
        "只有 L10 可创建跨境突破",
        "不得要求高于当前境界 L10 累计值的额外无限刷修为",
    )
    require(
        errors,
        "docs/foundation/progression/content-v0.1.md",
        "L1–L10",
        "L10 混元",
        "progression.advance_layer",
        "L9 不可突破而 L10 可预览",
    )
    require(
        errors,
        "docs/foundation/progression/content-v0.6.md",
        "渡劫 L10",
        "不能直接跳过 L10",
        "resource.dao_fruit_progress>=1,000",
    )

    forbidden_stage_files = [
        path
        for path in DOCS.rglob("*.md")
        if path not in {
            DOCS / "foundation/progression/layers.md",
            DOCS / "foundation/progression/model.md",
        }
        and "realm_stage" in path.read_text(encoding="utf-8")
    ]
    for path in forbidden_stage_files:
        fail(errors, f"legacy realm_stage reference outside migration docs: {path.relative_to(ROOT)}")

    entertainment_dir = DOCS / "extensions/entertainment"
    if entertainment_dir.exists():
        fail(errors, "entertainment documentation directory must not exist")
    for path in CONTENT_FILES:
        if "entertainment" in path.parts:
            fail(errors, f"entertainment content package must not exist: {path.relative_to(ROOT)}")

    livelihood_root = DOCS / "gameplay/livelihood"
    for version in range(1, 7):
        relative = f"docs/gameplay/livelihood/content-v0.{version}.md"
        if not (ROOT / relative).exists():
            fail(errors, f"missing livelihood content package: {relative}")
    require(
        errors,
        "docs/gameplay/livelihood/content-v0.1.md",
        "所有 `mortal`、`seeker` 与 `cultivator` 均可参与",
        "禁止写入 `realm_cultivation`、`total_cultivation`、突破准备度",
        "residence.town_room",
        "town_commission.herb_supply",
    )
    require(
        errors,
        "docs/extensions/content/content-v0.1.md",
        "livelihood",
        "经营结果不得写入修为或突破准备度",
    )


def check_legacy_boundary(errors: list[str]) -> None:
    require(
        errors,
        "docs/reference-sources.md",
        "明确禁止直接继承",
        "上游境界名称",
        "上游命令名称",
        "上游 SQLite 表结构",
    )


def check_missing_systems(errors: list[str]) -> None:
    required_packages = {
        "docs/gameplay/routine": (
            "道历问安",
            "ritual.makeup.daily",
            "ritual.spirit_tree.harvest",
            "dao_contract.monthly",
            "gacha.fate.basic",
            "pass.wayfaring.v0.1",
            "quest.seven_day.v0.1",
            "redemption.code",
        ),
        "docs/gameplay/adventures": (
            "斗法留影",
            "bounty.herb_supply",
            "instance.secret_realm.mist_grotto",
            "story.mainline.xuantian",
            "combat.replay",
        ),
        "docs/foundation/advancement": (
            "progression.retreat.basic",
            "talent.tree.body",
            "constitution.profile",
            "skill.basic_attack",
            "item.tempering.basic_weapon",
            "item.refinement.basic_weapon",
        ),
        "docs/gameplay/companions": (
            "灵兽",
            "灵骑",
            "beast.wood_rat",
            "mount.bamboo_deer",
            "beast.gear.sack_small",
            "mount.tack.bamboo_saddle",
        ),
    }
    for directory, terms in required_packages.items():
        relative = f"{directory}/content-v0.1.md"
        require(errors, relative, *terms)
        for version in range(1, 7):
            path = ROOT / directory / f"content-v0.{version}.md"
            if not path.exists():
                fail(errors, f"missing content package: {path.relative_to(ROOT)}")

    require(
        errors,
        "docs/gameplay/routine/content-v0.1.md",
        "补录道历",
        "灵木聚财",
        "日/周/月道契",
        "机缘寻宝",
        "问道行卷",
        "功业录",
        "七日入道",
        "机缘密令",
        "运营奖励不得发放修为或突破物",
    )
    require(
        errors,
        "docs/gameplay/adventures/content-v0.1.md",
        "悬赏榜",
        "秘境试炼",
        "主线道途",
        "斗法留影",
        "首通唯一键",
    )
    require(
        errors,
        "docs/foundation/advancement/content-v0.1.md",
        "闭关修行",
        "体质根性",
        "道脉天书",
        "神通参悟",
        "法器祭炼",
        "灵纹重铸的随机词条池",
    )
    require(
        errors,
        "docs/gameplay/companions/content-v0.6.md",
        "beast.evolution.dao",
        "mount.evolution.dao",
        "ENDGAME_ASSET_FORBIDDEN",
    )


def main() -> int:
    errors: list[str] = []
    check_content_headers(errors)
    check_links(errors)
    check_release_contracts(errors)
    check_monotonicity_and_endgame(errors)
    check_ten_layer_and_scope(errors)
    check_legacy_boundary(errors)
    check_missing_systems(errors)
    if errors:
        print("CONTENT DOCUMENT VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "content document validation: ok "
        f"({len(CONTENT_FILES)} content files; links, headers, release gates, and endgame closure)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
