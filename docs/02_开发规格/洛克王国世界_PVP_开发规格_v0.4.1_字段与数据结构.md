# 洛克王国世界 PVP 战斗信息获取与敌方配置推算系统开发规格 v0.4.1

> 修订日期：2026-05-11  
> 本文档从主需求文档中拆出，专门维护开发字段、数据结构、数据库表、枚举、事件日志和实现约束。  
> 命名要求：所有精灵相关英文词条统一使用 `elf`。

---

## 0. 开发规格定位

本文档用于指导数据库、后端、前端、图像识别和计算模块实现。

与主需求文档的分工：

| 文档 | 内容边界 |
|---|---|
| 需求说明 | 业务流程、规则解释、阶段目标、展示需求、待确认问题 |
| 开发规格 | 字段字典、结构定义、枚举值、数据库表、索引、事件、快照、计算上下文 |

本文档中字段采用 `snake_case` 表示数据库字段；代码结构可以按语言规范转换为 `camelCase` 或 `PascalCase`。

---

## 1. 命名规范

### 1.1 精灵缩写

统一使用：

```text
elf
```

正式命名清单：

| 用途 | 正式命名 |
|---|---|
| 精灵唯一 ID | `elf_id` |
| 精灵名称 | `elf_name` |
| 精灵静态定义 | `ElfDefinition` |
| 敌方精灵运行时状态 | `EnemyElfState` |
| 战斗内精灵状态表 | `battle_elf_state` |
| 状态归属精灵 ID | `owner_elf_id` |
| 状态来源精灵 ID | `source_elf_id` |
| 事件行动方精灵 ID | `actor_elf_id` |
| 事件目标精灵 ID | `target_elf_id` |
| 伤害攻击方精灵 ID | `attacker_elf_id` |
| 伤害防御方精灵 ID | `defender_elf_id` |
| 我方当前在场精灵 ID | `self_active_elf_id` |
| 敌方当前在场精灵 ID | `enemy_active_elf_id` |
| 精灵切换事件 | `switch_elf` |
| 精灵归属范围枚举 | `owner_scope = elf` |
| 精灵挂载目标枚举 | `attach_target_type = elf` |

### 1.2 精灵不设置别名

`ElfDefinition` 不设置 `alias_names`。

技能可以保留 `alias_names`，用于技能 OCR 误识别、玩家搜索和手动输入容错。

---

## 2. 静态定义数据

### 2.1 精灵定义 `ElfDefinition`

```text
ElfDefinition {
  elf_id
  elf_name
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

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `elf_id` | string | 是 | 精灵唯一 ID，所有运行时引用使用该字段 |
| `elf_name` | string | 是 | 精灵标准名称，不设置别名 |
| `avatar` | string | 是 | 精灵头像资源路径或资源 ID |
| `element_types` | array | 是 | 系别数组，支持单系或双系 |
| `base_hp_talent` | int | 是 | 生命种族资质 |
| `base_physical_attack_talent` | int | 是 | 物攻种族资质 |
| `base_physical_defense_talent` | int | 是 | 物防种族资质 |
| `base_magic_attack_talent` | int | 是 | 魔攻种族资质 |
| `base_magic_defense_talent` | int | 是 | 魔防种族资质 |
| `base_speed_talent` | int | 是 | 速度种族资质 |
| `learnable_skill_ids` | array | 是 | 可学习技能列表，敌方技能未知时用于枚举 |
| `common_skill_sets` | array | 否 | 常见技能组，只用于候选权重 |
| `common_natures` | array | 否 | 常见性格，只用于候选权重 |
| `common_individual_talent_patterns` | array | 否 | 常见个体资质分布，只用于候选权重 |
| `forms` | array | 否 | 形态信息；若种族资质不同，建议拆为不同 `elf_id` |
| `recognition_templates` | array | 否 | 图像识别模板 |
| `data_source` | string | 否 | 数据来源 |
| `data_version` | string | 否 | 数据版本 |
| `updated_at` | datetime | 否 | 更新时间 |

### 2.2 性格定义 `NatureDefinition`

```text
NatureDefinition {
  nature_id
  nature_name
  positive_stat
  positive_multiplier
  negative_stat
  negative_multiplier
  neutral_multiplier
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `nature_id` | string | 是 | 性格唯一 ID |
| `nature_name` | string | 是 | 性格名称 |
| `positive_stat` | enum | 是 | 正面修正维度 |
| `positive_multiplier` | decimal | 是 | 当前固定为 1.2 |
| `negative_stat` | enum | 是 | 负面修正维度 |
| `negative_multiplier` | decimal | 是 | 当前固定为 0.9 |
| `neutral_multiplier` | decimal | 是 | 当前固定为 1.0 |

`positive_stat` / `negative_stat` 可取：

```text
hp
physical_attack
physical_defense
magic_attack
magic_defense
speed
```

### 2.3 技能定义 `SkillDefinition`

```text
SkillDefinition {
  skill_id
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
  effect_operations
  recognition_template

  data_source
  data_version
  updated_at
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `skill_id` | string | 是 | 技能唯一 ID |
| `skill_name` | string | 是 | 技能标准名称 |
| `alias_names` | array | 否 | 技能别名或 OCR 常见误识别名 |
| `skill_icon` | string | 否 | 技能图标 |
| `element_type` | enum | 是 | 技能系别 |
| `skill_category` | enum | 是 | `physical`、`magic`、`status`、`special` |
| `base_power` | int | 条件 | 基础威力；状态技能可为空 |
| `base_energy_cost` | int | 是 | 基础能耗 |
| `priority_modifier` | int | 否 | 技能先手修正，默认 0 |
| `tags` | array | 否 | 检索标签 |
| `damage_rule` | object | 条件 | 伤害规则，攻击技能必填 |
| `hit_rule` | object | 否 | 单次、动画多段、连击规则 |
| `effect_operations` | array | 否 | 技能造成的状态变化操作 |
| `recognition_template` | object | 否 | 图像识别模板 |
| `data_source` | string | 否 | 数据来源 |
| `data_version` | string | 否 | 数据版本 |
| `updated_at` | datetime | 否 | 更新时间 |

### 2.4 伤害规则 `DamageRule`

```text
DamageRule {
  damage_type
  attack_stat
  defense_stat
  power_source
  fixed_damage_value
  percent_damage_base

  ignore_defense
  ignore_type_effectiveness

  affected_by_stat_modifier
  affected_by_damage_modifier
  affected_by_weather
  affected_by_mark
  affected_by_abnormal
  affected_by_skill_modifier

  rounding_policy
  special_formula_id
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `damage_type` | enum | 是 | `normal_formula`、`fixed`、`percent_hp`、`special_formula` |
| `attack_stat` | enum | 条件 | `physical_attack` 或 `magic_attack` |
| `defense_stat` | enum | 条件 | `physical_defense` 或 `magic_defense` |
| `power_source` | enum | 否 | `base_power`、`dynamic_by_effect`、`dynamic_by_hp`、`none` |
| `fixed_damage_value` | int | 条件 | 固定伤害值 |
| `percent_damage_base` | enum | 条件 | 百分比伤害基准 |
| `ignore_defense` | bool | 是 | 是否无视防御 |
| `ignore_type_effectiveness` | bool | 是 | 是否无视克制 |
| `affected_by_stat_modifier` | bool | 是 | 是否受普通属性修正影响 |
| `affected_by_damage_modifier` | bool | 是 | 是否受增伤减伤影响 |
| `affected_by_weather` | bool | 是 | 是否受天气影响 |
| `affected_by_mark` | bool | 是 | 是否受印记影响 |
| `affected_by_abnormal` | bool | 是 | 是否受异常影响 |
| `affected_by_skill_modifier` | bool | 是 | 是否受技能威力等修正影响 |
| `rounding_policy` | enum | 条件 | 取整策略，待完整公式确认 |
| `special_formula_id` | string | 条件 | 特殊公式处理器 ID |

### 2.5 命中 / 连击规则 `HitRule`

```text
HitRule {
  damage_display_type

  is_combo
  base_hit_count
  hit_count_type
  min_hit_count
  max_hit_count
  hit_count_modifier_allowed

  visual_total_damage_displayed
  runtime_record_strategy

  combo_calculation_mode
  combo_total_displayed
  combo_per_hit_same_damage
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `damage_display_type` | enum | 是 | `single_damage`、`visual_total_damage`、`combo_repeated_damage`、`special_damage` |
| `is_combo` | bool | 是 | 是否为连击 |
| `base_hit_count` | int | 条件 | 技能基础连击次数 |
| `hit_count_type` | enum | 是 | `single`、`fixed`、`effect_modified`、`skill_specific` |
| `min_hit_count` | int | 否 | 最小连击次数 |
| `max_hit_count` | int | 否 | 最大连击次数 |
| `hit_count_modifier_allowed` | bool | 是 | 是否允许状态修改连击次数 |
| `visual_total_damage_displayed` | bool | 是 | 动画多段是否显示最终总伤害 |
| `runtime_record_strategy` | enum | 是 | `single_value`、`final_total_only`、`per_hit_value_and_count` |
| `combo_calculation_mode` | enum | 条件 | `per_hit_formula_then_repeat`、`special_formula` |
| `combo_total_displayed` | bool | 是 | 连击是否显示总伤害；当前规则为 false |
| `combo_per_hit_same_damage` | bool | 是 | 连击每段是否相同；当前规则为 true |

推荐配置：

```text
普通单次技能：
damage_display_type = single_damage
runtime_record_strategy = single_value

动画多段但最终显示总伤害：
damage_display_type = visual_total_damage
visual_total_damage_displayed = true
runtime_record_strategy = final_total_only

连击：
damage_display_type = combo_repeated_damage
is_combo = true
combo_total_displayed = false
combo_per_hit_same_damage = true
runtime_record_strategy = per_hit_value_and_count
```

### 2.6 技能效果操作 `EffectOperation`

```text
EffectOperation {
  op_id
  op_type
  target

  effect_id
  value_type
  value
  layers

  duration_turns
  duration_uses

  condition
  timing
  probability

  can_be_manual_corrected
  note
}
```

`op_type` 推荐枚举：

| op_type | 含义 |
|---|---|
| `apply_effect` | 添加状态 |
| `remove_effect` | 移除状态 |
| `stack_effect` | 修改层数 |
| `refresh_effect` | 刷新持续时间 |
| `convert_effect` | 状态转换 |
| `transfer_effect` | 状态转移 |
| `dispel_effect` | 驱散状态 |
| `modify_skill_cost` | 修改技能能耗 |
| `modify_skill_power` | 修改技能威力 |
| `modify_combo_count` | 修改连击次数 |
| `set_weather` | 设置天气 |
| `heal` | 回复生命 |
| `energy_change` | 改变能量 |
| `special_rule` | 特殊规则 |

### 2.7 统一状态定义 `EffectDefinition`

```text
EffectDefinition {
  effect_id
  effect_name
  icon

  category
  polarity
  display_group
  display_priority

  owner_scope
  target_scope
  attach_target_type

  is_visible_icon
  is_recognizable_by_icon
  recognition_alias

  default_layers
  max_layers
  stack_rule
  refresh_rule

  duration_type
  default_duration_turns
  default_duration_uses

  clear_on_switch
  clear_by_abnormal_cleanse
  clear_by_stat_clear
  clear_by_mark_clear
  clear_by_weather_replace
  clear_by_skill_specific

  can_be_transferred
  can_be_converted
  can_be_inherited
  can_be_stolen
  can_be_doubled

  conflict_group
  conflict_policy

  formula_hooks
  stat_modifier
  damage_modifier
  skill_modifier
  action_modifier
  resource_modifier

  special_rule_id
  developer_notes
}
```

关键规则：

- `category` 是标签，不是独立系统。
- 状态是否切换清除由 `clear_on_switch` 决定。
- 印记、天气、异常、普通属性变化全部使用 `EffectDefinition`。
- 不强制建立 `MarkDefinition` 或 `WeatherDefinition` 主规则表；可以建立查询视图。

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `effect_id` | string | 是 | 状态唯一 ID |
| `effect_name` | string | 是 | 状态名称 |
| `icon` | string | 条件 | 图标资源，图标可识别状态建议必填 |
| `category` | enum | 是 | 分类标签 |
| `polarity` | enum | 是 | `positive`、`negative`、`neutral`、`mixed` |
| `display_group` | enum | 是 | UI 展示分区 |
| `display_priority` | int | 否 | 展示排序 |
| `owner_scope` | enum | 是 | `elf`、`side`、`field`、`skill_slot`、`turn` |
| `target_scope` | enum | 是 | 作用目标范围 |
| `attach_target_type` | enum | 是 | 实例挂载目标类型 |
| `is_visible_icon` | bool | 是 | 是否显示图标 |
| `is_recognizable_by_icon` | bool | 是 | 是否可通过图标识别 |
| `recognition_alias` | array | 否 | 状态识别容错名，不是精灵别名 |
| `default_layers` | int | 否 | 默认层数 |
| `max_layers` | int | 否 | 最大层数 |
| `stack_rule` | enum | 是 | 叠层规则 |
| `refresh_rule` | enum | 否 | 再次获得时是否刷新持续时间 |
| `duration_type` | enum | 是 | 持续类型 |
| `default_duration_turns` | int | 否 | 默认持续回合数 |
| `default_duration_uses` | int | 否 | 默认持续次数 |
| `clear_on_switch` | bool | 是 | 切换当前在场精灵时是否清除 |
| `clear_by_abnormal_cleanse` | bool | 是 | 是否可被清除异常技能去除 |
| `clear_by_stat_clear` | bool | 是 | 是否可被清除普通属性变化技能去除 |
| `clear_by_mark_clear` | bool | 是 | 是否可被清除印记技能去除 |
| `clear_by_weather_replace` | bool | 是 | 是否被新天气替换 |
| `clear_by_skill_specific` | bool | 是 | 是否只能由特定技能处理 |
| `can_be_transferred` | bool | 是 | 是否可被转移 |
| `can_be_converted` | bool | 是 | 是否可被转换 |
| `can_be_inherited` | bool | 是 | 是否可被继承 |
| `can_be_stolen` | bool | 是 | 是否可被夺取 |
| `can_be_doubled` | bool | 是 | 是否可被翻倍层数 |
| `conflict_group` | string | 否 | 互斥组 |
| `conflict_policy` | enum | 否 | 同组冲突处理策略 |
| `formula_hooks` | array | 否 | 参与公式环节 |
| `stat_modifier` | object | 否 | 属性修正规则 |
| `damage_modifier` | object | 否 | 伤害修正规则 |
| `skill_modifier` | object | 否 | 技能能耗、威力、冷却等规则 |
| `action_modifier` | object | 否 | 先手、蓄力、无法行动等规则 |
| `resource_modifier` | object | 否 | 生命、能量持续结算规则 |
| `special_rule_id` | string | 否 | 特殊规则处理器 ID |
| `developer_notes` | string | 否 | 开发备注 |

---

## 3. 运行时数据结构

### 3.1 我方 / 敌方精灵运行时状态 `BattleElfState`

```text
BattleElfState {
  battle_id
  side
  elf_id
  elf_name
  avatar

  panel_stats
  current_hp_value
  current_hp_percent
  energy

  skill_ids
  confirmed_skill_ids

  active_effect_instance_ids

  is_active_elf
  is_defeated
  last_switch_turn
  manual_override
}
```

说明：

- 运行时状态不拆 `buffs`、`debuffs`、`marks`、`abnormal_status`。
- 所有状态统一通过 `active_effect_instance_ids` 关联。
- 展示层根据 `EffectDefinition.category` 分组。

### 3.2 敌方候选配置 `BuildCandidate`

```text
BuildCandidate {
  candidate_id
  battle_id
  elf_id
  nature_id
  individual_talent_distribution

  final_hp
  final_physical_attack
  final_physical_defense
  final_magic_attack
  final_magic_defense
  final_speed

  possible_skill_ids
  confirmed_skill_ids

  match_score
  confidence
  is_excluded
  excluded_reason
  evidence_ids
}
```

注意：候选配置只保存面板属性，不保存状态修正后的临时属性。

### 3.3 状态实例 `BattleEffectInstance`

```text
BattleEffectInstance {
  instance_id
  battle_id
  effect_id

  owner_scope
  owner_side
  owner_elf_id
  owner_skill_slot_id
  field_id

  source_side
  source_elf_id
  source_skill_id
  source_event_id

  layers
  remaining_turns
  remaining_uses
  is_active

  applied_turn
  expire_turn
  last_updated_turn

  recognition_source
  recognition_confidence
  manual_override

  notes
}
```

字段约束：

- `owner_scope = elf` 时，`owner_elf_id` 必填。
- `owner_scope = side` 时，`owner_side` 必填。
- `owner_scope = field` 时，可填写 `field_id`。
- `owner_scope = skill_slot` 时，`owner_skill_slot_id` 必填。
- 无层数状态 `layers = 1`。

### 3.4 状态快照 `BattleEffectSnapshot`

```text
BattleEffectSnapshot {
  snapshot_id
  battle_id
  turn_number
  timestamp

  active_effect_instance_ids

  self_active_elf_id
  enemy_active_elf_id

  self_elf_effect_ids
  enemy_elf_effect_ids
  self_side_effect_ids
  enemy_side_effect_ids
  field_effect_ids
  skill_slot_effect_ids
  turn_effect_ids

  source_event_id
}
```

说明：

- 伤害事件、治疗事件、能量变化事件、切换事件都应引用快照。
- 计算层优先读取 `active_effect_instance_ids`。
- 分组字段只用于查询和展示。
- 不再单独维护 `weather_snapshot`、`mark_snapshot`、`abnormal_status_snapshot` 作为计算主字段。

### 3.5 伤害公式上下文 `DamageFormulaContext`

```text
DamageFormulaContext {
  context_id
  battle_id

  attacker_elf_id
  defender_elf_id
  skill_id

  attacker_panel_stats
  defender_panel_stats

  effect_snapshot_id
  active_effect_instance_ids

  type_effectiveness
  damage_rule
  hit_rule

  damage_display_type
  hit_count

  special_formula_id
  rounding_policy
}
```

说明：

- 这是计算时上下文，不是永久属性。
- 面板属性和状态效果在这里结合。
- 不保存“战斗有效属性”字段。

### 3.6 速度上下文 `SpeedContext`

```text
SpeedContext {
  context_id
  battle_id
  turn_number

  self_elf_id
  enemy_elf_id
  self_panel_speed
  enemy_panel_speed_candidates

  effect_snapshot_id
  action_rule_effect_ids
  skill_priority_modifiers

  result_type
  self_first_probability
  enemy_first_probability
  explanation
}
```

### 3.7 伤害结果 `DamageResult`

```text
DamageResult {
  attacker_elf_id
  defender_elf_id
  skill_id

  damage_display_type

  damage_value_min
  damage_value_max
  damage_percent_min
  damage_percent_max

  per_hit_damage_min
  per_hit_damage_max
  hit_count_min
  hit_count_max
  total_combo_damage_min
  total_combo_damage_max

  is_exact
  can_knock_out
  can_first_move_knock_out
  speed_judgement

  confidence
  explanation
}
```

---

## 4. 事件结构

### 4.1 通用战斗事件 `BattleEvent`

```text
BattleEvent {
  event_id
  battle_id
  turn_number
  timestamp
  event_type

  actor_side
  actor_elf_id
  target_side
  target_elf_id

  skill_id
  skill_confirmed

  snapshot_id

  source
  recognition_confidence
  manual_override
  notes
}
```

`event_type` 推荐枚举：

| event_type | 含义 |
|---|---|
| `skill_use` | 使用技能 |
| `damage` | 造成伤害 |
| `combo_damage` | 连击伤害 |
| `heal` | 回复生命 |
| `energy_change` | 能量变化 |
| `effect_apply` | 获得状态 |
| `effect_remove` | 移除状态 |
| `effect_stack` | 状态叠层 |
| `effect_convert` | 状态转换 |
| `effect_transfer` | 状态转移 |
| `effect_dispel` | 状态驱散 |
| `switch_elf` | 切换精灵 |
| `switch_clear` | 切换导致状态清除 |
| `weather_change` | 天气变化 |
| `mark_change` | 印记变化，可作为 effect 事件展示别名 |

### 4.2 伤害事件 `DamageEvent`

```text
DamageEvent {
  event_id
  battle_event_id

  damage_display_type

  damage_value
  final_total_damage_value

  per_hit_damage_value
  hit_count
  computed_total_damage_value
  combo_count_source
  combo_confidence

  hp_percent_before
  hp_percent_after
  hp_percent_delta
  enemy_hp_percent_damage

  type_effectiveness
  formula_context_id
  special_formula_id

  calculation_confidence
  recognition_confidence
  manual_override
}
```

规则：

- `single_damage`：`damage_value` 为单次伤害。
- `visual_total_damage`：`damage_value` 和 `final_total_damage_value` 均为最终总伤害。
- `combo_repeated_damage`：记录 `per_hit_damage_value`、`hit_count`、`computed_total_damage_value`。
- 连击候选过滤优先使用 `per_hit_damage_value`；击杀判断使用 `computed_total_damage_value`。

### 4.3 状态变化事件 `EffectChangeEvent`

```text
EffectChangeEvent {
  event_id
  battle_event_id
  turn_number
  timestamp

  change_type
  effect_instance_id
  effect_id
  effect_name
  category

  target_side
  target_elf_id
  target_skill_slot_id
  owner_scope

  layers_before
  layers_after
  duration_before
  duration_after

  source_skill_id
  source_elf_id
  condition_branch
  reason

  source
  recognition_confidence
  manual_override
}
```

`change_type` 推荐枚举：

```text
apply
remove
stack
refresh
replace
convert
transfer
dispel
switch_clear
switch_keep
expire
consume
```

### 4.4 生命 / 能量变化事件 `ResourceChangeEvent`

```text
ResourceChangeEvent {
  event_id
  battle_event_id

  resource_type
  change_type

  source_side
  source_elf_id
  target_side
  target_elf_id

  value_type
  value
  before_value
  after_value

  confidence
  manual_override
}
```

---

## 5. 推荐枚举

### 5.1 `category`

| 枚举值 | 含义 |
|---|---|
| `stat_modifier` | 普通属性修正 |
| `abnormal` | 异常状态 |
| `special_status` | 特殊层数或特殊规则状态 |
| `mark` | 印记 |
| `weather` | 天气 / 战场环境 |
| `damage_modifier` | 增伤 / 减伤 |
| `skill_modifier` | 技能槽修正 |
| `combo_modifier` | 连击数修正 |
| `action_rule` | 行动规则 |
| `resource_rule` | 生命 / 能量持续结算 |
| `special_rule` | 复杂特殊机制 |

### 5.2 `owner_scope`

```text
elf
side
field
skill_slot
turn
```

### 5.3 `damage_display_type`

```text
single_damage
visual_total_damage
combo_repeated_damage
special_damage
```

### 5.4 `runtime_record_strategy`

```text
single_value
final_total_only
per_hit_value_and_count
```

### 5.5 `source`

```text
database_rule
auto_recognition
manual_input
system_calculated
system_inferred
```

---

## 6. 数据库表拆分

推荐表：

| 表名 | 说明 |
|---|---|
| `elf_definition` | 精灵静态数据 |
| `nature_definition` | 性格定义 |
| `skill_definition` | 技能静态数据 |
| `effect_definition` | 统一状态定义 |
| `battle` | 战斗主表 |
| `battle_elf_state` | 战斗中每只精灵运行时状态 |
| `build_candidate` | 敌方候选配置 |
| `battle_effect_instance` | 当前状态实例 |
| `battle_effect_snapshot` | 状态快照 |
| `battle_event` | 通用事件日志 |
| `damage_event` | 伤害事件详情 |
| `effect_change_event` | 状态变化事件详情 |
| `resource_change_event` | 生命 / 能量变化事件详情 |

不强制建立：

```text
mark_definition
weather_definition
abnormal_definition
```

可用视图替代：

```text
mark_effect_view = effect_definition where category = mark
weather_effect_view = effect_definition where category = weather
abnormal_effect_view = effect_definition where category in (abnormal, special_status)
```

---

## 7. 索引建议

| 表 | 索引 |
|---|---|
| `elf_definition` | `elf_id` 唯一索引 |
| `skill_definition` | `skill_id` 唯一索引 |
| `effect_definition` | `effect_id` 唯一索引，`category` 普通索引 |
| `battle_elf_state` | `battle_id + side + elf_id` |
| `battle_effect_instance` | `battle_id + owner_side + owner_elf_id`，`battle_id + category` |
| `battle_effect_snapshot` | `battle_id + turn_number + timestamp` |
| `battle_event` | `battle_id + turn_number + timestamp` |
| `damage_event` | `battle_event_id`，`battle_id + attacker_elf_id + defender_elf_id` |
| `build_candidate` | `battle_id + elf_id + is_excluded` |

---

## 8. 核心实现流程

### 8.1 状态图标识别流程

```text
截取状态栏 / 天气栏 / 印记区 / 技能槽角标区
↓
识别所有可见图标
↓
匹配 effect_definition.effect_id
↓
根据 EffectDefinition 判断 owner_scope 和默认规则
↓
生成或更新 BattleEffectInstance
↓
保存 BattleEffectSnapshot
```

### 8.2 切换精灵状态处理

```text
发生 switch_elf 事件
↓
读取离场精灵 owner_scope = elf 的 active BattleEffectInstance
↓
clear_on_switch = true：移除并记录 EffectChangeEvent(switch_clear)
↓
clear_on_switch = false：保留并记录 EffectChangeEvent(switch_keep)
↓
owner_scope = side / field 的实例不受普通切换影响
↓
生成新的 BattleEffectSnapshot
```

### 8.3 伤害事件记录流程

```text
识别技能与伤害显示类型
↓
如果 single_damage：记录 damage_value
↓
如果 visual_total_damage：记录 final_total_damage_value，并按一次伤害处理
↓
如果 combo_repeated_damage：记录 per_hit_damage_value 和 hit_count，计算 computed_total_damage_value
↓
保存 DamageEvent
↓
关联当时的 BattleEffectSnapshot
```

### 8.4 连击次数计算流程

```text
读取 SkillDefinition.hit_rule.base_hit_count
↓
读取 BattleEffectSnapshot 中 category = combo_modifier 的状态
↓
按优先级处理固定连击、加减连击、倍率连击
↓
得到最终 hit_count
↓
记录 combo_count_source 与 combo_confidence
```

优先级待实测确认。当前建议先按：

```text
固定连击 > 加减连击 > 倍率连击 > 技能基础连击
```

该优先级只是实现占位，后续可通过规则表调整。

### 8.5 敌方候选过滤流程

```text
读取 DamageEvent
↓
读取关联 BattleEffectSnapshot
↓
读取攻击方与防御方配置
↓
形成 DamageFormulaContext
↓
枚举候选配置
↓
计算理论伤害
↓
与实际伤害、扣血百分比对比
↓
更新 BuildCandidate.match_score / confidence / is_excluded
```

---

## 9. 第一阶段 MVP 必须字段

### 9.1 静态数据

| 对象 | 必须字段 |
|---|---|
| `ElfDefinition` | `elf_id`、`elf_name`、`avatar`、`element_types`、六维种族资质、`learnable_skill_ids` |
| `NatureDefinition` | 全字段 |
| `SkillDefinition` | `skill_id`、`skill_name`、`element_type`、`skill_category`、`base_power`、`base_energy_cost`、`damage_rule`、`hit_rule`、`effect_operations` |
| `EffectDefinition` | `effect_id`、`effect_name`、`category`、`polarity`、`owner_scope`、`stack_rule`、`duration_type`、`clear_on_switch`、`formula_hooks`、`is_visible_icon`、`display_group` |

### 9.2 运行时与事件

| 对象 | 必须字段 |
|---|---|
| `BattleElfState` | `battle_id`、`side`、`elf_id`、`panel_stats`、`current_hp_percent`、`energy`、`active_effect_instance_ids` |
| `BuildCandidate` | `candidate_id`、`battle_id`、`elf_id`、`nature_id`、个体资质分布、六维面板属性、`match_score`、`confidence`、`is_excluded` |
| `BattleEffectInstance` | `instance_id`、`battle_id`、`effect_id`、`owner_scope`、`owner_side`、`owner_elf_id`、`layers`、`is_active` |
| `BattleEffectSnapshot` | `snapshot_id`、`battle_id`、`turn_number`、`active_effect_instance_ids` |
| `BattleEvent` | `event_id`、`battle_id`、`turn_number`、`event_type`、`actor_side`、`actor_elf_id`、`target_side`、`target_elf_id`、`snapshot_id` |
| `DamageEvent` | `event_id`、`battle_event_id`、`damage_display_type`、`damage_value`、连击相关字段、生命百分比相关字段 |

### 9.3 第一阶段暂不实现

- 奉献具体规则。
- 高级图像识别。
- 动画多段逐段伤害识别。
- 连击每段触发独立状态。
- 根据敌方行动习惯动态更新技能概率。

---

## 10. 命名一致性检查清单

从 v0.4.1 起，正式文档、代码、数据库、事件和索引中均使用以下命名：

- 精灵唯一 ID 使用 `elf_id`。
- 精灵名称使用 `elf_name`。
- 精灵静态定义使用 `ElfDefinition`。
- 敌方精灵运行时状态使用 `EnemyElfState`。
- 状态归属精灵字段使用 `owner_elf_id`。
- 状态来源精灵字段使用 `source_elf_id`。
- 事件行动方精灵字段使用 `actor_elf_id`。
- 事件目标精灵字段使用 `target_elf_id`。
- 伤害攻击方和防御方字段使用 `attacker_elf_id`、`defender_elf_id`。
- 当前在场精灵字段使用 `self_active_elf_id`、`enemy_active_elf_id`。
- 精灵切换事件使用 `switch_elf`。
- 精灵运行时状态表使用 `battle_elf_state`。
- 精灵静态数据表使用 `elf_definition`。
- 状态归属范围枚举使用 `owner_scope = elf`。
- 精灵仍然不设置别名字段；技能别名字段保留。

---

## 11. 开发注意事项

1. 不要把状态拆成多套系统。统一使用 `EffectDefinition` 和 `BattleEffectInstance`。
2. 不要用 `category` 直接决定所有规则。规则必须落到字段上，例如 `clear_on_switch`、`owner_scope`、`formula_hooks`。
3. 不要保存“战斗有效属性”作为候选配置字段。候选配置只保存面板属性。
4. 动画多段不是连击。动画多段按最终总伤害作为一次伤害事件处理。
5. 连击需要记录单段伤害和连击次数，系统计算总伤害。
6. 每次伤害、治疗、能量变化、切换都应关联状态快照。
7. 手动输入优先级最高，必须能覆盖自动识别和系统推算。
8. 奉献暂时只记录状态，不进入第一阶段公式计算。
9. 星陨是印记，不是普通异常或普通减益。
10. 印记允许多个不同印记共存，不再维护唯一增益印记槽和减益印记槽。
