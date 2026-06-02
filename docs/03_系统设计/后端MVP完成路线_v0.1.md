# 后端 MVP 完成路线 v0.1

更新日期：2026-05-29

## 1. MVP 完成目标

后端 MVP 的完成标准不是“覆盖所有洛克王国规则”，而是形成一条可验证的闭环：

1. 玩家可以录入战斗、阵容、技能、伤害、状态和切换。
2. 系统能基于事件发生时的状态快照解释当前伤害或状态伤害。
3. 系统能把伤害观测、状态触发、技能出现、速度先后手写入候选软评分。
4. 候选结果能给出解释链，说明为什么加分、扣分或保持未知。
5. 事件修正后可以重放重算，避免历史解释读取当前状态。
6. 所有静态规则导入都有 dry-run、commit 和可审阅摘要。

候选硬排除不作为 MVP 必须项。MVP 阶段默认坚持软评分，只有在公式、状态快照和技能分支都完整可信时，才允许局部开启硬排除。

## 2. 当前后端状态

### 已完成

- 数据库结构与 Alembic 迁移已建立。
- rocom 静态数据已导入：精灵、技能、可学习技能、属性克制。
- 性格核心规则已幂等初始化。
- P0 状态定义已有 JSON 种子和导入器，当前本地库已写入 10 条：
  - 灼烧
  - 中毒
  - 寄生
  - 冻结
  - 棘刺印记
  - 中毒印记
  - 星陨印记
  - 雨天
  - 沙暴
  - 暴风雪
- 普通攻击最小伤害、P0 状态伤害、星陨伤害计算器已接入 `DamageCalculator`。
- `RuleResolver` 已能解析技能基础字段、本系、属性克制、双属性合并、应对倍率和基础减伤。
- 星陨已明确按幻系计算克制/抵抗，不继承触发技能属性克制。
- Observation API 已支持普通伤害、扣血百分比、技能出现、速度先后手，并允许伤害观测 payload 指定 `formula_type = status | starfall`。
- 候选系统已能更新 `match_score`、`confidence`、matched/mismatched evidence，默认不硬排除。
- 战斗运行时数据清理和归档 purge 已有 dry-run/commit 流程。

### 未完成

- 状态自动结算尚未实现。
- 星陨、灼烧、中毒、寄生、冻结、棘刺和暴风雪施加冻结已具备阶段 C 的最小自动结算入口。
- 技能效果操作执行器尚未实现，技能不会自动施加状态、印记、天气或资源变化。
- `ModifierResolver` 尚未成型，天气、状态、印记、应对/防御减伤仍未统一进入公式修正链。
- 复杂技能分支 DSL 尚未实现。
- 事件重放重算仍是占位。
- 候选 evidence 查询仍偏摘要，缺少完整解释页。
- 前端尚未提供测试状态/星陨公式 payload 的完整 UI 字段。

## 3. 完成 MVP 的阶段路线

### 阶段 A：规则数据可审阅与可测试（已完成）

目标：让前端和后端都能确认当前规则库里有什么。

后端任务：

1. 扩展 `EffectDefinitionOut`，返回 MVP 测试必需字段：
   - `display_priority`
   - `target_scope`
   - `attach_target_type`
   - `default_layers`
   - `max_layers`
   - `stack_rule`
   - `duration_type`
   - `clear_by_*`
   - `can_be_*`
   - `resource_modifier_json`
   - `damage_modifier_json`
   - `skill_modifier_json`
   - `action_modifier_json`
   - `special_rule_id`
   - `developer_notes`
   - `data_version`
2. 给 effect importer 增加独立管理 API 或脚本记录：
   - dry-run 摘要；
   - commit 摘要；
   - 本地库当前版本；
   - 已导入 effect 数量。
3. 保持启动时不自动写入状态定义，避免误污染本地规则库。

验收：

- `/api/v1/effects` 能让前端完整展示星陨 `uses_type_effectiveness = true`。
- 状态定义导入 dry-run 与 commit 均有测试覆盖。

完成记录：

- `EffectDefinitionOut` 已扩展完整审阅字段。
- 前端 `EffectDefinitionOut` 类型已同步。
- 接口文档已同步 `/effects` 响应字段。
- effect importer 已新增 `--status` 只读查询，可输出当前状态定义数量、版本、分类、归属范围和 effect_id 列表。
- 当前工作库 `effect_definition` 已验证 10 条 P0 状态定义，星陨 `resource_modifier_json.uses_type_effectiveness = true`。

### 阶段 B：状态施加与状态实例稳定

目标：玩家手动施加状态时，不容易挂错位置，状态快照稳定可追溯。

后端任务：

1. `EffectService.apply_effect` 根据 `EffectDefinition` 校验 owner_scope：
   - `elf` 必须有 `owner_side + owner_elf_id`；
   - `side` 必须有 `owner_side`，不要求 `owner_elf_id`；
   - `field` 固定或默认 `field_id = main`；
   - `skill_slot` 必须有 `owner_skill_slot_id`。
2. 按定义处理默认层数、持续时间、叠层规则、冲突组和天气替换。
3. 每次施加、叠层、移除、切换清除都写入 `EffectChangeEvent`。
4. 每次状态变化后创建 `BattleEffectSnapshot`。

验收：

- 前端施加星陨印记时，后端能强制其为 `owner_scope = side`。
- 前端施加天气时，后端能强制其为 `owner_scope = field`。
- 切换精灵时，`clear_on_switch = true` 的 elf 状态清除，side/field 状态保留。

实现口径：

- `EffectService.apply_effect` 以 `EffectDefinition.owner_scope` 为准归一化挂载目标。
- 若前端误传星陨 `owner_scope = elf`，后端仍写为 `side`，并清空 `owner_elf_id`。
- 若前端误传天气 `owner_scope = side`，后端仍写为 `field`，并默认 `field_id = main`。
- 精灵状态必须提供 `owner_side + owner_elf_id`，否则返回 400。
- 技能槽状态必须提供 `owner_skill_slot_id`，否则返回 400。
- 显式传入的 `remaining_turns = 0` 和 `remaining_uses = 0` 必须保留，不能被默认值覆盖。

### 阶段 B+：最小回合语义

目标：先解决“当前回合做了什么、怎样结束本回合”的基础语义，为阶段 C 自动结算提供挂载点。

后端任务：

1. 新增结束回合接口：

```text
POST /api/v1/battles/{battle_id}/turns/end
```

2. 阶段 B+ 的最小行为：
   - 只允许 `battle.phase = battle` 的战斗结束回合；
   - 写入 `BattleEvent(event_type = turn_end)`；
   - 创建结束回合后的状态快照；
   - `battle.turn_number += 1`；
   - 返回 `settlement_status = not_implemented`。

3. 阶段 C 会在同一接口内接入 P0 回合末自动结算。

验收：

- 前端点击“结束回合”后，当前回合号递增。
- 时间线中能看到 `turn_end` 事件。
- 新快照成为 `battle.current_snapshot_id`。
- 准备阶段、已结束、已归档战斗不能结束回合。

### 阶段 C：回合自动结算

目标：状态伤害不再只靠手动录入，系统可以按阶段自动结算并生成事件。

新增服务建议：

```text
backend/app/services/turn_settlement_service.py
```

当前落地进度：

- 已新增 `TurnSettlementService.settle_end_turn()`，并接入 `POST /api/v1/battles/{battle_id}/turns/end`。
- 已支持 P0 回合末结算：中毒印记、中毒、灼烧、寄生、冻结阈值检查。
- 已支持 P0 攻击后结算：手动伤害事件后触发星陨印记。
- 已支持 P0 入场结算：切换后触发棘刺印记。
- 已支持 P0 回合末施加效果：暴风雪给双方当前上场精灵施加冻结。
- 自动结算会创建系统来源事件，并在伤害事件中写入 `formula_context_json`、克制倍率和解释链。
- 灼烧结算后按 `after_settlement.layer_change = halve_floor` 写入 `EffectChangeEvent` 并更新层数。
- 星陨结算后按 `after_settlement.layer_change = clear` 写入 `EffectChangeEvent` 并清空印记。
- 自动结算生成的敌方受击伤害会转为 Observation 软评分，写入候选 evidence，仍不硬排除。
- 上下文不足时只返回 skipped/partial 摘要，不假算伤害、不改写状态。

职责：

1. 读取当前战斗状态和事件发生前快照。
2. 按阶段筛选 active effects：
   - `start_turn`
   - `before_action`
   - `post_attack`
   - `end_turn`
   - `switch_in`
3. 根据 `resource_modifier_json.settlement_type` 和 `formula_hooks_json` 分发到计算器。
4. 创建独立事件：
   - `BattleEvent`
   - `DamageEvent`
   - `ResourceChangeEvent`
   - `EffectChangeEvent`
   - `BattleEffectSnapshot`
5. 状态结算必须记录 `formula_context_json` 和解释链。

P0 结算顺序建议：

1. 攻击技能伤害。
2. 攻击后星陨。
3. 入场棘刺。
4. 回合末中毒印记。
5. 回合末中毒。
6. 回合末灼烧。
7. 回合末寄生。
8. 冻结阈值检查。

验收：

- 手动触发“结算回合末状态”后，灼烧/中毒/寄生能生成伤害事件。
- 手动伤害事件后，星陨能生成独立 `formula_type = starfall` 的 `DamageEvent`。
- 切换入场后，棘刺能生成独立伤害事件。
- 暴风雪回合末能给双方当前上场精灵施加冻结。
- 自动结算生成的敌方受击伤害能进入候选软评分 evidence。
- 结算结果与直接调用 `DamageCalculator` 的单元测试一致。

阶段 C 已完成最小闭环。后续更复杂的技能施加、条件分支、天气替换和清除仍归入阶段 D 的 `EffectOperationExecutor`。

### 阶段 D：技能效果操作执行器（已完成）

目标：使用技能后，能按结构化规则施加状态、印记、天气和资源变化。

新增服务建议：

```text
backend/app/services/effect_operation_executor.py
```

职责：

1. 读取 `skill_definition.effect_operations_json`。
2. 执行结构化操作：
   - apply_effect；
   - add_layers；
   - remove_effect；
   - clear_effects；
   - change_weather；
   - resource_change；
   - conditional_branch。
3. 所有操作必须生成事件和快照。
4. 不明确的技能分支标记 unknown，不强行执行。

验收：

- 超维投射能给敌方 side 增加 4 层星陨印记。
- 星轨裂变能给敌方 side 增加 2 层星陨印记。
- 二律背反“应对防御翻倍”在应对结果未知时不自动翻倍，只记录 unknown branch。

当前落地进度：

- 已新增 `EffectOperationExecutor`，并接入通用 `skill_use` 事件。技能事件创建后会读取 `SkillDefinition.effect_operations_json`，执行 `apply_effect` / `add_layers`，状态变化写入 `BattleEffectInstance` 和 `EffectChangeEvent`，再创建事件快照。
- 已支持 P0 目标解析：`enemy_side`、`self_side`、`target_side`、`field` 等会根据 `EffectDefinition.owner_scope` 归一化到 side / elf / field / skill_slot。
- 已支持条件分支最小处理：`always` 自动执行；`response_attack_success`、`response_defense_success`、`response_status_success` 等只有在 `payload_json.manual_flags` 或 `payload_json.condition_flags` 中显式为 `true` 时才执行，否则只返回 skipped/unknown，不改写状态。
- 已补齐阶段 D 通用操作：`dynamic_apply_effect`、`remove_effect`、`clear_effects`、`change_weather`、`resource_change`、`multiply_layers`、`conditional_branch`。
- `change_weather` 会按天气冲突组清除旧天气并施加新天气；`resource_change` 会更新战斗精灵 HP/energy 并写入 `ResourceChangeEvent`。
- 动态层数当前支持从目标现有状态层数读取；缺少上下文或层数为 0 时跳过，不假造状态。
- 已新增星陨技能规则种子 `backend/app/seed/starfall_skill_operations_p0.json`，覆盖 `skills.csv` 中含“星陨”的技能：超维投射、冥想、多维击打、心灵洞悉、二律背反、星轨裂变、超新星馈赠、空间压迫、星链、错乱。
- 已新增技能操作规则导入器 `backend/app/data_pipeline/skill_operations/importer.py`，支持按 `skill_name` 或 `skill_id` 写入 `effect_operations_json`，默认 dry-run，传 `--commit` 后才提交。
- 当前仍不把“修改连击数/公式参数”放入 EffectOperationExecutor 自动执行；这类内容后续由 RuleResolver / ModifierResolver 统一进入公式上下文。

### 阶段 E：ModifierResolver 与应对/防御结算层

目标：把天气、状态、印记、减伤、应对成功统一解析为公式上下文。

新增或扩展模块：

```text
backend/app/calculation/modifier_resolver.py
backend/app/calculation/response_resolver.py
```

职责：

1. 从 `BattleEffectSnapshot.full_snapshot_json` 读取事件发生时状态。
2. 汇总伤害修正：
   - 天气倍率；
   - 状态/印记增伤减伤；
   - 防御技能减伤；
   - 应对成功倍率；
   - 无视抵抗；
   - 特殊分支。
3. 输出结构化解释：
   - 来源；
   - 倍率；
   - 是否确定；
   - 未知因素。

验收：

- 应对/防御造成的减伤能进入 `damage_reductions`。
- 若应对是否成功未知，候选匹配返回 unknown，不扣分。
- 星陨仍只吃幻系克制和防御减伤，不吃本系、天气、显示威力。

### 阶段 F：候选软评分增强

目标：让状态伤害、星陨、速度、技能出现都稳定影响候选置信度。

后端任务：

1. Observation payload 标准化：
   - attack；
   - status；
   - starfall；
   - speed_order；
   - skill_seen；
   - state_trigger。
2. 对 status/starfall 观测写入更完整 evidence：
   - 观测值；
   - 预测值；
   - 公式上下文；
   - unknown_factors；
   - 状态快照 ID。
3. 状态伤害按候选 HP、双属性克制和状态层数推算。
4. 星陨按候选防御面板、候选属性、层数和触发技能类别推算。
5. 保持默认不硬排除。

验收：

- 星陨伤害观测能改变候选 Top 5 排序。
- 灼烧/中毒伤害观测能约束候选最大 HP 和属性克制。
- 有未知关键因素时 `unknown_count` 增加，不误扣分。

### 阶段 G：事件重放重算

目标：修正历史事件后，候选和状态能从指定事件开始重算。

后端任务：

1. 实现 `ReplayService`：
   - 从 battle 初始状态开始；
   - 按时间线顺序重放事件；
   - 每步重建状态实例、资源、快照；
   - 重新执行候选 observation。
2. 修正事件后作废旧事件，生成新事件。
3. 重放时不要读取当前状态冒充历史状态。

验收：

- 修改一次伤害值后，候选分数随重放更新。
- 修改一次状态层数后，后续状态伤害解释随重放更新。
- 重放结果能报告成功、失败、跳过和 unknown 数量。

### 阶段 H：MVP 收尾与前端联调

目标：前端可以完整测试后端 MVP。

后端需要提供或稳定：

1. 规则库可审阅接口。
2. 状态施加/移除/叠层接口。
3. 状态结算接口：
   - 结算回合末；
   - 结算攻击后；
   - 结算入场。
4. 伤害预览接口：
   - 输入 attacker/defender/skill/status/snapshot；
   - 输出预测伤害、解释链、unknown_factors。
5. 候选 evidence 详情接口。
6. 重放接口。

验收：

- 不使用数据库手查，也能在前端确认 P0 状态定义、星陨规则和状态实例。
- 前端能手动制造“星陨印记 -> 非幻系攻击 -> 星陨伤害 -> 候选软评分变化”的完整流程。
- 前端能手动制造“中毒/灼烧回合末结算 -> 伤害事件 -> 候选软评分变化”的完整流程。

## 4. 推荐立即开始的任务

优先顺序如下：

1. 扩展 `EffectDefinitionOut`，让前端能审阅完整状态定义。
2. 加强 `EffectService.apply_effect` 的 owner_scope 校验和默认值填充。
3. 新建 `TurnSettlementService`，先只实现 P0 的手动结算入口。
4. 为星陨和 P0 状态结算生成独立 `DamageEvent` 与解释链。
5. 把结算事件接入 Observation 软评分。
6. 再做 `EffectOperationExecutor`，让技能自动施加状态。

这条顺序的原因是：先让状态定义可信、状态实例可信、结算可信，再让技能自动触发。否则技能操作执行器会把错误状态或错误 owner_scope 扩散到事件流和候选评分。

## 5. MVP 不做或暂缓

以下内容不阻塞后端 MVP：

- 图像识别。
- 全技能完整 DSL。
- 候选硬排除。
- 所有复杂特性。
- 所有天气与状态 modifier。
- 速度概率完整模型。

这些内容应在 MVP 闭环稳定后，再逐步扩展。
