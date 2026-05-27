# 后端项目进展更新

更新日期：2026-05-21

## 当前后端阶段

后端已经完成纯手动输入 MVP 的主要闭环，并已进入“观测驱动候选软评分 + 普通攻击伤害计算 + RuleResolver 雏形”阶段。当前重点是补齐正式状态定义、技能规则分支、状态自动结算、候选证据链和事件重放；候选硬排除仍保持关闭。

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
- 支持候选摘要、详情、列表查询。
- 支持 Observation API 驱动候选软评分，写入 `match_score`、`confidence`、匹配/冲突事件 ID 和 evidence。
- 默认不硬排除候选。

### 7. 计算与推断

- 已实现普通攻击最小伤害公式。
- 已实现伤害值和扣血百分比观测匹配。
- 已实现技能出现、速度先后手等观测匹配骨架。
- 已实现 `RuleResolver` 雏形，支持技能基础信息、本系、属性克制、双属性合并、应对倍率和基础减伤解析。

### 8. 数据管线

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

- 完整真实伤害体系：当前只有普通攻击最小公式；状态伤害、星陨、复杂技能分支、天气/状态 modifier 仍未完成。
- 候选硬排除：仍未开启；当前只软评分。
- 速度先手概率：只保留简单面板速度观测匹配，未实现概率/先制/优先级完整规则。
- 事件重放重算：接口存在，但业务逻辑仍是占位。
- 候选证据链：observation 已写入 evidence，但聚合查询和前端解释页仍需完善。
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
3. 继续扩展 `RuleResolver`，接入技能规则分支 DSL、天气/状态 modifier、减伤和特殊公式。
4. 实现状态自动结算与星陨等特殊伤害。
5. 完善候选 evidence 聚合查询和前端解释链展示。
6. 为候选生成补性能测试和规模控制策略。
7. 在样例验证充分后，再逐步开启候选硬排除。
8. 实现真实事件重放服务。


---

## 2026-05-20 补充：候选反推与普通伤害计算推进

详细更新记录见：`backend/BACKEND_UPDATE_LOG.md`。

本次后端已完成两个新的反推相关里程碑：

### 里程碑 1：观测驱动的候选软评分骨架

新增：

- `app/inference/observation_types.py`
- `app/inference/match_result.py`
- `app/inference/skill_pool_matcher.py`
- `app/inference/speed_matcher.py`
- `app/inference/observation_matcher.py`

`InferenceEngine` 新增 `process_observation_event()`，现在可以根据玩家录入的技能出现、速度先后手等观测更新候选：

- `match_score`
- `confidence`
- `matched_event_ids_json`
- `mismatched_event_ids_json`
- `evidence_ids_json`

默认仍不硬排除候选。

### 里程碑 2：普通攻击伤害计算与伤害观测匹配

新增：

- `app/calculation/rounding.py`
- `app/calculation/attack_damage.py`
- `app/inference/damage_matcher.py`

修改：

- `app/calculation/formula_context.py`
- `app/calculation/damage_calculator.py`
- `app/inference/observation_matcher.py`

现在支持最小普通攻击伤害计算，并可用玩家录入的：

- 整数伤害；
- 扣血百分比；

对候选进行软评分。

该阶段完成时仍未实现 RuleResolver、属性克制解析器、状态自动结算、星陨独立事件和候选硬排除。随后第四阶段已补齐 RuleResolver 雏形，详见下文。当前仍未完成的是状态自动结算、星陨独立事件、技能分支 DSL 和候选硬排除。

### 当前测试命令

在 `backend/` 目录下执行：

```bash
python -m pytest -q
```

当前结果：

```text
17 passed
```

代码风格检查：

```bash
python -m ruff check app/calculation app/inference app/api/v1/endpoints app/schemas app/tests/test_attack_damage_calculator.py app/tests/test_inference_milestone1.py app/tests/test_observation_api.py
```

当前结果：

```text
All checks passed!
```


---


## 2026-05-20 补充：第三里程碑 Observation API

已完成第三里程碑：把候选反推的观察事件处理能力暴露为后端 API。

新增：

- `app/schemas/observation.py`
- `app/api/v1/endpoints/observations.py`
- `app/tests/test_observation_api.py`

修改：

- `app/api/v1/router.py` 注册 `observations` 路由。
- `app/schemas/data_update.py` 修复既有 ruff 长行问题。

可调用接口：

```text
POST /api/v1/observations/{battle_id}
```

当前用途：

- 前端提交玩家观测到的伤害数字、扣血比例、技能出现、速度先后手等事件；
- 后端转换为 `ObservationEventInput`；
- 调用 `InferenceEngine.process_observation_event()`；
- 写回候选 `match_score`、`confidence`、匹配/冲突事件 ID 和 evidence。

最新测试：

```text
python -m pytest -q
17 passed
```

最新风格检查：

```text
python -m ruff check app/calculation app/inference app/api/v1/endpoints app/schemas app/tests/test_attack_damage_calculator.py app/tests/test_inference_milestone1.py app/tests/test_observation_api.py
All checks passed!
```

第四阶段 RuleResolver 雏形已完成，下一步应继续接入技能规则分支 DSL。
---

## 2026-05-20 补充：第四阶段 RuleResolver 雏形

已完成第四阶段第一版：后端新增 `RuleResolver`，并接入观察事件伤害反推流程。

新增：

- `app/calculation/rule_resolver.py`
- `app/tests/test_rule_resolver.py`

修改：

- `app/calculation/formula_context.py`：增加技能系别、双方系别、规则解析开关与解释详情字段；
- `app/calculation/attack_damage.py`：计算解释中输出 `rule_resolution_details`；
- `app/inference/observation_matcher.py`：构造伤害上下文后调用 `RuleResolver`；
- `app/inference/inference_engine.py`：向 `ObservationMatcher` 注入数据库会话；
- `app/tests/test_observation_api.py`：增加 `resolve_rules=true` 的 API 回归测试。

当前能力：

- 后端可解析 `SkillDefinition`、本系加成、属性克制、双属性合并、应对成功倍率和基础减伤来源；
- 应对成功未知时会标记 unknown，不会用单点伤害误导候选扣分；
- Observation API 已能使用后端解析出的倍率进行候选软评分。

最新测试：

```text
python -m pytest -q
17 passed
```

最新风格检查：

```text
python -m ruff check app/calculation app/inference app/api/v1/endpoints app/schemas app/tests/test_attack_damage_calculator.py app/tests/test_inference_milestone1.py app/tests/test_observation_api.py app/tests/test_rule_resolver.py
All checks passed!
```

下一步建议：继续做技能规则分支 DSL，把 `SkillDefinition.damage_rule_json` 中的条件分支逐步接入 RuleResolver。
