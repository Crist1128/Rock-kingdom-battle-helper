"""核心性格规则初始化。

本模块只负责维护系统运行必需的 30 种性格定义，不插入任何示例精灵、
示例技能或示例状态。它适合在应用启动时执行幂等自检查，也可以作为独立
脚本手动运行。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import StatKey
from app.db.session import SessionLocal
from app.models.static import NatureDefinition

logger = logging.getLogger(__name__)

STAT_KEYS = [
    StatKey.HP,
    StatKey.PHYSICAL_ATTACK,
    StatKey.PHYSICAL_DEFENSE,
    StatKey.MAGIC_ATTACK,
    StatKey.MAGIC_DEFENSE,
    StatKey.SPEED,
]

NATURE_NAME_MAP = {
    StatKey.HP: "生命",
    StatKey.PHYSICAL_ATTACK: "物攻",
    StatKey.PHYSICAL_DEFENSE: "物防",
    StatKey.MAGIC_ATTACK: "魔攻",
    StatKey.MAGIC_DEFENSE: "魔防",
    StatKey.SPEED: "速度",
}


@dataclass(frozen=True)
class NatureSeedRow:
    """单条性格种子数据。"""

    nature_id: str
    nature_name: str
    positive_stat: str
    positive_multiplier: float
    negative_stat: str
    negative_multiplier: float
    neutral_multiplier: float


@dataclass(frozen=True)
class NatureSeedResult:
    """性格初始化执行结果。"""

    expected_count: int
    created: int
    updated: int
    restored: int

    @property
    def changed(self) -> bool:
        """本次是否实际修改了数据库。"""
        return self.created > 0 or self.updated > 0 or self.restored > 0


def build_core_nature_rows() -> list[NatureSeedRow]:
    """生成正式核心规则所需的 30 种性格定义。"""
    rows: list[NatureSeedRow] = []
    for positive in STAT_KEYS:
        for negative in STAT_KEYS:
            if positive == negative:
                continue
            rows.append(
                NatureSeedRow(
                    nature_id=f"{positive.value}_plus_{negative.value}_minus",
                    nature_name=f"{NATURE_NAME_MAP[positive]}+{NATURE_NAME_MAP[negative]}-",
                    positive_stat=positive.value,
                    positive_multiplier=1.2,
                    negative_stat=negative.value,
                    negative_multiplier=0.9,
                    neutral_multiplier=1.0,
                )
            )
    return rows


def ensure_core_natures(db: Session) -> NatureSeedResult:
    """幂等写入/修正 30 种核心性格定义。

    规则：
    - 不存在则创建；
    - 存在但字段值与核心定义不同则更新；
    - 曾被软删除则恢复；
    - 不删除额外性格，避免破坏用户或后续版本扩展数据。
    """
    created = 0
    updated = 0
    restored = 0
    rows = build_core_nature_rows()

    for row in rows:
        nature = db.get(NatureDefinition, row.nature_id)
        if nature is None:
            db.add(
                NatureDefinition(
                    nature_id=row.nature_id,
                    nature_name=row.nature_name,
                    positive_stat=row.positive_stat,
                    positive_multiplier=row.positive_multiplier,
                    negative_stat=row.negative_stat,
                    negative_multiplier=row.negative_multiplier,
                    neutral_multiplier=row.neutral_multiplier,
                )
            )
            created += 1
            continue

        field_changed = False
        for field in (
            "nature_name",
            "positive_stat",
            "positive_multiplier",
            "negative_stat",
            "negative_multiplier",
            "neutral_multiplier",
        ):
            next_value = getattr(row, field)
            if getattr(nature, field) != next_value:
                setattr(nature, field, next_value)
                field_changed = True

        if nature.deleted_at is not None:
            nature.deleted_at = None
            restored += 1

        if field_changed:
            updated += 1

    return NatureSeedResult(
        expected_count=len(rows),
        created=created,
        updated=updated,
        restored=restored,
    )


def ensure_core_natures_with_session() -> NatureSeedResult:
    """创建数据库会话并执行核心性格自检查。"""
    db = SessionLocal()
    try:
        result = ensure_core_natures(db)
        if result.changed:
            db.commit()
            logger.info(
                "Core natures ensured: expected=%s created=%s updated=%s restored=%s",
                result.expected_count,
                result.created,
                result.updated,
                result.restored,
            )
        else:
            db.rollback()
            logger.info("Core natures already up to date: expected=%s", result.expected_count)
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    """命令行入口：手动补齐核心性格定义。"""
    result = ensure_core_natures_with_session()
    print(
        "Core natures ensured: "
        f"expected={result.expected_count}, "
        f"created={result.created}, "
        f"updated={result.updated}, "
        f"restored={result.restored}"
    )


if __name__ == "__main__":
    main()
