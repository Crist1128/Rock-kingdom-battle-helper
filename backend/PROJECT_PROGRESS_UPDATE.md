# 后端项目进展更新

更新日期：2026-05-19

## 当前后端阶段

后端已经完成纯手动输入 MVP 的主要闭环，当前重点从“接口和事件流搭建”转向“正式规则数据、状态定义、真实公式和推断逻辑”。

## 已完成模块

### 1. 应用与基础设施

- FastAPI 应用入口：`app/main.py`。
- API v1 路由聚合：`app/api/v1/router.py`。
- 配置管理：`app/core/config.py`。
- SQLite Session 与 PRAGMA：`app/db/session.py`。
- ORM Base 与时间戳混入：`app/db/base.py`。
- Alembic 迁移：
  - `0001_initial_schema.py`
  - `0002_event_correction_resource_mvp.py`

### 2. 静态规则查询

- 精灵查询：`/api/v1/elves`。
- 精灵可学习技能：`/api/v1/elves/{elf_id}/skills`。
- 技能查询：`/api/v1/skills`。
- 性格查询：`/api/v1/natures`。
- 状态定义查询：`/api/v1/effects`。

### 3. 己方配置

- 创建、查询、更新、软删除己方配置。
- 替换技能槽顺序。
- 创建/更新时计算面板属性缓存。
- 输出中冗余返回精灵名称、头像、系别，便于前端展示。

### 4. 战斗流程

- 创建战斗。
- 战斗列表。
- 阵容录入。
- 首发确认并进入 battle 阶段。
- 切换精灵。
- 结束战斗。
- 归档战斗。
- 查询完整战斗状态。

### 5. 事件与快照

- 通用事件。
- 伤害事件。
- 资源变化事件。
- 状态施加/移除事件。
- 切换时状态清除/保留。
- 事件时间线。
- 事件作废与修正。
- 重放接口占位。
- 状态快照。

### 6. 候选配置

- 根据敌方 `elf_id` 生成候选配置。
- 当前候选枚举范围：30 种性格 × 个体资质分布。
- 支持候选摘要、详情、列表、证据占位查询。

### 7. 数据管线

- BWIKI 远程爬取。
- raw 数据清洗为 cleaned JSON。
- cleaned JSON dry-run / commit 导入 SQLite。
- 管理接口触发远程同步、本地导入和任务查询。
- 默认不随后端启动自动爬取远程。

## 当前本地数据状态

当前本地数据库已有：

- 精灵：465
- 技能：469
- 精灵可学习技能：21447
- 属性克制规则：113
- 性格：30
- 候选配置：已有生成记录

注意：当前正式 `effect_definition` 状态定义数据仍需补齐。

## 明确未完成内容

- 真实伤害公式：`app/calculation/damage_calculator.py` 当前仍返回 `formula_unavailable`。
- 真实候选过滤：`app/inference/inference_engine.py` 当前不排除候选。
- 速度先手概率：只保留简单速度比较/占位。
- 事件重放重算：接口存在，但业务逻辑仍是占位。
- 候选证据链：接口存在，但真实证据依赖候选过滤。
- 图像识别：未开始。
- 状态定义正式数据：待导入。

## 空库初始化现状

当前已实现：后端启动时自动幂等自检查 30 种核心性格定义。

该启动自检查只处理 `nature_definition`：

- 缺失则创建。
- 字段不一致则修正。
- 曾被软删除则恢复。
- 不插入示例精灵、示例技能或示例状态。
- 不远程爬取 rocom 数据。

因此空库首次启动前仍建议先执行：

```bash
python -m alembic upgrade head
```

随后启动后端即可自动补齐 30 种性格。精灵、技能、技能池和属性克制仍通过 rocom 数据管线导入。

历史 `app.seed.minimal_seed` 已降级为兼容入口，现在只补齐 30 种性格，不再写入示例宠物数据库。

## 状态定义数据接入建议

如果已有状态相关资料，建议先整理成 `effect_definitions.json`，字段对齐 `EffectDefinition` 模型。推荐最小字段：

- `effect_id`
- `effect_name`
- `category`
- `polarity`
- `display_group`
- `owner_scope`
- `target_scope`
- `attach_target_type`
- `default_layers`
- `max_layers`
- `stack_rule`
- `duration_type`
- `default_duration_turns`
- `clear_on_switch`
- `clear_by_abnormal_cleanse`
- `clear_by_stat_clear`
- `clear_by_mark_clear`
- `clear_by_weather_replace`
- `conflict_group`
- `conflict_policy`
- `formula_hooks_json`
- `stat_modifier_json`
- `damage_modifier_json`
- `developer_notes`

建议下一步新增：

```text
backend/app/data_pipeline/core_rules/
  effects_importer.py
  schemas.py
  README.md
```

导入能力应包含：

- 字段校验。
- 枚举校验。
- 重复 ID 校验。
- dry-run 报告。
- commit 写库。
- 不存在则创建，存在则更新，支持恢复软删除。

## 下一步后端优先级

1. 增加 `effect_definition` 导入器。
2. 为状态系统补测试。
3. 为候选生成补性能测试和规模控制策略。
4. 确认真实伤害公式并实现 `DamageCalculator`。
5. 实现 `InferenceEngine` 候选过滤。
6. 实现真实事件重放服务。
