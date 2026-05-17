"""
洛克王国 BWIKI 爬虫数据清洗模块。

本模块只依赖 Python 标准库，负责把爬虫产出的 raw JSON 转换为后端
静态规则表可以直接导入的数据；历史 CSV 输入仅作为兼容入口保留：

- elf_definition
- skill_definition
- elf_learnable_skill
- type_effectiveness_rule

设计原则：
1. 清洗逻辑和数据库写入分离，便于离线审阅、回滚和测试。
2. MVP 阶段不下载/依赖图片；如提供 urls.csv，可把远程图片 URL 作为 avatar/skill_icon 元数据。
3. 不根据技能描述臆造完整公式，只写入 formula_unavailable 或 non_damage 占位规则。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_SOURCE = "biligame_rocom_bwiki"

ELEMENT_NAME_MAP: dict[str, str] = {
    "普通": "normal",
    "火": "fire",
    "水": "water",
    "草": "grass",
    "电": "electric",
    "冰": "ice",
    "翼": "wing",
    "地": "earth",
    "幽": "ghost",
    "恶": "dark",
    "光": "light",
    "毒": "poison",
    "武": "fighting",
    "机械": "mechanical",
    "萌": "cute",
    "虫": "bug",
    "龙": "dragon",
    "幻": "illusion",
}

SKILL_CATEGORY_MAP: dict[str, str] = {
    "物攻": "physical",
    "魔攻": "magic",
    "状态": "status",
    # 后端枚举目前没有 defense，防御类技能按 status 入库，并保留 raw_category/tags。
    "防御": "status",
}

STAT_FIELD_MAP = {
    "hp": "base_hp_talent",
    "atk": "base_physical_attack_talent",
    "def": "base_physical_defense_talent",
    "sp_atk": "base_magic_attack_talent",
    "sp_def": "base_magic_defense_talent",
    "spd": "base_speed_talent",
}

SPRITE_SKILL_RE = re.compile(
    r"([^;()]+)\(LV(\d+)/([^/]*)/([^/]*)/(-?\d+)/(-?\d+)/(.*?)\)(?:;|$)"
)
EVOLUTION_RE = re.compile(r"([^;()]+)\(([^/]*)/([^)]*)\)")


@dataclass(slots=True)
class CleanedDataset:
    """清洗后的静态规则数据集合。"""

    elves: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    elf_skills: list[dict[str, Any]] = field(default_factory=list)
    type_effectiveness_rules: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_csv_rows(path: str | Path | None) -> list[dict[str, str]]:
    """读取 UTF-8-SIG CSV，空路径或不存在时返回空列表。"""
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def dumps_json(value: Any) -> str:
    """生成后端可读的 JSON 字符串。"""
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def safe_int(value: Any, default: int = 0) -> int:
    """把 CSV 字段安全转换为 int。"""
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def optional_int(value: Any) -> int | None:
    """把 CSV 字段安全转换为可空 int。"""
    text = "" if value is None else str(value).strip()
    if not text or text.lower() == "nan":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_bool(value: Any) -> bool:
    """兼容 bool/字符串/数字的布尔转换。"""
    if isinstance(value, bool):
        return value
    text = "" if value is None else str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "是"}


def normalize_text(value: Any) -> str:
    """清理 CSV 字段中的 NaN、空白和不可见字符。"""
    text = "" if value is None else str(value).strip()
    if text.lower() == "nan":
        return ""
    return re.sub(r"\s+", " ", text)


def split_cn_list(value: Any) -> list[str]:
    """解析逗号分隔的中文列表。"""
    text = normalize_text(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,，]", text) if item.strip()]


def normalize_element(value: Any) -> str:
    """中文属性名转换为后端内部 element_type。未知值保留原文。"""
    text = normalize_text(value)
    return ELEMENT_NAME_MAP.get(text, text)


def normalize_skill_category(value: Any) -> str:
    """中文技能类型转换为后端 SkillCategory 枚举值。"""
    text = normalize_text(value)
    return SKILL_CATEGORY_MAP.get(text, "special" if text else "status")


def short_hash(value: str, length: int = 8) -> str:
    """生成稳定短 hash，用于跨版本保持 ID 可复现。"""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def make_elf_id(row: dict[str, Any]) -> str:
    """生成稳定精灵 ID。编号重复或形态变化时仍可唯一定位。"""
    no = safe_int(row.get("no"), 0)
    name = normalize_text(row.get("name"))
    form = normalize_text(row.get("form"))
    url = normalize_text(row.get("url"))
    identity = f"{no}|{name}|{form}|{url}"
    return f"rocom_elf_{no:04d}_{short_hash(identity, 6)}"


def make_skill_id(skill_name: str) -> str:
    """生成稳定技能 ID。"""
    name = normalize_text(skill_name)
    return f"rocom_skill_{short_hash(name, 10)}"


def display_name(row: dict[str, Any]) -> str:
    """精灵展示名；有形态时使用中文括号拼接。"""
    name = normalize_text(row.get("name"))
    form = normalize_text(row.get("form"))
    return f"{name}（{form}）" if form else name


def parse_sprite_skills(skills_text: Any) -> list[dict[str, Any]]:
    """解析 sprites.csv 中的技能池字符串。"""
    text = normalize_text(skills_text)
    if not text:
        return []
    result: list[dict[str, Any]] = []
    for name, level, attr, category, power, cost, desc in SPRITE_SKILL_RE.findall(text):
        result.append(
            {
                "skill_name": normalize_text(name),
                "skill_id": make_skill_id(name),
                "level": safe_int(level),
                "raw_attribute": normalize_text(attr),
                "element_type": normalize_element(attr),
                "raw_category": normalize_text(category),
                "skill_category": normalize_skill_category(category),
                "base_power": None if safe_int(power) == 0 and category in {"状态", "防御"} else safe_int(power),
                "base_energy_cost": safe_int(cost),
                "description": normalize_text(desc),
            }
        )
    return result


def parse_evolution_chain(value: Any) -> list[dict[str, Any]]:
    """解析进化链字符串，如 喵喵(/);喵呜(16/);魔力猫(32/)。"""
    text = normalize_text(value)
    if not text:
        return []
    chain: list[dict[str, Any]] = []
    previous_name: str | None = None
    for name, level, condition in EVOLUTION_RE.findall(text):
        item = {
            "name": normalize_text(name),
            "evolves_from": previous_name,
            "level": optional_int(level),
            "condition": normalize_text(condition) or None,
        }
        chain.append(item)
        previous_name = item["name"]
    return chain


def build_skill_catalog(skill_rows: list[dict[str, str]], sprite_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """合并 skills.csv 和 sprites.csv 技能池，生成去重技能字典。"""
    catalog: dict[str, dict[str, Any]] = {}

    def upsert_skill(
        *,
        skill_name: str,
        raw_attribute: str,
        raw_category: str,
        power: int | None,
        cost: int,
        description: str,
        data_version: str,
    ) -> None:
        name = normalize_text(skill_name)
        if not name:
            return
        skill_id = make_skill_id(name)
        category = normalize_skill_category(raw_category)
        tags = []
        if raw_category == "防御":
            tags.append("defense")
        if power is None and category in {"physical", "magic"}:
            tags.append("power_missing")

        if category == "physical":
            damage_rule: dict[str, Any] | None = {
                "status": "formula_unavailable",
                "damage_type": "normal_formula",
                "attack_stat": "physical_attack",
                "defense_stat": "physical_defense",
                "power_source": "base_power",
                "raw_description": description,
            }
        elif category == "magic":
            damage_rule = {
                "status": "formula_unavailable",
                "damage_type": "normal_formula",
                "attack_stat": "magic_attack",
                "defense_stat": "magic_defense",
                "power_source": "base_power",
                "raw_description": description,
            }
        else:
            damage_rule = None

        hit_rule = {
            "damage_display_type": "single_damage",
            "runtime_record_strategy": "single_value",
            "source": "cleaner_default",
            "needs_manual_review": True,
        }
        effect_operations = None
        if description and category == "status":
            effect_operations = [{"status": "unparsed", "raw_description": description}]

        catalog[skill_id] = {
            "skill_id": skill_id,
            "skill_name": name,
            "alias_names_json": None,
            "skill_icon": None,
            "element_type": normalize_element(raw_attribute),
            "skill_category": category,
            "base_power": power,
            "base_energy_cost": cost,
            "priority_modifier": 0,
            "tags_json": dumps_json(tags or [raw_category]) if (tags or raw_category) else None,
            "damage_rule_json": dumps_json(damage_rule) if damage_rule else None,
            "hit_rule_json": dumps_json(hit_rule),
            "effect_operations_json": dumps_json(effect_operations) if effect_operations else None,
            "recognition_template_json": None,
            "data_source": DATA_SOURCE,
            "data_version": data_version,
            "raw_attribute": raw_attribute,
            "raw_category": raw_category,
            "raw_description": description,
        }

    data_version = default_data_version()
    for row in skill_rows:
        category = normalize_text(row.get("类型"))
        raw_power = safe_int(row.get("威力"))
        power = None if raw_power == 0 and category in {"状态", "防御"} else raw_power
        upsert_skill(
            skill_name=normalize_text(row.get("技能名")),
            raw_attribute=normalize_text(row.get("属性")),
            raw_category=category,
            power=power,
            cost=safe_int(row.get("耗能")),
            description=normalize_text(row.get("效果描述")),
            data_version=data_version,
        )

    # sprites.csv 里的技能池包含技能等级；如果 skills.csv 缺项，用它补齐技能定义。
    for sprite in sprite_rows:
        for skill in parse_sprite_skills(sprite.get("skills")):
            if skill["skill_id"] not in catalog:
                upsert_skill(
                    skill_name=skill["skill_name"],
                    raw_attribute=skill["raw_attribute"],
                    raw_category=skill["raw_category"],
                    power=skill["base_power"],
                    cost=skill["base_energy_cost"],
                    description=skill["description"],
                    data_version=data_version,
                )
    return catalog


def load_image_refs(url_rows: list[dict[str, str]], image_mode: str = "remote") -> dict[tuple[str, str], str]:
    """读取 urls.csv，按 (name, type) 返回图片引用。"""
    refs: dict[tuple[str, str], str] = {}
    for row in url_rows:
        name = normalize_text(row.get("name"))
        img_type = normalize_text(row.get("type"))
        if not name or not img_type:
            continue
        value = normalize_text(row.get("local_path")) if image_mode == "local" else normalize_text(row.get("url"))
        if value:
            refs.setdefault((name, img_type), value)
    return refs


def build_lineup_usage(lineup_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """从 lineups.csv 汇总每个精灵的常见技能组、性格和天赋分布。"""
    usage: dict[str, dict[str, Any]] = {}
    for row in lineup_rows:
        for index in range(1, 7):
            name = normalize_text(row.get(f"pokemon_{index}"))
            if not name:
                continue
            bucket = usage.setdefault(
                name,
                {
                    "skill_sets": {},
                    "natures": {},
                    "talent_patterns": {},
                    "bloodlines": {},
                    "count": 0,
                },
            )
            bucket["count"] += 1
            skills = [x.strip() for x in normalize_text(row.get(f"skills_{index}")).split(";") if x.strip()]
            if skills:
                key = dumps_json(skills)
                bucket["skill_sets"][key] = bucket["skill_sets"].get(key, 0) + 1
            nature = normalize_text(row.get(f"nature_{index}"))
            if nature:
                bucket["natures"][nature] = bucket["natures"].get(nature, 0) + 1
            talents = [x.strip() for x in normalize_text(row.get(f"talents_{index}")).split(",") if x.strip()]
            if talents:
                key = dumps_json(talents)
                bucket["talent_patterns"][key] = bucket["talent_patterns"].get(key, 0) + 1
            bloodline = normalize_text(row.get(f"bloodline_{index}"))
            if bloodline:
                bucket["bloodlines"][bloodline] = bucket["bloodlines"].get(bloodline, 0) + 1
    return usage


def ranked_usage(counter: dict[str, int], *, json_key: bool = False, limit: int = 10) -> list[dict[str, Any]]:
    """把计数字典转为排序后的 JSON 友好列表。"""
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    result: list[dict[str, Any]] = []
    for key, count in items:
        value: Any = json.loads(key) if json_key else key
        result.append({"value": value, "count": count})
    return result


def lookup_lineup_usage(row: dict[str, Any], usage: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """按形态名和基础名查找配队统计。"""
    candidates = [display_name(row), normalize_text(row.get("name"))]
    for candidate in candidates:
        if candidate in usage:
            return usage[candidate]
    return None


def build_elf_record(
    row: dict[str, Any],
    *,
    image_refs: dict[tuple[str, str], str],
    lineup_usage: dict[str, dict[str, Any]],
    data_version: str,
) -> dict[str, Any]:
    """把 sprites.csv 单行转换为 elf_definition 可导入记录。"""
    attrs_raw = split_cn_list(row.get("attributes"))
    attrs = [normalize_element(x) for x in attrs_raw]
    usage = lookup_lineup_usage(row, lineup_usage)

    common_skill_sets_json = None
    common_natures_json = None
    common_individual_talent_patterns_json = None
    if usage:
        common_skill_sets_json = dumps_json(ranked_usage(usage["skill_sets"], json_key=True))
        common_natures_json = dumps_json(ranked_usage(usage["natures"]))
        common_individual_talent_patterns_json = dumps_json(
            {
                "talent_patterns": ranked_usage(usage["talent_patterns"], json_key=True),
                "bloodlines": ranked_usage(usage["bloodlines"]),
                "sample_count": usage["count"],
            }
        )

    name = normalize_text(row.get("name"))
    avatar = image_refs.get((display_name(row), "sprite")) or image_refs.get((name, "sprite")) or ""
    stats = {target: safe_int(row.get(source)) for source, target in STAT_FIELD_MAP.items()}

    forms_payload = {
        "raw_no": safe_int(row.get("no")),
        "form": normalize_text(row.get("form")) or None,
        "display_name": display_name(row),
        "has_shiny": parse_bool(row.get("has_shiny")),
        "source_url": normalize_text(row.get("url")),
        "raw_attributes": attrs_raw,
        "ability": {
            "name": normalize_text(row.get("ability_name")) or None,
            "description": normalize_text(row.get("ability_desc")) or None,
        },
        "type_matchup": {
            "strong_against": split_cn_list(row.get("strong_against")),
            "weak_to": split_cn_list(row.get("weak_to")),
            "resists": split_cn_list(row.get("resists")),
            "resisted_by": split_cn_list(row.get("resisted_by")),
        },
        "evolution_chain": parse_evolution_chain(row.get("evolution_chain")),
    }

    return {
        "elf_id": make_elf_id(row),
        "elf_name": display_name(row),
        "avatar": avatar,
        "element_types_json": dumps_json(attrs),
        **stats,
        "common_skill_sets_json": common_skill_sets_json,
        "common_natures_json": common_natures_json,
        "common_individual_talent_patterns_json": common_individual_talent_patterns_json,
        "forms_json": dumps_json(forms_payload),
        "recognition_templates_json": None,
        "data_source": DATA_SOURCE,
        "data_version": data_version,
    }


def build_elf_skill_links(sprite_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """生成 elf_learnable_skill 导入记录。"""
    seen: set[tuple[str, str]] = set()
    links: list[dict[str, Any]] = []
    for row in sprite_rows:
        elf_id = make_elf_id(row)
        for skill in parse_sprite_skills(row.get("skills")):
            key = (elf_id, skill["skill_id"])
            if key in seen:
                continue
            seen.add(key)
            links.append(
                {
                    "elf_id": elf_id,
                    "skill_id": skill["skill_id"],
                    "source": DATA_SOURCE,
                    "learn_level": skill["level"],
                    "raw_skill_name": skill["skill_name"],
                }
            )
    return links


def build_type_effectiveness_rules(sprite_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[str]]:
    """从单属性精灵的克制关系中保守推导属性克制规则。"""
    candidates: dict[tuple[str, str], float] = {}
    conflicts: list[str] = []

    def add_rule(attack_cn: str, defense_cn: str, multiplier: float, source: str) -> None:
        attack = normalize_element(attack_cn)
        defense = normalize_element(defense_cn)
        if not attack or not defense:
            return
        key = (attack, defense)
        previous = candidates.get(key)
        if previous is not None and previous != multiplier:
            conflicts.append(
                f"属性克制冲突: {attack}->{defense} 已有 {previous}, 新值 {multiplier}, 来源 {source}"
            )
            return
        candidates[key] = multiplier

    for row in sprite_rows:
        attrs = split_cn_list(row.get("attributes"))
        # 双属性精灵的页面克制关系是复合结果，不用于推导单属性攻击/防御矩阵。
        if len(attrs) != 1:
            continue
        attr = attrs[0]
        source = display_name(row)
        for defense in split_cn_list(row.get("strong_against")):
            add_rule(attr, defense, 2.0, source)
        for defense in split_cn_list(row.get("resisted_by")):
            add_rule(attr, defense, 0.5, source)
        for attack in split_cn_list(row.get("weak_to")):
            add_rule(attack, attr, 2.0, source)
        for attack in split_cn_list(row.get("resists")):
            add_rule(attack, attr, 0.5, source)

    rules = [
        {
            "attack_element_type": attack,
            "defense_element_type": defense,
            "multiplier": multiplier,
            "data_version": default_data_version(),
        }
        for (attack, defense), multiplier in sorted(candidates.items())
    ]
    return rules, conflicts


def default_data_version() -> str:
    """默认数据版本：按 UTC 日期生成。"""
    return "rocom_bwiki_" + datetime.now(UTC).strftime("%Y%m%d")



def raw_sprite_to_row(sprite: dict[str, Any]) -> dict[str, Any]:
    """把爬虫 raw JSON 中的一只精灵转换为 cleaner 内部行结构。"""
    stats = sprite.get("stats") or {}
    ability = sprite.get("ability") or {}
    matchup = sprite.get("type_matchup") or {}

    def skill_str(skill: dict[str, Any]) -> str:
        return (
            f"{normalize_text(skill.get('name'))}("
            f"LV{safe_int(skill.get('level'))}/"
            f"{normalize_text(skill.get('attribute'))}/"
            f"{normalize_text(skill.get('category'))}/"
            f"{safe_int(skill.get('power'))}/"
            f"{safe_int(skill.get('cost'))}/"
            f"{normalize_text(skill.get('description'))})"
        )

    return {
        "no": sprite.get("no", ""),
        "name": sprite.get("name", ""),
        "form": sprite.get("form") or "",
        "url": sprite.get("url", ""),
        "has_shiny": sprite.get("has_shiny", False),
        "attributes": ",".join(sprite.get("attributes") or []),
        "total_stats": stats.get("total", ""),
        "hp": stats.get("hp", ""),
        "atk": stats.get("atk", ""),
        "sp_atk": stats.get("sp_atk", ""),
        "def": stats.get("def", ""),
        "sp_def": stats.get("sp_def", ""),
        "spd": stats.get("spd", ""),
        "ability_name": ability.get("name", ""),
        "ability_desc": ability.get("description", ""),
        "strong_against": ",".join(matchup.get("strong_against") or []),
        "weak_to": ",".join(matchup.get("weak_to") or []),
        "resists": ",".join(matchup.get("resists") or []),
        "resisted_by": ",".join(matchup.get("resisted_by") or []),
        "evolution_chain": ";".join(
            f"{e.get('name', '')}({e.get('level') or ''}/{e.get('condition') or ''})"
            for e in (sprite.get("evolution_chain") or [])
        ),
        "skills": ";".join(skill_str(skill) for skill in (sprite.get("skills") or [])),
    }


def raw_skills_to_catalog_rows(raw_sprites: list[dict[str, Any]]) -> list[dict[str, str]]:
    """从 raw JSON 技能池中提取去重技能行，替代历史 skills.csv。"""
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for sprite in raw_sprites:
        for skill in sprite.get("skills") or []:
            name = normalize_text(skill.get("name"))
            if not name or name in seen:
                continue
            seen.add(name)
            rows.append(
                {
                    "技能名": name,
                    "属性": normalize_text(skill.get("attribute")),
                    "类型": normalize_text(skill.get("category")),
                    "威力": str(safe_int(skill.get("power"))),
                    "耗能": str(safe_int(skill.get("cost"))),
                    "效果描述": normalize_text(skill.get("description")),
                }
            )
    return rows


def clean_from_raw_sprites(
    raw_sprites: list[dict[str, Any]],
    *,
    image_url_rows: list[dict[str, Any]] | None = None,
    lineups_csv: str | Path | None = None,
    data_version: str | None = None,
    image_mode: str = "remote",
) -> CleanedDataset:
    """从爬虫 raw JSON 直接生成后端静态规则导入数据，不依赖任何 CSV。"""
    version = data_version or default_data_version()
    sprite_rows = [raw_sprite_to_row(sprite) for sprite in raw_sprites]
    skill_rows = raw_skills_to_catalog_rows(raw_sprites)
    url_rows = [dict(row) for row in (image_url_rows or [])]
    lineup_rows = read_csv_rows(lineups_csv)

    image_refs = load_image_refs(url_rows, image_mode=image_mode)
    lineup_usage = build_lineup_usage(lineup_rows)
    skill_catalog = build_skill_catalog(skill_rows, sprite_rows)
    for skill in skill_catalog.values():
        skill["data_version"] = version
        skill["skill_icon"] = image_refs.get((skill["skill_name"], "skill"))

    elves = [
        build_elf_record(row, image_refs=image_refs, lineup_usage=lineup_usage, data_version=version)
        for row in sprite_rows
    ]
    elf_skills = build_elf_skill_links(sprite_rows)
    type_rules, conflicts = build_type_effectiveness_rules(sprite_rows)
    for rule in type_rules:
        rule["data_version"] = version

    warnings: list[str] = []
    warnings.extend(conflicts)
    if not sprite_rows:
        warnings.append("未读取到 raw_sprites 数据。")
    if not url_rows:
        warnings.append("未提供 image_url_rows，avatar/skill_icon 将为空。MVP 阶段可接受。")

    return CleanedDataset(
        elves=elves,
        skills=sorted(skill_catalog.values(), key=lambda item: item["skill_name"]),
        elf_skills=elf_skills,
        type_effectiveness_rules=type_rules,
        warnings=warnings,
        stats={
            "raw_sprites": len(raw_sprites),
            "sprites_rows": len(sprite_rows),
            "skills_rows": len(skill_rows),
            "urls_rows": len(url_rows),
            "lineups_rows": len(lineup_rows),
            "elves": len(elves),
            "skills": len(skill_catalog),
            "elf_skills": len(elf_skills),
            "type_effectiveness_rules": len(type_rules),
            "data_version": version,
            "image_mode": image_mode,
            "source_format": "raw_json",
        },
    )

def clean_from_csv(
    *,
    sprites_csv: str | Path,
    skills_csv: str | Path | None = None,
    urls_csv: str | Path | None = None,
    lineups_csv: str | Path | None = None,
    data_version: str | None = None,
    image_mode: str = "remote",
) -> CleanedDataset:
    """从爬虫 CSV 输出生成后端静态规则导入数据。"""
    version = data_version or default_data_version()
    sprite_rows = read_csv_rows(sprites_csv)
    skill_rows = read_csv_rows(skills_csv)
    url_rows = read_csv_rows(urls_csv)
    lineup_rows = read_csv_rows(lineups_csv)

    image_refs = load_image_refs(url_rows, image_mode=image_mode)
    lineup_usage = build_lineup_usage(lineup_rows)
    skill_catalog = build_skill_catalog(skill_rows, sprite_rows)
    # 修正 catalog 内构造时的默认版本，保证 CLI 指定版本能全局一致；同时补充技能图标引用。
    for skill in skill_catalog.values():
        skill["data_version"] = version
        skill["skill_icon"] = image_refs.get((skill["skill_name"], "skill"))

    elves = [
        build_elf_record(row, image_refs=image_refs, lineup_usage=lineup_usage, data_version=version)
        for row in sprite_rows
    ]
    elf_skills = build_elf_skill_links(sprite_rows)
    type_rules, conflicts = build_type_effectiveness_rules(sprite_rows)
    for rule in type_rules:
        rule["data_version"] = version

    warnings: list[str] = []
    warnings.extend(conflicts)
    if not sprite_rows:
        warnings.append(f"未读取到 sprites.csv 数据: {sprites_csv}")
    if not skill_rows:
        warnings.append("未提供或未读取到 skills.csv，已尝试仅根据 sprites.csv 技能池补齐技能定义。")
    if not url_rows:
        warnings.append("未提供或未读取到 urls.csv，avatar/skill_icon 将为空。")

    return CleanedDataset(
        elves=elves,
        skills=sorted(skill_catalog.values(), key=lambda item: item["skill_name"]),
        elf_skills=elf_skills,
        type_effectiveness_rules=type_rules,
        warnings=warnings,
        stats={
            "sprites_rows": len(sprite_rows),
            "skills_rows": len(skill_rows),
            "urls_rows": len(url_rows),
            "lineups_rows": len(lineup_rows),
            "elves": len(elves),
            "skills": len(skill_catalog),
            "elf_skills": len(elf_skills),
            "type_effectiveness_rules": len(type_rules),
            "data_version": version,
            "image_mode": image_mode,
        },
    )


def write_json(path: Path, value: Any) -> None:
    """写入缩进 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_cleaned_dataset(dataset: CleanedDataset, output_dir: str | Path) -> None:
    """把清洗结果写入多个 JSON 文件，便于人工审阅和数据库导入。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "elves.json", dataset.elves)
    write_json(out / "skills.json", dataset.skills)
    write_json(out / "elf_learnable_skills.json", dataset.elf_skills)
    write_json(out / "type_effectiveness_rules.json", dataset.type_effectiveness_rules)
    write_json(out / "import_summary.json", {"stats": dataset.stats, "warnings": dataset.warnings})


def main() -> None:
    """命令行入口：清洗 raw JSON 或历史 CSV，不写数据库。"""
    import argparse

    parser = argparse.ArgumentParser(description="清洗洛克王国 BWIKI 爬虫 raw JSON 为后端可导入 JSON")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--raw-json", help="爬虫产出的 sprites_raw.json，推荐入口")
    source.add_argument("--sprites-csv", help="历史兼容：爬虫产出的 sprites.csv")
    parser.add_argument("--image-urls-json", help="爬虫产出的 image_urls.json")
    parser.add_argument("--skills-csv", help="历史兼容：爬虫产出的 skills.csv")
    parser.add_argument("--urls-csv", help="历史兼容：爬虫产出的 urls.csv")
    parser.add_argument("--lineups-csv", help="配队数据 lineups.csv，可选，用于常见配置统计")
    parser.add_argument("--output-dir", default="data/rocom/cleaned", help="清洗结果输出目录")
    parser.add_argument("--data-version", help="写入 data_version，如 rocom_bwiki_20260516")
    parser.add_argument(
        "--image-mode",
        choices=["remote", "local"],
        default="remote",
        help="图片引用使用远程 URL 还是本地路径；MVP 推荐 remote",
    )
    args = parser.parse_args()

    if args.raw_json:
        raw_sprites = json.loads(Path(args.raw_json).read_text(encoding="utf-8"))
        image_url_rows = []
        if args.image_urls_json and Path(args.image_urls_json).exists():
            image_url_rows = json.loads(Path(args.image_urls_json).read_text(encoding="utf-8"))
        dataset = clean_from_raw_sprites(
            raw_sprites,
            image_url_rows=image_url_rows,
            lineups_csv=args.lineups_csv,
            data_version=args.data_version,
            image_mode=args.image_mode,
        )
    else:
        dataset = clean_from_csv(
            sprites_csv=args.sprites_csv,
            skills_csv=args.skills_csv,
            urls_csv=args.urls_csv,
            lineups_csv=args.lineups_csv,
            data_version=args.data_version,
            image_mode=args.image_mode,
        )

    write_cleaned_dataset(dataset, args.output_dir)
    print(json.dumps({"stats": dataset.stats, "warnings": dataset.warnings[:20]}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
