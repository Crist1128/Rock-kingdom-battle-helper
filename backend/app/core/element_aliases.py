"""属性名称别名工具。"""

from __future__ import annotations

ELEMENT_ALIASES: dict[str, str] = {
    "普通": "normal",
    "normal": "normal",
    "火": "fire",
    "fire": "fire",
    "水": "water",
    "water": "water",
    "草": "grass",
    "grass": "grass",
    "冰": "ice",
    "ice": "ice",
    "电": "electric",
    "electric": "electric",
    "毒": "poison",
    "poison": "poison",
    "翼": "wing",
    "wing": "wing",
    "地": "earth",
    "土": "earth",
    "earth": "earth",
    "石": "earth",
    "虫": "bug",
    "bug": "bug",
    "龙": "dragon",
    "dragon": "dragon",
    "幽灵": "ghost",
    "幽": "ghost",
    "ghost": "ghost",
    "武": "fighting",
    "fighting": "fighting",
    "机械": "mechanical",
    "mechanical": "mechanical",
    "恶": "dark",
    "dark": "dark",
    "萌": "cute",
    "cute": "cute",
    "幻": "illusion",
    "illusion": "illusion",
    "光": "light",
    "light": "light",
}


def canonical_element_type(value: object) -> str | None:
    """把中英文属性名归一到数据库常用英文值。"""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return ELEMENT_ALIASES.get(raw, raw)


def element_type_matches(left: object, right: object) -> bool:
    """判断两个属性名是否等价，兼容中文 seed 与英文 rocom 数据。"""
    left_value = canonical_element_type(left)
    right_value = canonical_element_type(right)
    return left_value is not None and left_value == right_value
