# 后端更新记录与测试指南

> 最近更新日期：2026-05-21  
> 当前重点：敌方配置反推闭环，从“玩家观测”更新候选评分与置信度。

---

## 1. 当前推进到什么程度

目前后端已经从原来的“只记录事件、伤害公式占位”推进到：

```text
玩家手动录入观测事件
  -> ObservationMatcher 分发匹配逻辑
  -> 对每个 BuildCandidate 构造候选上下文
  -> 计算或匹配观测
  -> 更新 match_score / confidence / evidence
  -> 默认不硬排除候选
```

也就是说，现在已经具备了候选反推 MVP 的后端内部骨架。

---

## 2. 已完成里程碑

### 2.1 里程碑 1：观测驱动的候选软评分骨架

已完成内容：

1. 新增通用观测类型：

```text
backend/app/inference/observation_types.py
```

当前包括：

```text
DAMAGE_VALUE
HP_PERCENT_DELTA
SPEED_ORDER
SKILL_SEEN
STATE_TRIGGER
SURVIVAL
```

2. 新增通用匹配结果模型：

```text
backend/app/inference/match_result.py
```

核心字段：

```text
matched: true / false / null
score_delta
can_hard_exclude
unknown_factors
observed_value
predicted_value
predicted_range
evidence
```

其中 `matched = null` 表示信息不足，不加分、不扣分、不排除。

3. 新增技能池匹配器：

```text
backend/app/inference/skill_pool_matcher.py
```

用于判断玩家观测到的敌方技能是否存在于候选的 `possible_skill_ids_json` 中。

4. 新增速度先后手匹配器：

```text
backend/app/inference/speed_matcher.py
```

当前只做最基础的面板速度比较。若存在技能优先级、速度状态、先制等未知因素，则返回 unknown。

5. 新增观测分发器：

```text
backend/app/inference/observation_matcher.py
```

负责将不同观测类型分发给对应 matcher。

6. 改造推断引擎：

```text
backend/app/inference/inference_engine.py
```

新增：

```python
process_observation_event(...)
```

该方法会：

- 加载候选；
- 逐个候选匹配观测；
- 更新 `match_score`；
- 写入 `matched_event_ids_json` / `mismatched_event_ids_json`；
- 写入 `evidence_ids_json`；
- 用 softmax 刷新 `confidence`；
- 默认不硬排除。

---

### 2.2 里程碑 2：普通伤害计算与伤害观测匹配

已完成内容：

1. 扩展伤害公式上下文：

```text
backend/app/calculation/formula_context.py
```

新增：

```python
PanelStats
```

并扩展 `DamageFormulaContext`，支持：

- 攻击方面板；
- 防御方面板；
- 技能类别；
- 基础威力；
- 显示威力；
- 本系、克制、天气、应对倍率等已解析参数；
- 减伤列表；
- 观测伤害；
- 观测扣血百分比；
- unknown_factors。

2. 新增取整工具：

```text
backend/app/calculation/rounding.py
```

当前普通伤害最终使用向下取整。

3. 新增普通攻击伤害计算器：

```text
backend/app/calculation/attack_damage.py
```

当前支持最小普通攻击公式：

```text
floor((A / D * 37 / 41) * display_power * unstable * reductions) * hit_count
```

其中：

- 物理技能使用物攻 / 物防；
- 魔法技能使用魔攻 / 魔防；
- `display_power` 可由外部直接传入；
- 如果没有 `display_power`，则由 `base_power` 和已解析倍率计算；
- 目前不负责判断应对、天气、克制是否成立，只消费已经解析好的参数。

4. 改造伤害计算入口：

```text
backend/app/calculation/damage_calculator.py
```

当前会根据 `formula_type` 分发到普通攻击计算器。

上下文不完整时仍返回：

```text
formula_unavailable
```

5. 新增伤害观测匹配器：

```text
backend/app/inference/damage_matcher.py
```

支持：

- 整数伤害匹配；
- 扣血百分比匹配；
- 理论范围匹配预留；
- 公式不可用时返回 unknown；
- 有 unknown_factors 时返回 unknown。

6. `ObservationMatcher` 已接入：

```text
DAMAGE_VALUE
HP_PERCENT_DELTA
```

现在玩家录入伤害或扣血百分比后，可以对每个候选计算理论伤害，并更新候选分数。

---

## 3. 当前明确还没有做的内容

以下内容截至第四阶段后仍尚未完成或未完全完成：

1. `RuleResolver` 仍只是雏形。
   - 已支持技能基础信息、本系、属性克制、双属性合并、应对倍率和基础减伤；尚未完整接入技能规则分支 DSL、天气/状态 modifier 和复杂特殊公式。

2. 状态自动结算尚未实现。
   - 冻结、星陨、灼烧、中毒、寄生、棘刺还没有真正接入自动回合结算。

3. 星陨独立伤害事件尚未实现。

4. 通用 observation 提交 API 已完成。
   - 当前路径为 `POST /api/v1/observations/{battle_id}`。

5. 默认不硬排除。
   - 即使 matcher 判断不匹配，也只是扣分和写证据链。

---

## 4. 关键文件清单

### 4.1 计算层

```text
backend/app/calculation/formula_context.py
backend/app/calculation/rounding.py
backend/app/calculation/attack_damage.py
backend/app/calculation/damage_calculator.py
backend/app/calculation/speed_calculator.py
```

### 4.2 推断层

```text
backend/app/inference/inference_engine.py
backend/app/inference/observation_types.py
backend/app/inference/observation_matcher.py
backend/app/inference/match_result.py
backend/app/inference/skill_pool_matcher.py
backend/app/inference/speed_matcher.py
backend/app/inference/damage_matcher.py
```

### 4.3 测试

```text
backend/app/tests/test_inference_milestone1.py
backend/app/tests/test_attack_damage_calculator.py
backend/app/tests/test_observation_api.py
```

---

## 5. 如何运行测试

以下命令都在 `backend/` 目录下执行。

### 5.1 安装开发依赖

如果是新环境，先执行：

```bash
python -m pip install -e ".[dev]"
```

如果缺少特定包，可单独安装：

```bash
python -m pip install pydantic-settings ruff pytest httpx
```

### 5.2 运行全部后端测试

```bash
python -m pytest -q
```

当前通过情况：

```text
17 passed
```

会出现 FastAPI `on_event` 的弃用 warning，这是既有问题，不影响当前测试结果。

### 5.3 只测试候选反推骨架

```bash
python -m pytest app/tests/test_inference_milestone1.py -q
```

覆盖：

- 技能出现匹配；
- 技能池不可靠时返回 unknown；
- 速度先后手匹配；
- 观测事件更新候选分数；
- 置信度刷新；
- 证据链写入。

### 5.4 只测试普通攻击伤害计算

```bash
python -m pytest app/tests/test_attack_damage_calculator.py -q
```

覆盖：

- 普通物理伤害公式；
- 上下文缺失时返回 `formula_unavailable`。

### 5.5 运行代码风格检查

```bash
python -m ruff check app/calculation app/inference app/api/v1/endpoints app/schemas app/tests/test_attack_damage_calculator.py app/tests/test_inference_milestone1.py app/tests/test_observation_api.py
```

当前通过情况：

```text
All checks passed!
```

---

## 6. 如何手动理解/验证当前逻辑

### 6.1 技能出现观测

假设玩家观察到敌方用了 `skill_a`。

如果候选的：

```json
possible_skill_ids_json = ["skill_a", "skill_b"]
```

则：

```text
matched = true
match_score += 2.0
```

如果候选技能池中没有 `skill_a`，且技能池可靠：

```text
matched = false
match_score -= 2.0
```

但默认：

```text
is_excluded = false
```

### 6.2 速度先后手观测

如果玩家观察到我方先手：

```text
observed_order = self_first
```

且：

```text
self_speed = 100
candidate.final_speed = 80
```

则候选匹配。

如果：

```text
candidate.final_speed = 120
```

则候选不匹配并扣分。

如果存在：

```text
unknown_factors = ["priority_modifier_unknown"]
```

则返回 unknown，不加分、不扣分。

### 6.3 整数伤害观测

玩家录入：

```text
observed_damage_value = 90
```

系统会用候选防御面板计算理论伤害。

例如：

```text
我方物攻 = 200
敌方候选物防 = 100
技能威力 = 50
```

理论伤害为：

```text
floor((200 / 100 * 37 / 41) * 50) = 90
```

该候选匹配并加分。

### 6.4 扣血百分比观测

玩家录入：

```text
observed_hp_percent_delta = 30.0
```

若候选理论伤害为 90：

```text
候选最大 HP = 300 -> 90 / 300 * 100 = 30%
候选最大 HP = 600 -> 90 / 600 * 100 = 15%
```

前者匹配，后者不匹配。

---

## 7. 下一步建议

第四阶段已完成 RuleResolver 雏形和 Observation API 接入。下一步建议：

1. 扩展 RuleResolver 的技能规则分支 DSL。
2. 接入天气/状态 modifier、减伤和复杂特殊公式。
3. 实现状态自动结算与星陨独立伤害事件。
4. 完善候选 evidence 聚合查询和前端证据链展示。
5. 补充状态触发与生存观测 matcher。

不建议现在开启硬排除。当前阶段应继续只做软评分。

---

## 8. 2026-05-20 第三里程碑：Observation API 接入

本次新增通用观察事件 API，使前端可以通过 HTTP 调用候选反推能力。

新增文件：

```text
backend/app/schemas/observation.py
backend/app/api/v1/endpoints/observations.py
backend/app/tests/test_observation_api.py
```

修改文件：

```text
backend/app/api/v1/router.py
backend/app/schemas/data_update.py
```

新增接口：

```http
POST /api/v1/observations/{battle_id}
```

请求体核心字段：

```json
{
  "enemy_elf_id": "enemy_elf",
  "event_id": "event_damage_api_1",
  "observation_type": "damage_value",
  "observed_value": 90,
  "payload": {
    "attacker_panel_stats": {
      "hp": 300,
      "physical_attack": 200,
      "physical_defense": 100,
      "magic_attack": 100,
      "magic_defense": 100,
      "speed": 100
    },
    "skill_category": "physical",
    "base_power": 50,
    "damage_tolerance": 0
  }
}
```

接口会返回本次观察处理摘要，包括候选总数、匹配数、冲突数、unknown 数量、硬排除数量、Top 候选和 Top 置信度。

测试覆盖：

- 伤害数字观察通过 API 更新候选评分、置信度和证据链；
- 战斗不存在时返回 404；
- 继续确认默认不硬排除候选。

最新验证结果：

```text
python -m pytest -q
17 passed

python -m ruff check app/calculation app/inference app/api/v1/endpoints app/schemas app/tests/test_attack_damage_calculator.py app/tests/test_inference_milestone1.py app/tests/test_observation_api.py
All checks passed!
```
---

## 9. 2026-05-20 第四阶段：RuleResolver 雏形

本次完成第四阶段第一版规则解析层，将一部分原本需要前端手动传入的倍率迁移到后端解析。

新增文件：

```text
backend/app/calculation/rule_resolver.py
backend/app/tests/test_rule_resolver.py
```

修改文件：

```text
backend/app/calculation/formula_context.py
backend/app/calculation/attack_damage.py
backend/app/inference/observation_matcher.py
backend/app/inference/inference_engine.py
backend/app/tests/test_observation_api.py
```

当前 RuleResolver 支持：

- `resolve_rules=true` 时启用后端规则解析；
- 根据 `skill_id` 从 `SkillDefinition` 补齐技能系别、技能类别和基础威力；
- 根据双方 `elf_id` 或 payload 中的 `attacker_element_types` / `defender_element_types` 读取系别；
- 按数学建模文档计算本系加成，当前本系倍率为 `1.25`；
- 从 `type_effectiveness_rule` 读取属性克制倍率；
- 按项目规则处理双属性合并：双克制为 `3`、双抵抗为 `1/3`、一克制一抵抗为 `1`；
- 根据 `response_success` 和 `response_success_multiplier` 解析应对成功倍率；
- 当存在应对倍率但成功与否未知时写入 `response_success_unknown`，避免误扣分；
- 解析结构化 `damage_reduction_sources` 为公式可消费的减伤列表。

API 层已验证：

- `POST /api/v1/observations/{battle_id}` 的伤害观察可带 `resolve_rules=true`；
- 后端可用本系和属性克制算出显示威力，再对候选进行软评分；
- evidence 中会保留 `rule_resolution_details`，便于前端解释。

最新验证结果：

```text
python -m pytest -q
17 passed

python -m ruff check app/calculation app/inference app/api/v1/endpoints app/schemas app/tests/test_attack_damage_calculator.py app/tests/test_inference_milestone1.py app/tests/test_observation_api.py app/tests/test_rule_resolver.py
All checks passed!
```

下一步不建议直接扩展硬排除，建议继续补 RuleResolver 的技能分支 DSL 和状态/天气 modifier。

