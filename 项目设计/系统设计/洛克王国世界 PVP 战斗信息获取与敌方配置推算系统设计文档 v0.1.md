# 洛克王国世界 PVP 战斗信息获取与敌方配置推算系统设计文档 v0.1

> 设计依据：需求分析 v0.3.3
> 设计目标：把需求文档中的业务规则、状态体系、伤害/速度计算、敌方配置推算和 UI 展示需求，转化为第一版可落地的系统设计。
> 版本定位：第一版系统设计，重点支持“纯手动输入 MVP”，为后续半自动识别、实时辅助和高级推算预留扩展点。

------

## 1. 背景与设计目标

本系统面向《洛克王国世界》PVP 对战场景，核心不是自动替玩家决策，而是在对战过程中收集战斗信息、维护战斗状态、计算双方技能伤害、判断速度先手关系，并通过实际伤害事件逐步收敛敌方精灵的未知配置。

系统要解决的核心问题是：

1. 准备阶段已知双方六只精灵，其中己方配置完整确定，敌方只确定精灵种类。
2. 敌方性格、个体资质、面板属性、技能组未知，需要根据静态数据库生成候选配置集合。
3. 战斗阶段每次技能、伤害、状态变化、天气、印记、切换等信息都可能影响后续计算。
4. 伤害事件必须引用事件发生瞬间的完整状态快照，而不是使用当前最新状态。
5. 多次伤害事件用于过滤候选配置，并逐步提高敌方配置置信度。
6. UI 需要实时展示伤害区间、生命百分比、击杀判断、速度先手概率、候选配置收敛结果和关键状态。

第一版系统设计的核心原则：

- **先计算准确，再做识别自动化**：MVP 不依赖图像识别，优先用手动输入验证伤害、状态、推算链路。
- **事件驱动 + 快照计算**：所有关键事实记录为事件，所有推算依赖事件快照。
- **状态统一建模**：普通增益、异常、印记、天气、技能槽修正、行动规则状态都统一抽象为 BattleEffect。
- **规则数据化，特殊逻辑插件化**：精灵、技能、状态、印记、天气、伤害规则尽量由数据库配置；复杂技能通过 special_formula_id 或 effect handler 扩展。
- **推算保守，不因低置信事件误杀候选**：识别低置信、状态不完整、多段规则不明时降低事件权重，而不是强行排除大量候选。

------

## 2. 系统范围

### 2.1 本期范围：第一阶段纯手动输入 MVP

第一阶段重点实现以下能力：

1. 手动创建一场战斗。
2. 手动录入双方六只精灵。
3. 手动录入己方六只精灵完整配置。
4. 根据敌方精灵种类生成候选配置集合。
5. 支持手动录入技能、伤害、扣血百分比、生命百分比、状态变化、天气、印记、切换事件。
6. 支持统一 BattleEffect 状态实例管理。
7. 支持切换时自动清除 clear_on_switch = true 的效果。
8. 支持队伍侧增益印记槽和减益印记槽。
9. 支持天气 / 战场状态。
10. 支持基于状态快照的伤害计算。
11. 支持基于伤害事件的敌方候选配置过滤。
12. 支持速度区间和先手概率展示。
13. 支持伤害区间、生命百分比、击杀可能性展示。
14. 支持事件日志、手动纠错和基于事件回放重算。

### 2.2 后续范围

第二阶段加入半自动识别：当前精灵、技能名、伤害数字、敌方扣血百分比、最终总伤害、状态图标、天气、印记、防御技能状态等。

第三阶段实现实时辅助：战斗中自动刷新、自动维护候选集合、自动展示当前最优伤害数据、场下伤害预估、切换前预览。

第四阶段实现高级推算：技能组概率、遗漏状态提示、敌方行动习惯建模、速度候选与伤害候选联合判断、更多特殊技能和特殊状态。

### 2.3 明确不做

第一版不做以下内容：

1. 不做自动战斗决策。
2. 不做逐段伤害强制识别。
3. 不把“护盾”作为通用机制建模，而是归入技能特殊效果 / 防御技能减伤。
4. 不依赖图像识别作为 MVP 主链路。
5. 不把精灵名称作为系统主键，内部统一使用 pet_id。
6. 不在精灵表维护 alias_names，识别容错由头像模板、名称置信度和手动确认处理。

------

## 3. 总体架构设计

### 3.1 逻辑架构

系统建议按以下逻辑分层：

```text
展示层 UI
  ↓
输入层：手动输入 / 图像识别适配器
  ↓
事件层：事件标准化、事件日志、手动纠错
  ↓
运行时状态层：BattleSession、PetRuntimeState、BattleEffect、MarkState、WeatherState
  ↓
快照层：BattleEffectSnapshot / BattleStateSnapshot
  ↓
计算与推算层：属性计算、伤害计算、速度判断、候选生成、配置推算
  ↓
规则数据层：精灵、性格、技能、状态、印记、天气、属性克制、玩家配置
  ↓
持久化层：静态规则库、战斗记录库、事件日志库、用户配置库
```

### 3.2 推荐部署形态

第一阶段建议做成本地优先的单机工具或本地 Web 应用：

```text
前端单页应用
  - 战斗面板
  - 手动输入面板
  - 状态编辑器
  - 候选配置展示
  - 事件日志

本地服务 / 规则引擎
  - 状态管理
  - 伤害计算
  - 推算引擎
  - 数据库访问

本地数据库
  - 静态规则数据
  - 玩家己方配置
  - 战斗事件日志
  - 推算结果缓存
```

如果后续需要云端同步，可在不改变核心领域模型的前提下增加账号、云端规则库同步和战斗记录同步。

### 3.3 核心数据流

```text
创建战斗
  ↓
录入双方阵容
  ↓
读取 PetDefinition / SkillDefinition / NatureDefinition
  ↓
己方生成确定面板属性
  ↓
敌方生成 BuildCandidate 集合
  ↓
进入战斗阶段
  ↓
用户录入或识别一条战斗事件
  ↓
事件标准化为 BattleEvent / DamageEvent / EffectChangeEvent / SwitchEvent
  ↓
状态管理器应用事件，生成新运行时状态
  ↓
如果是伤害事件，保存事件发生瞬间 BattleEffectSnapshot
  ↓
伤害计算器枚举候选，计算理论伤害
  ↓
推算引擎更新候选 match_score / confidence / is_excluded
  ↓
速度判断器更新先手概率
  ↓
UI 刷新伤害、速度、候选、事件解释
```

------

## 4. 核心模块设计

### 4.1 战斗会话模块 BattleSessionService

职责：管理一场 PVP 对战的生命周期。

主要能力：

- 创建战斗 battle_id。
- 录入双方六只精灵。
- 维护当前回合 turn_number。
- 维护当前上场精灵 active_pet。
- 管理己方和敌方 side_state。
- 触发候选配置初始化。
- 对外提供当前战斗状态查询。
- 支持从事件日志重放恢复整场战斗。

核心对象：

```text
BattleSession {
  battle_id
  created_at
  updated_at
  phase                // preparation / battle / finished
  turn_number
  my_side: SideRuntimeState
  enemy_side: SideRuntimeState
  battlefield_state
  event_ids
  current_snapshot_id
}
```

### 4.2 规则数据模块 RuleDataService

职责：读取和维护静态规则数据。

主要数据：

- PetDefinition
- NatureDefinition
- SkillDefinition
- DamageRule
- HitRule
- EffectOperation
- EffectDefinition
- MarkDefinition
- WeatherDefinition
- TypeEffectivenessRule
- PlayerPetBuild

设计要求：

- 查询必须以 ID 为主。
- 允许 UI 使用名称搜索，但落库和事件引用使用 pet_id、skill_id、effect_id。
- 技能规则采用 damage_rule + hit_rule + effect_script 组合。
- 特殊技能通过 special_formula_id 或 special_effect_handler 扩展。
- 静态规则数据需要 data_version，用于之后处理游戏平衡改动。

### 4.3 输入模块 InputAdapter

第一阶段只实现 ManualInputAdapter。

```text
ManualInputAdapter
  - 输入阵容
  - 输入己方配置
  - 输入技能使用
  - 输入伤害值
  - 输入扣血百分比
  - 输入状态变化
  - 输入切换事件
  - 输入天气 / 印记变化
  - 修正历史事件
```

第二阶段增加 RecognitionInputAdapter，但识别结果不直接修改状态，必须先转换为标准事件，并保留 source 和 recognition_confidence。

输入优先级：

```text
manual_input > auto_recognition > system_inferred
```

### 4.4 事件标准化模块 EventNormalizer

职责：把用户输入或识别结果转换为统一事件。

事件类型建议：

```text
event_type:
  battle_start
  lineup_confirmed
  pet_switch
  skill_used
  damage
  effect_change
  resource_change
  weather_change
  mark_change
  manual_correction
  turn_start
  turn_end
```

所有事件必须包含：

```text
BaseBattleEvent {
  event_id
  battle_id
  turn_number
  timestamp
  event_type
  source
  confidence
  manual_override
}
```

### 4.5 事件日志模块 BattleEventStore

职责：保存不可变事件日志，并支持手动纠错和回放。

设计策略：

1. 原始事件不建议直接物理覆盖。
2. 手动纠错以 manual_correction 事件形式记录。
3. 当前状态由事件日志按顺序重放得到。
4. 推算结果可以缓存，但必须能由事件日志重新计算。

这样可以解决以下问题：

- 某次状态录入错误后，可以修正并重算后续推算。
- 可以解释某个候选为什么被排除。
- 可以回看某次伤害发生时的状态快照。

### 4.6 状态管理模块 BattleStateEngine

职责：根据事件维护当前战斗运行时状态。

核心能力：

- 应用 skill_used 事件。
- 应用 damage 事件。
- 应用 effect_change 事件。
- 应用 weather_change / mark_change。
- 应用 pet_switch 事件，并执行 clear_on_switch 规则。
- 维护当前精灵身上的 BattleEffectInstance。
- 维护队伍侧 SideMarkState。
- 维护全战场 BattlefieldState。
- 维护技能槽 SkillSlotState。
- 在关键事件发生前后生成快照。

切换清除策略：

```text
onPetSwitch(side):
  active_pet = old_pet
  for each effect in old_pet.effects:
    if effect.clear_on_switch == true:
      remove effect
      append EffectChangeEvent(change_type = switch_clear)
  keep side marks
  keep battlefield weather
  keep clear_on_switch = false effects
  switch active pet
```

### 4.7 快照模块 SnapshotService

职责：为伤害、治疗、能量变化、切换等事件保存计算所需的状态快照。

关键原则：

- 快照不可变。
- 伤害推算使用事件发生瞬间快照。
- 快照可以只保存完整状态，也可以保存状态引用 + 版本号；第一版建议直接保存完整 JSON，降低复杂度。

核心结构：

```text
BattleEffectSnapshot {
  snapshot_id
  battle_id
  turn_number
  timestamp
  attacker_effects
  defender_effects
  attacker_side_marks
  defender_side_marks
  battlefield_effects
  attacker_skill_slot_effects
  defender_skill_slot_effects
  turn_effects
}
```

### 4.8 属性计算模块 StatCalculator

职责：根据种族资质、个体资质、性格计算面板属性，并根据 BattleEffectSnapshot 计算战斗有效属性。

面板属性计算：

```text
hp = round(([70 + 1.7 * base_hp + 0.85 * individual_hp] * nature_multiplier) + 100)
non_hp = ceil(([10 + 1.1 * base_stat + 0.55 * individual_stat] * nature_multiplier) + 50)
```

战斗有效属性计算：

```text
effective_stat = panel_stat
  -> apply normal buff/debuff hooks
  -> apply abnormal/layer hooks
  -> apply side mark hooks
  -> apply weather/battlefield hooks
  -> apply skill slot hooks
  -> apply special skill hooks
  -> apply damage modifier hooks
```

注意：计算过程不应该直接读取 UI 分组字段，而应读取 BattleEffectSnapshot 中的效果实例和 calculation_hooks。

### 4.9 伤害计算模块 DamageCalculator

职责：计算我方技能对敌方、敌方技能对我方、敌方可能技能对我方及场下精灵的伤害。

输入：

```text
DamageCalculationInput {
  attacker_pet
  defender_pet
  skill_id
  attacker_build_or_candidate
  defender_build_or_candidate
  snapshot_id
  hp_context
}
```

输出：

```text
DamageCalculationResult {
  skill_id
  damage_min
  damage_max
  damage_values
  hp_percent_min
  hp_percent_max
  can_kill
  confidence
  explanation
}
```

第一版策略：

- 已确认配置输出单值。
- 未确认配置输出区间。
- 多段技能默认按最终总伤害计算。
- 如果技能 hit_rule 不完整，则标记计算置信度降低。
- 如果状态快照存在未确认效果，也降低计算置信度。
- 防御技能减伤不作为通用护盾处理，而通过 skill special effect / damage_modifier hook 进入公式。

### 4.10 候选配置生成模块 CandidateGenerator

职责：准备阶段为敌方每只精灵生成 BuildCandidate 集合。

生成维度：

- 性格：正面维度 6 种，负面维度 5 种，共 30 种。
- 个体资质维度：1 到 3 个维度。
- 个体资质数值：存在个体的维度取 7 到 10，不存在为 0。
- 技能：初始 possible_skills = learnable_skill_ids，可用 common_skill_sets 加权。

候选规模估算：

```text
个体组合数 = C(6,1)*4 + C(6,2)*4^2 + C(6,3)*4^3
          = 24 + 240 + 1280
          = 1544

性格 30 种
单只精灵完整候选约 1544 * 30 = 46320
```

第一版可采用两级策略：

1. 默认生成“常见候选 + 全量候选索引”。
2. 常见候选优先参与实时 UI 展示。
3. 全量候选在伤害事件发生后批量过滤。
4. 对相同最终六维属性的候选做聚合，减少计算量。
5. 候选被排除后不参与伤害区间，但保留排除原因和事件证据。

### 4.11 敌方配置推算模块 InferenceEngine

职责：根据伤害事件、状态事件和技能使用事件更新候选集合。

核心流程：

```text
onDamageEvent(event):
  snapshot = getSnapshot(event.snapshot_id)
  target_candidates = getActiveCandidates(event.related_enemy_pet)

  if enemy_skill_known:
    enumerate candidates
  else if enemy_is_attacker:
    enumerate candidate + possible_skill pairs

  for each candidate or candidate_skill_pair:
    theoretical_damage = DamageCalculator.calculate(...)
    error = abs(theoretical_damage - actual_damage)
    score_delta = score(error, event.confidence, snapshot_confidence)
    update match_score
    update matched_event_ids / mismatched_event_ids

    if event high confidence and impossible beyond tolerance:
      mark excluded
    else:
      keep with lower score

  normalize confidence
  update speed range
  update damage ranges
```

候选过滤原则：

- 高置信手动事件可以强过滤。
- 自动识别低置信事件只调低分数，不立即排除。
- 状态快照不完整时只弱过滤。
- 多段技能规则不明确时只弱过滤。
- 实际伤害值与扣血百分比推导生命明显矛盾时，事件标记低置信。

置信度分层建议：

```text
未知：0 <= confidence < 0.25
低置信度：0.25 <= confidence < 0.5
中置信度：0.5 <= confidence < 0.75
高置信度：0.75 <= confidence < 0.9
已基本确认：0.9 <= confidence <= 1.0 且候选数量足够少
```

### 4.12 速度判断模块 SpeedJudgeService

职责：根据己方速度和敌方候选速度计算先手关系。

算法：

```text
my_first_weight = 0
enemy_first_weight = 0

for candidate in active_candidates:
  w = candidate.confidence_weight or 1
  if my_speed > candidate.final_speed:
    my_first_weight += w
  else if my_speed < candidate.final_speed:
    enemy_first_weight += w
  else:
    my_first_weight += 0.5 * w
    enemy_first_weight += 0.5 * w

my_first_probability = my_first_weight / total_weight
enemy_first_probability = enemy_first_weight / total_weight
```

输出：

```text
SpeedJudgeResult {
  my_speed
  enemy_speed_min
  enemy_speed_max
  has_same_speed_candidate
  my_first_probability
  enemy_first_probability
  conclusion
  confidence
}
```

### 4.13 UI 展示模块 BattleDashboard

第一版 UI 建议拆成六个页面 / 区块：

1. **准备阶段阵容页**
   - 己方六只精灵配置确认。
   - 敌方六只精灵识别 / 手动选择。
   - 候选配置初始化状态。
2. **当前对位面板**
   - 当前我方精灵、敌方精灵。
   - 生命、能量、状态图标。
   - 天气、队伍侧增益印记槽、减益印记槽。
   - 速度判断和先手概率。
3. **伤害计算面板**
   - 我方技能打敌方：准确伤害 / 百分比 / 击杀判断。
   - 敌方已知技能打我方：准确伤害 / 百分比 / 击杀判断。
   - 敌方可能技能打我方：伤害区间和风险提示。
   - 场下精灵伤害预估作为第三阶段扩展。
4. **事件录入面板**
   - 选择攻击方、防御方、技能、伤害值。
   - 输入受击前后生命百分比和扣血百分比。
   - 输入是否多段，默认记录总伤害。
   - 快速添加状态、天气、印记、切换。
5. **候选配置面板**
   - 当前候选数量。
   - 候选生命 / 双防 / 双攻 / 速度区间。
   - 高置信候选列表。
   - 已排除候选及排除原因。
   - 支持按事件查看“为什么排除 / 为什么保留”。
6. **事件日志与回放面板**
   - 按回合展示事件。
   - 展示每条事件来源和置信度。
   - 支持手动修正。
   - 修正后触发从该事件开始重放与重算。

------

## 5. 数据库设计

### 5.1 静态规则表

#### PetDefinition

```text
PetDefinition {
  pet_id PK
  pet_name
  avatar
  element_types
  base_hp_talent
  base_physical_attack_talent
  base_physical_defense_talent
  base_magic_attack_talent
  base_magic_defense_talent
  base_speed_talent
  learnable_skill_ids
  common_skill_sets
  common_natures
  common_individual_talent_patterns
  forms
  recognition_templates
  data_source
  data_version
  updated_at
}
```

#### NatureDefinition

```text
NatureDefinition {
  nature_id PK
  nature_name
  positive_stat
  positive_multiplier
  negative_stat
  negative_multiplier
  neutral_multiplier
}
```

#### SkillDefinition

```text
SkillDefinition {
  skill_id PK
  skill_name
  alias_names
  skill_icon
  element_type
  skill_category
  base_power
  base_energy_cost
  priority_modifier
  tags
  damage_rule
  hit_rule
  effect_script
  recognition_template
  data_source
  data_version
  updated_at
}
```

#### EffectDefinition

```text
EffectDefinition {
  effect_id PK
  name
  category
  polarity
  scope
  max_layers
  stack_rule
  duration_type
  clear_on_switch
  clear_by_normal_dispel
  clear_by_mark_dispel
  clear_by_abnormal_cleanse
  calculation_hooks
  stat_modifiers
  damage_modifiers
  skill_cost_modifiers
  action_rule_modifiers
  icon_id
  is_visible_icon
  display_group
  data_version
}
```

#### MarkDefinition

```text
MarkDefinition {
  mark_id PK
  mark_name
  polarity                 // positive / negative
  max_layers
  stack_rule
  conflict_policy
  clear_on_switch = false
  clear_by_mark_dispel
  calculation_hooks
  icon_id
}
```

#### WeatherDefinition

```text
WeatherDefinition {
  weather_id PK
  weather_name
  conflict_policy          // replace old weather
  duration_type
  calculation_hooks
  icon_id
}
```

#### TypeEffectivenessRule

```text
TypeEffectivenessRule {
  attack_element_type
  defense_element_type
  multiplier
}
```

### 5.2 用户配置表

#### PlayerPetBuild

```text
PlayerPetBuild {
  build_id PK
  pet_id
  nature_id
  individual_talent_distribution
  skill_ids
  final_stats_cache
  created_at
  updated_at
}
```

### 5.3 战斗运行时与事件表

#### BattleSessionRecord

```text
BattleSessionRecord {
  battle_id PK
  phase
  turn_number
  my_side_state_json
  enemy_side_state_json
  battlefield_state_json
  created_at
  updated_at
}
```

#### BattleEvent

```text
BattleEvent {
  event_id PK
  battle_id
  turn_number
  timestamp
  event_type
  actor_side
  actor_pet_id
  target_side
  target_pet_id
  skill_id
  payload_json
  snapshot_id
  source
  confidence
  manual_override
}
```

#### DamageEventPayload

```text
DamageEventPayload {
  attacker
  defender
  skill
  skill_confirmed
  damage_value
  hp_percent_before
  hp_percent_after
  hp_percent_delta
  enemy_hp_percent_damage
  is_multi_hit
  damage_record_mode
  total_hit_count
  total_damage_value
  total_hp_percent_damage
  hit_details
  type_effectiveness
  special_skill_effect
}
```

#### EffectChangeEventPayload

```text
EffectChangeEventPayload {
  change_type
  effect_id
  effect_name
  category
  target_side
  target_pet
  target_skill_slot
  layers_before
  layers_after
  duration_before
  duration_after
  source_skill
  source_actor
  condition_branch
  reason
}
```

#### BattleSnapshot

```text
BattleSnapshot {
  snapshot_id PK
  battle_id
  turn_number
  timestamp
  full_effect_snapshot_json
  full_runtime_state_json
}
```

#### BuildCandidateRecord

```text
BuildCandidateRecord {
  candidate_id PK
  battle_id
  side_id
  pet_id
  nature_id
  individual_talent_distribution_json
  final_hp
  final_physical_attack
  final_physical_defense
  final_magic_attack
  final_magic_defense
  final_speed
  possible_skills_json
  skill_weights_json
  match_score
  confidence
  is_excluded
  excluded_reason
  matched_event_ids_json
  mismatched_event_ids_json
}
```

------

## 6. 核心流程设计

### 6.1 准备阶段流程

```text
用户创建战斗
  ↓
录入己方 6 只精灵完整配置
  ↓
读取 PlayerPetBuild，计算己方面板属性
  ↓
录入敌方 6 只精灵种类
  ↓
读取 PetDefinition、SkillDefinition、NatureDefinition
  ↓
为敌方每只精灵生成 BuildCandidate 集合
  ↓
计算敌方候选六维属性和速度区间
  ↓
进入战斗阶段
```

### 6.2 伤害事件处理流程

```text
用户录入伤害事件
  ↓
EventNormalizer 标准化 DamageEvent
  ↓
SnapshotService 保存伤害发生瞬间 BattleEffectSnapshot
  ↓
BattleEventStore 保存事件
  ↓
BattleStateEngine 更新生命百分比等运行时状态
  ↓
InferenceEngine 根据事件过滤候选配置
  ↓
DamageCalculator 重新计算当前伤害区间
  ↓
SpeedJudgeService 重新计算先手概率
  ↓
UI 刷新展示
```

### 6.3 状态变化流程

```text
用户录入状态变化 / 技能 effect_script 触发状态变化
  ↓
生成 EffectChangeEvent
  ↓
读取 EffectDefinition / MarkDefinition / WeatherDefinition
  ↓
BattleStateEngine 应用变化
  ↓
如果是印记：更新 SideMarkState 对应槽位
  ↓
如果是天气：替换 BattlefieldState.weather
  ↓
如果是普通增减益：挂到对应精灵或技能槽
  ↓
如果是瞬时资源变化：只记录事件，不生成常驻图标
  ↓
刷新当前状态和 UI
```

### 6.4 切换流程

```text
用户录入切换事件
  ↓
保存切换前状态快照
  ↓
BattleStateEngine 找到离场精灵身上的效果
  ↓
清除 clear_on_switch = true 的效果
  ↓
为每个被清除效果生成 switch_clear 类型 EffectChangeEvent
  ↓
保留印记、天气、冻结、永久效果和明确不切换清除效果
  ↓
更新 active_pet
  ↓
刷新伤害、速度、状态展示
```

### 6.5 手动纠错流程

```text
用户选择历史事件
  ↓
提交修正内容
  ↓
生成 manual_correction 事件
  ↓
从被修正事件开始重放后续事件
  ↓
重建运行时状态和快照
  ↓
重新执行候选过滤
  ↓
刷新 UI，并标记哪些结果因修正发生变化
```

------

## 7. 推算策略设计

### 7.1 我方攻击敌方

目标：主要反推敌方生命、物防、魔防、防御相关性格、防御相关个体资质，以及是否存在防御技能减伤或其他状态影响。

流程：

```text
读取我方确定配置
读取我方技能和攻击属性
读取敌方候选配置
读取伤害快照
枚举敌方候选配置
计算理论伤害
对比实际 damage_value 和 enemy_hp_percent_damage
更新候选分数
```

### 7.2 敌方攻击我方，技能已知

目标：主要反推敌方物攻、魔攻、攻击相关性格、攻击相关个体资质和增伤状态。

流程：

```text
读取敌方已确认技能
枚举敌方候选配置
使用我方确定防御属性计算理论伤害
对比实际 damage_value
过滤候选
```

### 7.3 敌方攻击我方，技能未知

目标：同时推算敌方技能和攻击配置。

流程：

```text
读取敌方 learnable_skill_ids
枚举 possible_skill
枚举 BuildCandidate
形成 skill + candidate 联合候选
计算理论伤害
对比实际 damage_value
更新技能权重和配置置信度
```

### 7.4 误差与置信度

建议第一版配置以下参数：

```text
damage_tolerance_absolute = 2 ~ 3
damage_tolerance_percent = 1% ~ 2%
hp_percent_tolerance = 0.5% ~ 1.0%
low_confidence_event_weight = 0.3
manual_event_weight = 1.0
auto_recognition_event_weight = recognition_confidence
```

候选评分可先采用简单规则：

```text
error = abs(theoretical_damage - actual_damage)
if error <= tolerance:
  score += event_weight
else:
  score -= event_weight * penalty(error)
```

高置信排除条件：

```text
if event.confidence >= 0.9
and snapshot_confidence >= 0.9
and theoretical_damage_range cannot cover actual_damage even with tolerance:
  is_excluded = true
  excluded_reason = "理论伤害无法解释实际伤害"
```

------

## 8. 多段伤害设计

第一版遵循“总伤害优先”。

运行时 DamageEvent：

```text
is_multi_hit = true / false
damage_record_mode = single / multi_total_only / multi_with_hits
damage_value = 用于推算的主伤害值
total_damage_value = 多段最终显示总伤害
hit_details = null by default
```

规则：

- 单段技能：damage_value = 单段伤害。
- 多段技能：damage_value = 最终显示总伤害。
- MVP 不要求记录每一段。
- 技能数据库仍然记录 hit_rule，用于未来解释多段规则。
- 如果多段技能逐段状态触发会影响推算，但当前未识别逐段，则降低该事件置信度。

------

## 9. 接口设计草案

如果实现为前端 + 本地服务，可设计如下接口；如果是纯前端本地应用，也可以把这些接口理解为 service 方法。

### 9.1 战斗会话

```text
POST /battles
GET /battles/{battle_id}
POST /battles/{battle_id}/lineup
POST /battles/{battle_id}/start
POST /battles/{battle_id}/finish
```

### 9.2 事件

```text
POST /battles/{battle_id}/events
GET /battles/{battle_id}/events
PATCH /battles/{battle_id}/events/{event_id}/correction
POST /battles/{battle_id}/replay
```

### 9.3 状态与快照

```text
GET /battles/{battle_id}/state
GET /battles/{battle_id}/snapshots/{snapshot_id}
POST /battles/{battle_id}/effects
PATCH /battles/{battle_id}/effects/{effect_instance_id}
DELETE /battles/{battle_id}/effects/{effect_instance_id}
```

### 9.4 计算结果

```text
GET /battles/{battle_id}/damage-preview
GET /battles/{battle_id}/speed-judge
GET /battles/{battle_id}/enemy-candidates
GET /battles/{battle_id}/candidate-explanations/{candidate_id}
```

### 9.5 规则数据

```text
GET /pets?q=
GET /pets/{pet_id}
GET /skills?q=
GET /skills/{skill_id}
GET /effects?q=
GET /marks
GET /weathers
```

------

## 10. 非功能性设计

### 10.1 性能设计

潜在性能压力来自：

- 单只敌方精灵全量候选可达约 4.6 万。
- 六只敌方精灵候选总数可能接近 28 万。
- 敌方技能未知时，需要枚举“技能 + 配置”联合候选。
- 每次状态变化后，伤害区间和速度概率都要刷新。

优化策略：

1. 候选生成后缓存最终六维属性。
2. 对相同最终六维属性的候选聚合计算。
3. 已排除候选不参与实时伤害区间。
4. 常见候选优先展示，全量候选后台过滤。
5. 伤害计算结果按 `(attacker_build, defender_build, skill_id, snapshot_hash)` 缓存。
6. 状态快照生成 hash，状态未变化时复用计算结果。
7. UI 只展示 top-K 候选和区间摘要，不渲染全部候选。
8. 图像识别后续作为异步输入，不阻塞计算链路。

### 10.2 可靠性设计

- 所有关键事件记录 source 和 confidence。
- 手动输入优先级最高。
- 事件日志可回放。
- 快照不可变。
- 低置信事件不强排除候选。
- 候选排除必须记录 excluded_reason。
- 数据库规则带 data_version，防止规则变更后旧战斗解释混乱。

### 10.3 可维护性设计

- 状态统一使用 BattleEffectDefinition + BattleEffectInstance。
- 技能效果拆成 EffectOperation，而不是写死自然语言。
- 特殊公式通过 special_formula_id 注册处理器。
- UI 展示分组由 display_group 派生，不作为计算来源。
- 静态规则、运行时状态、事件日志三类数据严格分离。

### 10.4 可扩展性设计

为后续扩展预留：

- RecognitionAdapter：图像识别输入。
- HitDetail：逐段伤害。
- SkillWeightModel：技能概率模型。
- MissingEffectDetector：遗漏增伤 / 减伤提示。
- CandidateJointInference：速度、伤害、技能联合判断。
- CloudRuleSync：规则库同步。

------

## 11. 第一版里程碑拆分

### M1：规则数据与己方配置

- PetDefinition / NatureDefinition / SkillDefinition 基础表。
- 己方 PlayerPetBuild 管理。
- 面板属性计算。
- 精灵和技能搜索。

### M2：战斗会话与手动输入

- 创建战斗。
- 录入双方阵容。
- 录入当前对位。
- 手动输入技能、伤害、状态、天气、印记、切换。

### M3：状态引擎与事件日志

- BattleEffectInstance。
- SideMarkState。
- BattlefieldState。
- EffectChangeEvent。
- DamageEvent。
- 快照保存。
- 事件回放。

### M4：候选生成与推算

- 敌方 BuildCandidate 生成。
- 候选面板属性缓存。
- 我方攻击敌方时过滤候选。
- 敌方攻击我方且技能已知时过滤候选。
- 敌方技能未知时做 skill + candidate 联合枚举。

### M5：伤害与速度展示

- 我方技能伤害区间。
- 敌方已知 / 可能技能伤害区间。
- 生命百分比展示。
- 击杀判断。
- 速度区间与先手概率。

### M6：纠错与解释

- 修改历史事件。
- 重放重算。
- 候选排除原因。
- 事件证据链。
- 低置信事件标记。

------

## 12. 关键风险与待确认问题

### 12.1 伤害公式风险

完整伤害公式、取整时机、天气 / 印记 / 防御技能减伤的叠加顺序可能需要实测确认。设计上通过 DamageRule.rounding_policy 和 special_formula_id 预留扩展。

### 12.2 状态规则风险

中毒、灼烧、萌化、奉献等是否切换清除不能只靠大类推断，需要逐个状态配置 clear_on_switch。第一版应允许手动修正状态生命周期。

### 12.3 印记冲突风险

同方向不同名印记是覆盖、失败还是保留，需要实测。第一版默认按 conflict_policy 配置，建议默认替换旧印记并记录 replace_mark 事件。

### 12.4 候选规模风险

全量候选规模较大，需要做候选聚合、缓存和增量计算。MVP 可以先限制只对当前上场敌方精灵做全量实时计算，后备敌方精灵按需计算。

### 12.5 图像识别风险

识别不是第一阶段主链路。第二阶段所有识别结果必须进入手动确认 / 纠错机制，避免低置信识别污染推算结果。

------

## 13. 第一版验收标准

第一版 MVP 可以按以下标准验收：

1. 能创建一场战斗并录入双方六只精灵。
2. 能录入己方完整配置并正确计算六维面板属性。
3. 能为敌方精灵生成候选配置集合。
4. 能手动录入伤害事件，并保存 damage_value、扣血百分比和状态快照。
5. 能根据我方打敌方的伤害过滤敌方防御侧候选。
6. 能根据敌方打我方的伤害过滤敌方攻击侧候选。
7. 技能未知时能枚举“技能 + 配置”联合候选。
8. 能展示我方技能对敌方的伤害区间和生命百分比。
9. 能展示敌方技能对我方的伤害区间和生命百分比。
10. 能展示敌方速度区间、同速情况和综合先手概率。
11. 能正确处理印记不随切换清除、天气不随切换清除、普通增减益默认随切换清除。
12. 能记录事件日志、手动修正历史事件，并触发重放重算。
13. 多段伤害默认只记录最终总伤害，且 damage_value 统一作为推算主伤害值。

------

## 14. 建议下一步

下一步建议先进入“详细设计 / 原型设计”阶段，重点产出以下内容：

1. BattleSession / BattleEvent / BuildCandidate / BattleEffectInstance 的 TypeScript 或后端实体定义。
2. PetDefinition、SkillDefinition、EffectDefinition、MarkDefinition 的数据库建表草案。
3. 准备阶段 UI 原型。
4. 战斗事件录入 UI 原型。
5. 候选过滤算法的最小可运行 demo。
6. 一组模拟战斗数据，用于验证候选收敛链路。