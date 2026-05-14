# Rock PVP Helper Backend

这是“洛克王国世界 PVP 战斗信息获取与敌方配置推算系统”的 FastAPI 后端。

当前版本重点完成 **手动输入 MVP 后端闭环**：己方配置、战斗阵容、敌方候选、统一状态实例、伤害事件记录、状态快照和公式占位推算。

## 常用命令

```bash
pip install -e '.[dev]'
python -m app.seed.minimal_seed
uvicorn app.main:app --reload
pytest
ruff check app
```

如果使用 Alembic 管理数据库：

```bash
alembic upgrade head
```

## 当前已包含

- FastAPI 应用入口与 API v1 路由。
- SQLAlchemy 2.x ORM 模型与 Alembic 首版迁移。
- SQLite PRAGMA 初始化。
- 静态规则查询：精灵、技能、状态。
- 己方配置管理：`/api/v1/player-builds`。
- 战斗流程：创建战斗、录入阵容、进入战斗、切换精灵。
- 敌方候选配置生成和摘要查询：`/api/v1/candidates`。
- 统一状态实例：手动施加、手动移除、切换清除/保留。
- 伤害事件记录：支持单次伤害、动画多段最终总伤害、连击伤害。
- 伤害公式占位：明确返回 `formula_unavailable`，不执行候选排除。
- 最小种子数据：30 个性格、2 个示例精灵、2 个示例技能、3 个示例状态。

## 手动输入 MVP 流程

1. 启动数据库并导入最小种子数据。
2. 创建己方精灵配置。
3. 创建战斗。
4. 录入双方阵容；己方使用 `build_id`，敌方使用 `elf_id`。
5. 系统为敌方精灵自动生成候选配置。
6. 确认双方首发，进入战斗阶段。
7. 手动记录技能、伤害、状态变化、切换等事件。
8. 每个关键事件生成状态快照。
9. 伤害公式未确认时，只记录事实，不排除候选。

## 重要边界

当前版本不会实现真实伤害公式，不会自动识图，也不会自动推荐出招。所有计算相关入口都已经预留，后续确认公式后可在 `app/calculation/damage_calculator.py` 和 `app/inference/inference_engine.py` 中接入。
