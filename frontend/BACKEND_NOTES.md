# 建议后端补充项

## 本次联调已补齐

本次后端已补齐 P0/P1 中不依赖公式的主要接口：己方配置软删除、精灵可学习技能、战斗列表、事件作废/修正、重放占位、结束/归档、快照详情、候选证据占位。下面原始清单保留为需求背景，其中真实重放、候选证据和规则库写接口仍需后续完善。


本前端可以在当前后端上运行，但为了完整支撑 MVP 体验，建议后续补充以下后端接口或字段。

## P0：己方配置删除接口

本版前端已经在“己方配置管理”页增加删除按钮，并会调用：

```http
DELETE /api/v1/player-builds/{build_id}
```

但你当前上传的后端代码里还没有这个接口。未补后端前，前端点击删除会提示“后端当前还没有 DELETE 接口”。

建议实现软删除，不建议物理删除配置主体，避免后续历史战斗引用 build_id 时断链。

建议改动：

### `backend/app/services/player_build_service.py`

```python
from app.db.base import utc_now

# class PlayerElfBuildService 内新增：
def delete_build(self, build_id: str) -> None:
    build = self.db.get(PlayerElfBuild, build_id)
    if build is None or build.deleted_at is not None:
        raise LookupError(f"己方配置不存在：{build_id}")

    build.deleted_at = utc_now()
    self.db.commit()
```

如你希望删除技能槽行，也可以在 commit 前增加：

```python
self.db.execute(delete(PlayerElfBuildSkill).where(PlayerElfBuildSkill.build_id == build_id))
```

### `backend/app/api/v1/endpoints/player_builds.py`

```python
@router.delete("/{build_id}", status_code=204)
def delete_player_build(
    build_id: str,
    db: Session = Depends(get_db),
) -> None:
    try:
        PlayerElfBuildService(db).delete_build(build_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

## P0：精灵可学习技能接口

本版前端在“新建/编辑己方配置”时会优先调用：

```http
GET /api/v1/elves/{elf_id}/skills?q=&limit=500&offset=0
```

用途：

- 选中精灵后，技能槽优先展示该精灵可学习技能。
- 敌方详情页后续可展示可能技能池。
- 候选技能组和真实推算后续可直接复用。

你当前数据库已经有 `elf_learnable_skill`，但最新后端代码还没有公开这个接口。未补后端前，前端会自动退回全局技能搜索，并在技能槽上显示提示。

建议改动：

### `backend/app/api/v1/endpoints/elves.py`

```python
from app.models.static import ElfDefinition, ElfLearnableSkill, SkillDefinition
from app.schemas.static import ElfDefinitionOut, SkillDefinitionOut

@router.get("/{elf_id}/skills", response_model=list[SkillDefinitionOut])
def list_elf_learnable_skills(
    elf_id: str,
    q: str | None = Query(default=None, description="按 skill_name 模糊搜索"),
    limit: int = Query(default=100, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
) -> list[SkillDefinition]:
    elf = db.get(ElfDefinition, elf_id)
    if elf is None or elf.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Elf not found")

    stmt = (
        select(SkillDefinition)
        .join(ElfLearnableSkill, SkillDefinition.skill_id == ElfLearnableSkill.skill_id)
        .where(
            ElfLearnableSkill.elf_id == elf_id,
            SkillDefinition.deleted_at.is_(None),
        )
    )
    if q:
        stmt = stmt.where(SkillDefinition.skill_name.contains(q))

    stmt = stmt.order_by(SkillDefinition.skill_name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())
```

## P0：战斗列表接口

当前没有 `GET /api/v1/battles`，前端只能用 localStorage 记录最近创建/访问的 battle_id。

建议新增：

```http
GET /api/v1/battles?phase=&limit=50&offset=0
```

返回 `BattleOut[]`，按 `updated_at` 或 `created_at` 倒序。

## P0：事件作废与修正接口

当前 `battle_event` 已有 `corrected_event_id`、`is_voided` 字段，但缺少 API。

建议新增：

```http
POST /api/v1/battles/{battle_id}/events/{event_id}/void
POST /api/v1/battles/{battle_id}/events/{event_id}/correct
POST /api/v1/battles/{battle_id}/replay-from/{event_id}
```

前端已经在事件日志页预留入口，但不会调用不存在的 API。

## P1：战斗结束 / 归档接口

建议新增：

```http
POST /api/v1/battles/{battle_id}/finish
POST /api/v1/battles/{battle_id}/archive
```

## P1：快照详情接口

时间线返回了 `snapshot_id`，但当前没有直接读取快照详情的公开 API。

建议新增：

```http
GET /api/v1/battles/{battle_id}/snapshots/{snapshot_id}
```

## P1：候选证据链接口

当前候选摘要和详情已有，但缺少按事件查看候选保留/排除原因的接口。

建议新增：

```http
GET /api/v1/candidates/{battle_id}/{elf_id}/evidence
```

在真实公式未实现前，返回 `formula_unavailable` 即可，不要伪造排除原因。

## P1：规则库输出字段优化

当前前端已兼容 `element_types_json` 字符串。后续可以考虑在后端输出聚合字段：

```json
{
  "element_types": ["fire"],
  "skill_icon": "https://...",
  "damage_rule": {"status": "formula_unavailable"}
}
```

这样可以减少前端重复解析 JSON 字符串。

## P1：规则库写接口

前端 MVP 目前将规则库做成只读页。后续如需要维护规则库，可增加精灵、技能、状态、性格的写接口。

## 管理更新接口说明

当前新增的 `/api/v1/admin/data-updates/rocom/*` 已在后端存在，但前端普通用户页面不调用，原因是：

- 需要 `X-Admin-Token`。
- 不应把 `ADMIN_UPDATE_TOKEN` 写死在公开前端代码中。
- 数据更新更适合作为开发者/管理后台功能。
