"""战斗默认技能与资源初始值。"""

DEFAULT_INITIAL_ENERGY = 10
DEFAULT_COMMON_SKILL_ID = "core_skill_focus_energy"
DEFAULT_COMMON_SKILL_IDS = [DEFAULT_COMMON_SKILL_ID]


def append_default_common_skill_ids(skill_ids: list[str]) -> list[str]:
    """在保持原顺序的前提下追加默认通用技能。"""
    seen: set[str] = set()
    result: list[str] = []
    for skill_id in [*skill_ids, *DEFAULT_COMMON_SKILL_IDS]:
        if skill_id in seen:
            continue
        seen.add(skill_id)
        result.append(skill_id)
    return result
