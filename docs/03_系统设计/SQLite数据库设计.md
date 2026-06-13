# 洛克王国世界 PVP 推算系统 SQLite 数据库设计文档 v0.4.1-local

> 设计日期：2026-05-11  
> 设计依据：`需求说明 v0.4.1`、`开发规格 v0.4.1`  
> 数据库：SQLite 3  
> 后端：Python + FastAPI + SQLAlchemy 2.x + Alembic  
> 命名要求：所有精灵相关英文词条统一使用 `elf`。

---

## 1. 设计原则

### 1.1 数据分类

数据库按三类数据组织：

| 数据类型 | 用途 | 示例 |
|---|---|---|
| 静态规则数据 | 查规则 | 精灵、性格、技能、状态、属性克制 |
| 战斗运行时数据 | 算当前结果 | 当前生命、能量、当前状态实例、敌方实时估计 |
| 事件日志数据 | 回放、纠错、解释 | 技能事件、伤害事件、状态变化事件、快照 |

### 1.2 SQLite 设计取舍

SQLite 支持本地零配置运行，但不适合无限制高度规范化。本文档采用“核心关系规范化 + 复杂规则 JSON 化”的设计：

- 高频查询字段独立成列。
- 技能规则、状态公式、候选证据、快照内容等复杂结构使用 `TEXT` 存 JSON。
- 所有 JSON 字段在代码层通过 Pydantic 校验。
- 所有关联主键使用字符串 ID，便于规则库导入导出和跨版本迁移。
- 所有布尔字段用 `INTEGER` 表示，`0=false`，`1=true`。
- 时间字段用 `TEXT` 存 ISO-8601 字符串。

### 1.3 SQLite 推荐 PRAGMA

应用启动时执行：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
```

### 1.4 通用字段约定

| 字段 | 类型 | 说明 |
|---|---|---|
| `created_at` | TEXT | 创建时间，ISO-8601 |
| `updated_at` | TEXT | 更新时间，ISO-8601 |
| `deleted_at` | TEXT | 软删除时间，可为空 |
| `data_version` | TEXT | 规则数据版本 |
| `notes` | TEXT | 人类可读备注 |

### 1.5 枚举存储约定

SQLite 没有原生 enum，统一用 `TEXT` 存储。关键枚举在应用层校验；必要字段可加 `CHECK` 约束。

---

## 2. 核心枚举

### 2.1 `side`

| 值 | 含义 |
|---|---|
| `self` | 我方 |
| `enemy` | 敌方 |

### 2.2 `phase`

| 值 | 含义 |
|---|---|
| `preparation` | 准备阶段 |
| `battle` | 战斗阶段 |
| `finished` | 已结束 |
| `archived` | 已归档 |

### 2.3 `stat_key`

| 值 | 含义 |
|---|---|
| `hp` | 生命 |
| `physical_attack` | 物攻 |
| `physical_defense` | 物防 |
| `magic_attack` | 魔攻 |
| `magic_defense` | 魔防 |
| `speed` | 速度 |

### 2.4 `skill_category`

| 值 | 含义 |
|---|---|
| `physical` | 物理攻击 |
| `magic` | 魔法攻击 |
| `status` | 状态技能 |
| `special` | 特殊技能 |

### 2.5 `effect category`

| 值 | 含义 |
|---|---|
| `stat_modifier` | 普通属性修正 |
| `abnormal` | 异常状态 |
| `special_status` | 特殊层数或特殊规则状态 |
| `mark` | 印记 |
| `weather` | 天气 / 战场环境 |
| `damage_modifier` | 吸血 / 增伤等伤害修正 |
| `skill_modifier` | 技能槽修正 |
| `combo_modifier` | 连击数修正 |
| `action_modifier` | 行动规则修正 |
| `resource_modifier` | 生命 / 能量持续结算 |
| `special_rule` | 复杂特殊机制 |

### 2.6 `owner_scope`

| 值 | 含义 |
|---|---|
| `elf` | 挂在某只精灵身上 |
| `side` | 挂在某一队伍侧 |
| `field` | 全战场 |
| `skill_slot` | 某个技能槽 |
| `turn` | 当前回合临时状态 |

### 2.7 `damage_display_type`

| 值 | 含义 |
|---|---|
| `single_damage` | 单次伤害 |
| `visual_total_damage` | 动画多段但最终显示总伤害 |
| `combo_repeated_damage` | 连击，每段相同且无总伤害 |
| `special_damage` | 特殊结算伤害 |

### 2.8 `source`

| 值 | 含义 |
|---|---|
| `database_rule` | 数据库规则 |
| `manual_input` | 手动输入 |
| `auto_recognition` | 自动识别 |
| `system_calculated` | 系统计算 |
| `system_inferred` | 系统推算 |

---

## 3. 静态规则表

## 3.1 `elf_definition` 精灵静态定义表

### 用途

记录精灵基础身份、系别、六维种族资质、可学习技能和常见配置。代码内部所有精灵引用必须使用 `elf_id`。精灵不设置别名字段。

### 建表 SQL

```sql
CREATE TABLE elf_definition (
  elf_id TEXT PRIMARY KEY,
  elf_name TEXT NOT NULL,
  avatar TEXT NOT NULL,
  element_types_json TEXT NOT NULL,

  base_hp_talent INTEGER NOT NULL,
  base_physical_attack_talent INTEGER NOT NULL,
  base_physical_defense_talent INTEGER NOT NULL,
  base_magic_attack_talent INTEGER NOT NULL,
  base_magic_defense_talent INTEGER NOT NULL,
  base_speed_talent INTEGER NOT NULL,

  common_skill_sets_json TEXT,
  common_natures_json TEXT,
  common_individual_talent_patterns_json TEXT,
  forms_json TEXT,
  recognition_templates_json TEXT,

  data_source TEXT,
  data_version TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `elf_id` | TEXT | 是 | 数据库录入 | 精灵唯一 ID。所有运行时状态、实时估计、事件日志都引用该字段。 |
| `elf_name` | TEXT | 是 | 数据库录入 | 精灵标准名称。用于 UI 展示和搜索，不作为复杂识别别名。 |
| `avatar` | TEXT | 是 | 资源维护 | 精灵头像资源路径或资源 ID。用于 UI 展示和图像识别。 |
| `element_types_json` | TEXT(JSON) | 是 | 数据库录入 | 精灵系别数组，支持单系或双系。示例：`["fire"]`。 |
| `base_hp_talent` | INTEGER | 是 | 数据库录入 | 生命种族资质，用于面板属性计算。 |
| `base_physical_attack_talent` | INTEGER | 是 | 数据库录入 | 物攻种族资质。 |
| `base_physical_defense_talent` | INTEGER | 是 | 数据库录入 | 物防种族资质。 |
| `base_magic_attack_talent` | INTEGER | 是 | 数据库录入 | 魔攻种族资质。 |
| `base_magic_defense_talent` | INTEGER | 是 | 数据库录入 | 魔防种族资质。 |
| `base_speed_talent` | INTEGER | 是 | 数据库录入 | 速度种族资质，用于候选速度区间和先手判断。 |
| `common_skill_sets_json` | TEXT(JSON) | 否 | 统计 / 手动维护 | 常见技能组，只用于候选初始权重，不用于排除冷门配置。 |
| `common_natures_json` | TEXT(JSON) | 否 | 统计 / 手动维护 | 常见性格权重。 |
| `common_individual_talent_patterns_json` | TEXT(JSON) | 否 | 统计 / 手动维护 | 常见个体资质分布权重。 |
| `forms_json` | TEXT(JSON) | 否 | 数据库录入 | 形态信息。若不同形态种族资质不同，建议拆成不同 `elf_id`。 |
| `recognition_templates_json` | TEXT(JSON) | 否 | 识别模块维护 | 头像区域、名称区域、模板特征等。 |
| `data_source` | TEXT | 否 | 数据库维护 | 数据来源说明。 |
| `data_version` | TEXT | 否 | 数据库维护 | 规则数据版本。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |
| `deleted_at` | TEXT | 否 | 系统生成 | 软删除时间。 |

### 索引

```sql
CREATE INDEX idx_elf_definition_name ON elf_definition(elf_name);
```

### 开发注释

- 不允许新增 `alias_names` 字段。
- 搜索可基于 `elf_name`，识别容错由头像模板和手动确认处理。
- `element_types_json` 由 Pydantic 校验为数组。

---

## 3.2 `elf_learnable_skill` 精灵可学习技能关联表

### 用途

记录精灵可学习技能池。敌方技能未知时，系统根据该表枚举可能技能。

### 建表 SQL

```sql
CREATE TABLE elf_learnable_skill (
  elf_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  source TEXT,
  weight REAL DEFAULT 1.0,
  created_at TEXT NOT NULL,
  PRIMARY KEY (elf_id, skill_id),
  FOREIGN KEY (elf_id) REFERENCES elf_definition(elf_id),
  FOREIGN KEY (skill_id) REFERENCES skill_definition(skill_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `elf_id` | TEXT | 是 | 数据库录入 | 精灵 ID。 |
| `skill_id` | TEXT | 是 | 数据库录入 | 可学习技能 ID。 |
| `source` | TEXT | 否 | 数据库维护 | 数据来源。 |
| `weight` | REAL | 否 | 统计 / 默认 | 技能先验权重。只影响排序，不直接排除。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |

### 索引

```sql
CREATE INDEX idx_elf_learnable_skill_skill ON elf_learnable_skill(skill_id);
```

---

## 3.3 `nature_definition` 性格定义表

### 用途

记录性格对六维属性的正负修正。

### 建表 SQL

```sql
CREATE TABLE nature_definition (
  nature_id TEXT PRIMARY KEY,
  nature_name TEXT NOT NULL,
  positive_stat TEXT NOT NULL,
  positive_multiplier REAL NOT NULL DEFAULT 1.2,
  negative_stat TEXT NOT NULL,
  negative_multiplier REAL NOT NULL DEFAULT 0.9,
  neutral_multiplier REAL NOT NULL DEFAULT 1.0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (positive_stat <> negative_stat)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `nature_id` | TEXT | 是 | 数据库录入 | 性格唯一 ID。 |
| `nature_name` | TEXT | 是 | 数据库录入 | 性格显示名称。 |
| `positive_stat` | TEXT | 是 | 数据库录入 | 正面修正维度。取 `hp`、`physical_attack`、`physical_defense`、`magic_attack`、`magic_defense`、`speed`。 |
| `positive_multiplier` | REAL | 是 | 数据库录入 | 正面倍率，当前固定 1.2。 |
| `negative_stat` | TEXT | 是 | 数据库录入 | 负面修正维度，不得与正面维度相同。 |
| `negative_multiplier` | REAL | 是 | 数据库录入 | 负面倍率，当前固定 0.9。 |
| `neutral_multiplier` | REAL | 是 | 数据库录入 | 其他属性倍率，当前固定 1.0。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE INDEX idx_nature_positive_negative ON nature_definition(positive_stat, negative_stat);
```

---

## 3.4 `skill_definition` 技能定义表

### 用途

记录技能基础信息、伤害规则、连击 / 动画多段规则、效果操作和识别模板。

### 建表 SQL

```sql
CREATE TABLE skill_definition (
  skill_id TEXT PRIMARY KEY,
  skill_name TEXT NOT NULL,
  alias_names_json TEXT,
  skill_icon TEXT,
  element_type TEXT NOT NULL,
  skill_category TEXT NOT NULL,
  base_power INTEGER,
  base_energy_cost INTEGER NOT NULL DEFAULT 0,
  priority_modifier INTEGER NOT NULL DEFAULT 0,
  tags_json TEXT,

  damage_rule_json TEXT,
  hit_rule_json TEXT,
  effect_operations_json TEXT,
  recognition_template_json TEXT,

  data_source TEXT,
  data_version TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `skill_id` | TEXT | 是 | 数据库录入 | 技能唯一 ID。事件日志和技能槽都引用该字段。 |
| `skill_name` | TEXT | 是 | 数据库录入 | 技能标准名称。 |
| `alias_names_json` | TEXT(JSON) | 否 | 手动维护 | 技能别名和 OCR 常见误识别名。注意：技能允许别名，精灵不允许。 |
| `skill_icon` | TEXT | 否 | 资源维护 | 技能图标路径或资源 ID。 |
| `element_type` | TEXT | 是 | 数据库录入 | 技能系别，用于属性克制和天气 / 印记规则。 |
| `skill_category` | TEXT | 是 | 数据库录入 | 技能类型：`physical`、`magic`、`status`、`special`。 |
| `base_power` | INTEGER | 条件 | 数据库录入 | 基础威力。攻击技能通常必填，状态技能可为空。 |
| `base_energy_cost` | INTEGER | 是 | 数据库录入 | 基础能耗。运行时实际能耗会受技能槽和状态修正。 |
| `priority_modifier` | INTEGER | 是 | 数据库录入 | 技能先手修正，普通技能为 0。 |
| `tags_json` | TEXT(JSON) | 否 | 数据库维护 | 检索标签，如 `combo`、`weather_setter`、`mark_related`。 |
| `damage_rule_json` | TEXT(JSON) | 条件 | 数据库录入 | 伤害规则，攻击技能必填。 |
| `hit_rule_json` | TEXT(JSON) | 否 | 数据库录入 | 单次、动画多段、连击规则。 |
| `effect_operations_json` | TEXT(JSON) | 否 | 数据库录入 | 技能附带的状态操作列表。 |
| `recognition_template_json` | TEXT(JSON) | 否 | 识别模块维护 | 技能名称 / 图标识别模板。 |
| `data_source` | TEXT | 否 | 数据库维护 | 数据来源。 |
| `data_version` | TEXT | 否 | 数据库维护 | 技能数据版本。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |
| `deleted_at` | TEXT | 否 | 系统生成 | 软删除时间。 |

### 索引

```sql
CREATE INDEX idx_skill_definition_name ON skill_definition(skill_name);
CREATE INDEX idx_skill_definition_element ON skill_definition(element_type);
CREATE INDEX idx_skill_definition_category ON skill_definition(skill_category);
```

### 开发注释

- `damage_rule_json` 对应开发规格中的 `DamageRule`。
- `hit_rule_json` 对应开发规格中的 `HitRule`，必须区分 `visual_total_damage` 和 `combo_repeated_damage`。
- `effect_operations_json` 对应 `EffectOperation[]`。
- 如果后续需要更强查询能力，可将 `effect_operations_json` 拆为独立表；第一阶段不强制。

---

## 3.5 `effect_definition` 统一状态定义表

### 用途

记录所有会在战斗中以图标、层数、属性修正、伤害修正、能耗修正、行动规则或资源结算规则存在的效果。

普通增益、普通减益、异常、印记、天气、技能槽修正、连击修正、行动规则状态全部进入该表。

### 建表 SQL

```sql
CREATE TABLE effect_definition (
  effect_id TEXT PRIMARY KEY,
  effect_name TEXT NOT NULL,
  icon TEXT,

  category TEXT NOT NULL,
  polarity TEXT NOT NULL,
  display_group TEXT NOT NULL,
  display_priority INTEGER DEFAULT 0,

  owner_scope TEXT NOT NULL,
  target_scope TEXT NOT NULL,
  attach_target_type TEXT NOT NULL,

  is_visible_icon INTEGER NOT NULL DEFAULT 1,
  is_recognizable_by_icon INTEGER NOT NULL DEFAULT 0,
  recognition_alias_json TEXT,

  default_layers INTEGER DEFAULT 1,
  max_layers INTEGER,
  stack_rule TEXT NOT NULL,
  refresh_rule TEXT,

  duration_type TEXT NOT NULL,
  default_duration_turns INTEGER,
  default_duration_uses INTEGER,

  clear_on_switch INTEGER NOT NULL DEFAULT 0,
  clear_by_abnormal_cleanse INTEGER NOT NULL DEFAULT 0,
  clear_by_stat_clear INTEGER NOT NULL DEFAULT 0,
  clear_by_mark_clear INTEGER NOT NULL DEFAULT 0,
  clear_by_weather_replace INTEGER NOT NULL DEFAULT 0,
  clear_by_skill_specific INTEGER NOT NULL DEFAULT 0,

  can_be_transferred INTEGER NOT NULL DEFAULT 0,
  can_be_converted INTEGER NOT NULL DEFAULT 0,
  can_be_inherited INTEGER NOT NULL DEFAULT 0,
  can_be_stolen INTEGER NOT NULL DEFAULT 0,
  can_be_doubled INTEGER NOT NULL DEFAULT 0,

  conflict_group TEXT,
  conflict_policy TEXT,

  formula_hooks_json TEXT,
  stat_modifier_json TEXT,
  damage_modifier_json TEXT,
  skill_modifier_json TEXT,
  action_modifier_json TEXT,
  resource_modifier_json TEXT,

  special_rule_id TEXT,
  developer_notes TEXT,
  data_version TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `effect_id` | TEXT | 是 | 数据库录入 | 状态唯一 ID。状态实例、快照、事件都引用该字段。 |
| `effect_name` | TEXT | 是 | 数据库录入 | 状态名称，如冰冻、灼烧、星陨、雨天、物攻提升。 |
| `icon` | TEXT | 条件 | 资源维护 | 图标资源。可见且可识别状态建议必填。 |
| `category` | TEXT | 是 | 数据库录入 | 分类标签，如 `abnormal`、`mark`、`weather`。分类只用于展示和检索，不直接决定规则。 |
| `polarity` | TEXT | 是 | 数据库录入 | 正面、负面、中性或混合：`positive`、`negative`、`neutral`、`mixed`。 |
| `display_group` | TEXT | 是 | 数据库录入 | UI 显示分区，如精灵状态栏、队伍侧、战场顶部、技能槽角标。 |
| `display_priority` | INTEGER | 否 | 数据库录入 | 展示排序，数值越小越靠前。 |
| `owner_scope` | TEXT | 是 | 数据库录入 | 归属范围：`elf`、`side`、`field`、`skill_slot`、`turn`。 |
| `target_scope` | TEXT | 是 | 数据库录入 | 技能作用目标范围，用于生成实例。 |
| `attach_target_type` | TEXT | 是 | 数据库录入 | 实例挂载目标类型，通常与 `owner_scope` 对应。 |
| `is_visible_icon` | INTEGER | 是 | 数据库录入 | 是否在 UI 中显示图标。瞬时资源变化通常为 0。 |
| `is_recognizable_by_icon` | INTEGER | 是 | 识别模块维护 | 是否可通过图标识别。 |
| `recognition_alias_json` | TEXT(JSON) | 否 | 识别模块维护 | 状态识别容错名。不是精灵别名。 |
| `default_layers` | INTEGER | 否 | 数据库录入 | 默认层数。无层数状态一般为 1。 |
| `max_layers` | INTEGER | 否 | 数据库录入 / 待实测 | 最大层数。未知可为空。 |
| `stack_rule` | TEXT | 是 | 数据库录入 | 叠层规则，如 `add`、`refresh`、`replace`、`max`、`ignore`。 |
| `refresh_rule` | TEXT | 否 | 数据库录入 | 再次获得时是否刷新持续时间。 |
| `duration_type` | TEXT | 是 | 数据库录入 | 持续类型，如 `turns`、`uses`、`until_switch`、`until_clear`、`battle_end`、`instant`。 |
| `default_duration_turns` | INTEGER | 否 | 数据库录入 | 默认持续回合数。 |
| `default_duration_uses` | INTEGER | 否 | 数据库录入 | 默认持续次数。 |
| `clear_on_switch` | INTEGER | 是 | 数据库录入 | 切换当前在场精灵时是否清除。中毒、灼烧为 1；冰冻、萌化、印记、天气为 0。 |
| `clear_by_abnormal_cleanse` | INTEGER | 是 | 数据库录入 | 是否可被清除异常技能移除。 |
| `clear_by_stat_clear` | INTEGER | 是 | 数据库录入 | 是否可被清除普通属性变化技能移除。 |
| `clear_by_mark_clear` | INTEGER | 是 | 数据库录入 | 是否可被清除印记技能移除。 |
| `clear_by_weather_replace` | INTEGER | 是 | 数据库录入 | 是否可被新天气替换。天气通常为 1。 |
| `clear_by_skill_specific` | INTEGER | 是 | 数据库录入 | 是否只能由特定技能或特殊规则处理。 |
| `can_be_transferred` | INTEGER | 是 | 数据库录入 | 是否可转移。 |
| `can_be_converted` | INTEGER | 是 | 数据库录入 | 是否可转换。 |
| `can_be_inherited` | INTEGER | 是 | 数据库录入 | 是否可继承。 |
| `can_be_stolen` | INTEGER | 是 | 数据库录入 | 是否可夺取。 |
| `can_be_doubled` | INTEGER | 是 | 数据库录入 | 是否可翻倍层数。星陨如支持翻倍则为 1。 |
| `conflict_group` | TEXT | 否 | 数据库录入 | 互斥组。例如天气可用同一冲突组。 |
| `conflict_policy` | TEXT | 否 | 数据库录入 | 同组冲突处理，如 `replace_old`、`reject_new`、`coexist`。 |
| `formula_hooks_json` | TEXT(JSON) | 否 | 数据库录入 | 参与公式环节，如 `damage_before_defense`、`speed_compare`、`combo_count`。 |
| `stat_modifier_json` | TEXT(JSON) | 否 | 数据库录入 | 属性修正规则。 |
| `damage_modifier_json` | TEXT(JSON) | 否 | 数据库录入 | 增伤 / 减伤规则。 |
| `skill_modifier_json` | TEXT(JSON) | 否 | 数据库录入 | 技能能耗、威力、冷却、位置等规则。 |
| `action_modifier_json` | TEXT(JSON) | 否 | 数据库录入 | 先手、蓄力、无法行动等规则。 |
| `resource_modifier_json` | TEXT(JSON) | 否 | 数据库录入 | 生命、能量持续结算规则。 |
| `special_rule_id` | TEXT | 否 | 数据库录入 / 代码实现 | 特殊规则处理器 ID。奉献第一阶段只记录，不实现公式。 |
| `developer_notes` | TEXT | 否 | 开发维护 | 备注、待实测项、原始技能描述。 |
| `data_version` | TEXT | 否 | 数据库维护 | 状态规则版本。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |
| `deleted_at` | TEXT | 否 | 系统生成 | 软删除时间。 |

### 索引

```sql
CREATE INDEX idx_effect_definition_category ON effect_definition(category);
CREATE INDEX idx_effect_definition_owner_scope ON effect_definition(owner_scope);
CREATE INDEX idx_effect_definition_display_group ON effect_definition(display_group);
CREATE INDEX idx_effect_definition_conflict_group ON effect_definition(conflict_group);
```

### 开发注释

- 不单独建立 `mark_definition`、`weather_definition`、`abnormal_definition` 主表。
- 可建立视图：`mark_effect_view`、`weather_effect_view`。
- 星陨必须配置为 `category = mark`，且 `clear_on_switch = 0`。
- 中毒、灼烧配置 `clear_on_switch = 1`。
- 冰冻、萌化配置 `clear_on_switch = 0`。

---

## 3.6 `type_effectiveness_rule` 属性克制规则表

### 用途

记录技能系别对目标系别的克制倍率。

### 建表 SQL

```sql
CREATE TABLE type_effectiveness_rule (
  attack_element_type TEXT NOT NULL,
  defense_element_type TEXT NOT NULL,
  multiplier REAL NOT NULL,
  notes TEXT,
  data_version TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (attack_element_type, defense_element_type)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `attack_element_type` | TEXT | 是 | 数据库录入 | 攻击技能系别。 |
| `defense_element_type` | TEXT | 是 | 数据库录入 | 防御精灵系别。 |
| `multiplier` | REAL | 是 | 数据库录入 | 克制倍率。 |
| `notes` | TEXT | 否 | 数据库维护 | 备注。 |
| `data_version` | TEXT | 否 | 数据库维护 | 规则版本。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

---

## 4. 用户配置表

## 4.1 `player_elf_build` 己方精灵配置表

### 用途

记录玩家提前录入的己方完整配置。准备阶段从该表复制数据到本场战斗的 `battle_elf_state`。

### 建表 SQL

```sql
CREATE TABLE player_elf_build (
  build_id TEXT PRIMARY KEY,
  elf_id TEXT NOT NULL,
  build_name TEXT,
  nature_id TEXT NOT NULL,

  individual_hp INTEGER NOT NULL DEFAULT 0,
  individual_physical_attack INTEGER NOT NULL DEFAULT 0,
  individual_physical_defense INTEGER NOT NULL DEFAULT 0,
  individual_magic_attack INTEGER NOT NULL DEFAULT 0,
  individual_magic_defense INTEGER NOT NULL DEFAULT 0,
  individual_speed INTEGER NOT NULL DEFAULT 0,

  final_hp INTEGER NOT NULL,
  final_physical_attack INTEGER NOT NULL,
  final_physical_defense INTEGER NOT NULL,
  final_magic_attack INTEGER NOT NULL,
  final_magic_defense INTEGER NOT NULL,
  final_speed INTEGER NOT NULL,

  is_favorite INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,

  FOREIGN KEY (elf_id) REFERENCES elf_definition(elf_id),
  FOREIGN KEY (nature_id) REFERENCES nature_definition(nature_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `build_id` | TEXT | 是 | 系统生成 | 己方配置唯一 ID。 |
| `elf_id` | TEXT | 是 | 用户选择 | 精灵 ID。 |
| `build_name` | TEXT | 否 | 用户输入 | 配置名称，如“高速物攻版”。 |
| `nature_id` | TEXT | 是 | 用户选择 | 性格 ID。 |
| `individual_hp` | INTEGER | 是 | 用户输入 | 生命个体资质。不存在则 0。 |
| `individual_physical_attack` | INTEGER | 是 | 用户输入 | 物攻个体资质。 |
| `individual_physical_defense` | INTEGER | 是 | 用户输入 | 物防个体资质。 |
| `individual_magic_attack` | INTEGER | 是 | 用户输入 | 魔攻个体资质。 |
| `individual_magic_defense` | INTEGER | 是 | 用户输入 | 魔防个体资质。 |
| `individual_speed` | INTEGER | 是 | 用户输入 | 速度个体资质。 |
| `final_hp` | INTEGER | 是 | 系统计算 | 面板生命缓存。 |
| `final_physical_attack` | INTEGER | 是 | 系统计算 | 面板物攻缓存。 |
| `final_physical_defense` | INTEGER | 是 | 系统计算 | 面板物防缓存。 |
| `final_magic_attack` | INTEGER | 是 | 系统计算 | 面板魔攻缓存。 |
| `final_magic_defense` | INTEGER | 是 | 系统计算 | 面板魔防缓存。 |
| `final_speed` | INTEGER | 是 | 系统计算 | 面板速度缓存。 |
| `is_favorite` | INTEGER | 是 | 用户操作 | 是否常用配置。 |
| `notes` | TEXT | 否 | 用户输入 | 备注。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |
| `deleted_at` | TEXT | 否 | 系统生成 | 软删除时间。 |

说明：`individual_*` 字段保存玩家界面输入的显示个体资质，不直接保存 PVP 公式有效值。计算 `final_*` 面板缓存时，代码内部先转换为 `有效个体资质 = 显示个体资质 × 6`。

### 索引

```sql
CREATE INDEX idx_player_elf_build_elf ON player_elf_build(elf_id);
```

---

## 4.2 `player_elf_build_skill` 己方配置技能表

### 用途

记录己方某个配置携带的技能组。单独拆表便于排序和替换。

### 建表 SQL

```sql
CREATE TABLE player_elf_build_skill (
  build_id TEXT NOT NULL,
  slot_index INTEGER NOT NULL,
  skill_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (build_id, slot_index),
  FOREIGN KEY (build_id) REFERENCES player_elf_build(build_id),
  FOREIGN KEY (skill_id) REFERENCES skill_definition(skill_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `build_id` | TEXT | 是 | 系统生成 | 己方配置 ID。 |
| `slot_index` | INTEGER | 是 | 用户输入 | 技能槽位，建议从 1 开始。 |
| `skill_id` | TEXT | 是 | 用户选择 | 技能 ID。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |

---

## 4.3 `team_preset` 配队预设表

### 用途

保存准备阶段可复用的 6 只精灵阵容模板。己方配队通常由已计算面板的
`player_elf_build` 组成；敌方热门阵容可以只保存精灵种类，用于快速录入
敌方阵容并触发候选生成。

### 建表 SQL

```sql
CREATE TABLE team_preset (
  preset_id TEXT PRIMARY KEY,
  preset_name TEXT NOT NULL,
  side_usage TEXT NOT NULL DEFAULT 'self',
  source_type TEXT NOT NULL DEFAULT 'custom',
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `preset_id` | TEXT | 是 | 系统生成 | 配队预设 ID。 |
| `preset_name` | TEXT | 是 | 用户输入 | 配队名称。 |
| `side_usage` | TEXT | 是 | 用户选择 | 使用侧：`self`、`enemy` 或 `both`。 |
| `source_type` | TEXT | 是 | 用户选择 | 来源：`custom` 或 `popular`。 |
| `notes` | TEXT | 否 | 用户输入 | 备注。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |
| `deleted_at` | TEXT | 否 | 系统生成 | 软删除时间。 |

### 索引

```sql
CREATE INDEX idx_team_preset_name ON team_preset(preset_name);
CREATE INDEX idx_team_preset_usage_source ON team_preset(side_usage, source_type);
```

---

## 4.4 `team_preset_slot` 配队预设槽位表

### 用途

保存配队中的 0-5 号槽位。己方配队槽位必须引用 `build_id`；敌方热门阵容
允许 `build_id` 为空，只保存 `elf_id`。

### 建表 SQL

```sql
CREATE TABLE team_preset_slot (
  slot_id TEXT PRIMARY KEY,
  preset_id TEXT NOT NULL,
  slot_index INTEGER NOT NULL,
  elf_id TEXT NOT NULL,
  build_id TEXT,
  notes TEXT,

  UNIQUE (preset_id, slot_index),
  FOREIGN KEY (preset_id) REFERENCES team_preset(preset_id),
  FOREIGN KEY (elf_id) REFERENCES elf_definition(elf_id),
  FOREIGN KEY (build_id) REFERENCES player_elf_build(build_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `slot_id` | TEXT | 是 | 系统生成 | 配队槽位 ID。 |
| `preset_id` | TEXT | 是 | 系统生成 | 所属配队预设。 |
| `slot_index` | INTEGER | 是 | 用户输入 | 槽位序号，0-5。 |
| `elf_id` | TEXT | 是 | 用户选择 | 精灵 ID。 |
| `build_id` | TEXT | 否 | 用户选择 | 己方配置 ID；敌方热门阵容可为空。 |
| `notes` | TEXT | 否 | 用户输入 | 槽位备注。 |

### 索引

```sql
CREATE INDEX idx_team_preset_slot_preset ON team_preset_slot(preset_id);
CREATE INDEX idx_team_preset_slot_elf ON team_preset_slot(elf_id);
```

### 一致性规则

- 同一配队的 `slot_index` 不能重复。
- `side_usage = self` 的配队槽位必须有 `build_id`。
- 如果槽位保存了 `build_id`，该配置的 `elf_id` 必须与槽位 `elf_id` 一致。
- 配队预设只用于准备阶段快速填充，不直接进入战斗事件日志。

---

## 5. 战斗运行时表

## 5.1 `battle` 战斗主表

### 用途

记录一场战斗的生命周期、当前阶段、当前回合和双方当前在场精灵。

### 建表 SQL

```sql
CREATE TABLE battle (
  battle_id TEXT PRIMARY KEY,
  battle_name TEXT,
  phase TEXT NOT NULL DEFAULT 'preparation',
  turn_number INTEGER NOT NULL DEFAULT 0,

  self_active_elf_id TEXT,
  enemy_active_elf_id TEXT,

  started_at TEXT,
  finished_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,

  notes TEXT
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `battle_id` | TEXT | 是 | 系统生成 | 战斗唯一 ID。 |
| `battle_name` | TEXT | 否 | 用户输入 | 战斗名称，便于历史查找。 |
| `phase` | TEXT | 是 | 系统维护 | 阶段：`preparation`、`battle`、`finished`、`archived`。 |
| `turn_number` | INTEGER | 是 | 系统维护 | 当前回合编号。 |
| `self_active_elf_id` | TEXT | 否 | 用户输入 / 事件 | 我方当前在场精灵 ID。准备阶段可为空。 |
| `enemy_active_elf_id` | TEXT | 否 | 用户输入 / 事件 | 敌方当前在场精灵 ID。准备阶段可为空。 |
| `started_at` | TEXT | 否 | 系统生成 | 进入战斗阶段时间。 |
| `finished_at` | TEXT | 否 | 系统生成 | 结束时间。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |
| `deleted_at` | TEXT | 否 | 系统生成 | 软删除时间。 |
| `notes` | TEXT | 否 | 用户输入 | 备注。 |

### 索引

```sql
CREATE INDEX idx_battle_phase ON battle(phase);
CREATE INDEX idx_battle_created_at ON battle(created_at);
```

---

## 5.2 `battle_elf_state` 战斗精灵运行时状态表

### 用途

记录本场战斗中双方每只精灵的运行时状态。所有状态效果不拆分字段，而是通过 `battle_effect_instance` 关联。

### 建表 SQL

```sql
CREATE TABLE battle_elf_state (
  battle_elf_state_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  side TEXT NOT NULL,
  team_slot INTEGER NOT NULL,
  elf_id TEXT NOT NULL,
  elf_name TEXT NOT NULL,
  avatar TEXT NOT NULL,

  nature_id TEXT,

  individual_hp INTEGER,
  individual_physical_attack INTEGER,
  individual_physical_defense INTEGER,
  individual_magic_attack INTEGER,
  individual_magic_defense INTEGER,
  individual_speed INTEGER,

  final_hp INTEGER,
  final_physical_attack INTEGER,
  final_physical_defense INTEGER,
  final_magic_attack INTEGER,
  final_magic_defense INTEGER,
  final_speed INTEGER,

  current_hp_value INTEGER,
  current_hp_percent REAL NOT NULL DEFAULT 100.0,
  energy INTEGER NOT NULL DEFAULT 0,

  skill_ids_json TEXT,
  confirmed_skill_ids_json TEXT,
  active_effect_instance_ids_json TEXT,

  is_active_elf INTEGER NOT NULL DEFAULT 0,
  is_defeated INTEGER NOT NULL DEFAULT 0,
  last_switch_turn INTEGER,
  manual_override INTEGER NOT NULL DEFAULT 0,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (elf_id) REFERENCES elf_definition(elf_id),
  FOREIGN KEY (nature_id) REFERENCES nature_definition(nature_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `battle_elf_state_id` | TEXT | 是 | 系统生成 | 战斗内精灵状态记录 ID。 |
| `battle_id` | TEXT | 是 | 系统生成 | 所属战斗。 |
| `side` | TEXT | 是 | 用户输入 | `self` 或 `enemy`。 |
| `team_slot` | INTEGER | 是 | 用户输入 | 队伍位置，1 到 6。 |
| `elf_id` | TEXT | 是 | 用户选择 / 识别 | 精灵 ID。 |
| `elf_name` | TEXT | 是 | 系统复制 | 精灵名称快照，防止后续规则库改名影响历史显示。 |
| `avatar` | TEXT | 是 | 系统复制 | 头像快照。 |
| `nature_id` | TEXT | 条件 | 用户输入 / 候选 | 己方必填；敌方未知时可为空。 |
| `individual_hp` | INTEGER | 条件 | 用户输入 / 候选 | 己方必填；敌方运行时未知可为空。 |
| `individual_physical_attack` | INTEGER | 条件 | 用户输入 / 候选 | 物攻个体资质。 |
| `individual_physical_defense` | INTEGER | 条件 | 用户输入 / 候选 | 物防个体资质。 |
| `individual_magic_attack` | INTEGER | 条件 | 用户输入 / 候选 | 魔攻个体资质。 |
| `individual_magic_defense` | INTEGER | 条件 | 用户输入 / 候选 | 魔防个体资质。 |
| `individual_speed` | INTEGER | 条件 | 用户输入 / 候选 | 速度个体资质。 |
| `final_hp` | INTEGER | 条件 | 系统计算 | 己方确定；敌方未确认时可为空或保存当前确认值。 |
| `final_physical_attack` | INTEGER | 条件 | 系统计算 | 面板物攻。 |
| `final_physical_defense` | INTEGER | 条件 | 系统计算 | 面板物防。 |
| `final_magic_attack` | INTEGER | 条件 | 系统计算 | 面板魔攻。 |
| `final_magic_defense` | INTEGER | 条件 | 系统计算 | 面板魔防。 |
| `final_speed` | INTEGER | 条件 | 系统计算 | 面板速度。 |
| `current_hp_value` | INTEGER | 否 | 手动输入 / 计算 | 当前生命值。敌方可能无法直接确认，可为空。 |
| `current_hp_percent` | REAL | 是 | 手动输入 / 识别 | 当前生命百分比。 |
| `energy` | INTEGER | 是 | 手动输入 / 识别 | 当前能量。 |
| `skill_ids_json` | TEXT(JSON) | 否 | 用户输入 / 候选 | 携带技能列表。敌方未知时可为空。 |
| `confirmed_skill_ids_json` | TEXT(JSON) | 否 | 战斗事件推导 | 已确认敌方技能。 |
| `active_effect_instance_ids_json` | TEXT(JSON) | 否 | 系统维护 | 当前关联状态实例 ID，仅作查询缓存。权威数据在 `battle_effect_instance`。 |
| `is_active_elf` | INTEGER | 是 | 系统维护 | 是否当前在场。 |
| `is_defeated` | INTEGER | 是 | 系统维护 | 是否已倒下。 |
| `last_switch_turn` | INTEGER | 否 | 系统维护 | 最近一次上场 / 离场回合。 |
| `manual_override` | INTEGER | 是 | 用户操作 | 是否由手动修正覆盖。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE UNIQUE INDEX idx_battle_elf_state_unique_slot ON battle_elf_state(battle_id, side, team_slot);
CREATE INDEX idx_battle_elf_state_battle_side_elf ON battle_elf_state(battle_id, side, elf_id);
CREATE INDEX idx_battle_elf_state_active ON battle_elf_state(battle_id, side, is_active_elf);
```

---

## 5.3 `battle_skill_slot` 战斗技能槽表

### 用途

记录战斗中某只精灵的技能槽状态。技能槽修正效果可以挂载到该表记录。

### 建表 SQL

```sql
CREATE TABLE battle_skill_slot (
  skill_slot_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  battle_elf_state_id TEXT NOT NULL,
  side TEXT NOT NULL,
  elf_id TEXT NOT NULL,
  slot_index INTEGER NOT NULL,
  skill_id TEXT,
  base_energy_cost INTEGER,
  current_energy_cost INTEGER,
  current_power INTEGER,
  cooldown_turns INTEGER DEFAULT 0,
  is_confirmed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (battle_elf_state_id) REFERENCES battle_elf_state(battle_elf_state_id),
  FOREIGN KEY (skill_id) REFERENCES skill_definition(skill_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `skill_slot_id` | TEXT | 是 | 系统生成 | 技能槽实例 ID。状态实例 `owner_scope=skill_slot` 时引用该字段。 |
| `battle_id` | TEXT | 是 | 系统生成 | 所属战斗。 |
| `battle_elf_state_id` | TEXT | 是 | 系统生成 | 所属精灵运行时状态。 |
| `side` | TEXT | 是 | 系统复制 | 队伍侧。 |
| `elf_id` | TEXT | 是 | 系统复制 | 精灵 ID。 |
| `slot_index` | INTEGER | 是 | 用户输入 / 系统维护 | 技能槽位置。 |
| `skill_id` | TEXT | 否 | 用户输入 / 识别 | 技能 ID。敌方未知技能槽可为空。 |
| `base_energy_cost` | INTEGER | 否 | 规则数据 | 基础能耗快照。 |
| `current_energy_cost` | INTEGER | 否 | 系统计算 | 当前能耗，受技能槽修正影响。 |
| `current_power` | INTEGER | 否 | 系统计算 | 当前威力，受技能威力修正影响。 |
| `cooldown_turns` | INTEGER | 是 | 系统维护 | 剩余冷却回合。 |
| `is_confirmed` | INTEGER | 是 | 用户 / 识别 | 敌方技能是否已确认。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE UNIQUE INDEX idx_battle_skill_slot_unique ON battle_skill_slot(battle_id, battle_elf_state_id, slot_index);
CREATE INDEX idx_battle_skill_slot_skill ON battle_skill_slot(battle_id, skill_id);
```

---

## 5.4 旧候选配置表删除说明

历史 `build_candidate` 表已通过 Alembic `0006_drop_legacy_candidate_tables` 删除；旧 ORM、service、schema、接口和测试也已移除。当前敌方配置推算状态只由 `enemy_panel_estimate` 和 `enemy_panel_estimate_evidence` 承担。新功能不得重新依赖候选空间落库筛选。

---

## 5.5 `battle_effect_instance` 状态实例表

### 用途

记录战斗中实际存在的状态实例。普通属性修正、异常、印记、天气、技能槽修正、行动规则状态全部使用此表。

### 建表 SQL

```sql
CREATE TABLE battle_effect_instance (
  instance_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  effect_id TEXT NOT NULL,

  owner_scope TEXT NOT NULL,
  owner_side TEXT,
  owner_elf_id TEXT,
  owner_skill_slot_id TEXT,
  field_id TEXT,

  source_side TEXT,
  source_elf_id TEXT,
  source_skill_id TEXT,
  source_event_id TEXT,

  layers INTEGER NOT NULL DEFAULT 1,
  remaining_turns INTEGER,
  remaining_uses INTEGER,
  is_active INTEGER NOT NULL DEFAULT 1,

  applied_turn INTEGER,
  expire_turn INTEGER,
  last_updated_turn INTEGER,

  recognition_source TEXT,
  recognition_confidence REAL,
  manual_override INTEGER NOT NULL DEFAULT 0,

  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (effect_id) REFERENCES effect_definition(effect_id),
  FOREIGN KEY (owner_skill_slot_id) REFERENCES battle_skill_slot(skill_slot_id),
  FOREIGN KEY (source_skill_id) REFERENCES skill_definition(skill_id),
  FOREIGN KEY (source_event_id) REFERENCES battle_event(event_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `instance_id` | TEXT | 是 | 系统生成 | 状态实例唯一 ID。 |
| `battle_id` | TEXT | 是 | 系统生成 | 所属战斗。 |
| `effect_id` | TEXT | 是 | 规则数据 | 状态定义 ID。 |
| `owner_scope` | TEXT | 是 | 规则数据 / 事件 | 归属范围。决定挂载到精灵、队伍、战场、技能槽还是回合。 |
| `owner_side` | TEXT | 条件 | 事件目标 | 归属队伍。`owner_scope=side` 时必填；`elf` 状态也建议填。 |
| `owner_elf_id` | TEXT | 条件 | 事件目标 | 归属精灵。`owner_scope=elf` 时必填。 |
| `owner_skill_slot_id` | TEXT | 条件 | 事件目标 | 归属技能槽。`owner_scope=skill_slot` 时必填。 |
| `field_id` | TEXT | 条件 | 系统默认 | 战场 ID。`owner_scope=field` 时可填 `main_field`。 |
| `source_side` | TEXT | 否 | 事件来源 | 来源队伍。 |
| `source_elf_id` | TEXT | 否 | 事件来源 | 来源精灵。 |
| `source_skill_id` | TEXT | 否 | 事件来源 | 来源技能。 |
| `source_event_id` | TEXT | 否 | 事件来源 | 来源事件 ID。 |
| `layers` | INTEGER | 是 | 规则 / 事件 | 当前层数。无层数状态为 1。 |
| `remaining_turns` | INTEGER | 否 | 规则 / 系统维护 | 剩余回合。 |
| `remaining_uses` | INTEGER | 否 | 规则 / 系统维护 | 剩余次数。 |
| `is_active` | INTEGER | 是 | 系统维护 | 是否仍然有效。历史失效实例保留。 |
| `applied_turn` | INTEGER | 否 | 系统生成 | 获得状态的回合。 |
| `expire_turn` | INTEGER | 否 | 系统计算 | 预计过期回合。 |
| `last_updated_turn` | INTEGER | 否 | 系统维护 | 最近更新回合。 |
| `recognition_source` | TEXT | 否 | 输入层 | 来源：手动、识别、系统推算。 |
| `recognition_confidence` | REAL | 否 | 输入层 | 识别置信度。手动输入可为 1。 |
| `manual_override` | INTEGER | 是 | 用户操作 | 是否被手动修正。 |
| `notes` | TEXT | 否 | 用户 / 系统 | 备注。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE INDEX idx_effect_instance_battle_active ON battle_effect_instance(battle_id, is_active);
CREATE INDEX idx_effect_instance_owner_elf ON battle_effect_instance(battle_id, owner_side, owner_elf_id, is_active);
CREATE INDEX idx_effect_instance_owner_side ON battle_effect_instance(battle_id, owner_side, owner_scope, is_active);
CREATE INDEX idx_effect_instance_effect ON battle_effect_instance(battle_id, effect_id, is_active);
CREATE INDEX idx_effect_instance_skill_slot ON battle_effect_instance(owner_skill_slot_id, is_active);
```

### 开发注释

- 查询印记：关联 `effect_definition.category = 'mark'`。
- 查询天气：关联 `effect_definition.category = 'weather'`。
- 不要再维护单独印记槽表。
- 不要根据 `category` 直接决定清除规则，必须读取 `effect_definition.clear_on_switch` 等字段。

---

## 5.6 `battle_effect_snapshot` 状态快照表

### 用途

保存事件发生瞬间的状态快照。伤害、治疗、能量变化、切换等事件都应引用快照。

### 建表 SQL

```sql
CREATE TABLE battle_effect_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  turn_number INTEGER NOT NULL,
  action_order INTEGER,
  timestamp TEXT NOT NULL,

  self_active_elf_id TEXT,
  enemy_active_elf_id TEXT,

  active_effect_instance_ids_json TEXT NOT NULL,
  effect_instances_json TEXT NOT NULL,

  self_elf_effect_ids_json TEXT,
  enemy_elf_effect_ids_json TEXT,
  self_side_effect_ids_json TEXT,
  enemy_side_effect_ids_json TEXT,
  field_effect_ids_json TEXT,
  skill_slot_effect_ids_json TEXT,
  turn_effect_ids_json TEXT,

  source_event_id TEXT,
  snapshot_hash TEXT,
  created_at TEXT NOT NULL,

  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (source_event_id) REFERENCES battle_event(event_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `snapshot_id` | TEXT | 是 | 系统生成 | 快照唯一 ID。 |
| `battle_id` | TEXT | 是 | 系统生成 | 所属战斗。 |
| `turn_number` | INTEGER | 是 | 系统记录 | 快照所属回合。 |
| `action_order` | INTEGER | 否 | 系统记录 | 同回合内动作顺序。 |
| `timestamp` | TEXT | 是 | 系统生成 | 快照时间。 |
| `self_active_elf_id` | TEXT | 否 | 系统复制 | 当时我方在场精灵。 |
| `enemy_active_elf_id` | TEXT | 否 | 系统复制 | 当时敌方在场精灵。 |
| `active_effect_instance_ids_json` | TEXT(JSON) | 是 | 系统生成 | 当时所有有效状态实例 ID。用于快速查询。 |
| `effect_instances_json` | TEXT(JSON) | 是 | 系统生成 | 当时所有有效状态实例的完整副本。计算时优先使用该字段，避免实例后续变化污染历史计算。 |
| `self_elf_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 我方当前精灵状态 ID 分组，仅用于展示和快速查询。 |
| `enemy_elf_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 敌方当前精灵状态 ID 分组。 |
| `self_side_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 我方队伍侧状态 / 印记。 |
| `enemy_side_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 敌方队伍侧状态 / 印记。 |
| `field_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 天气和全战场状态。 |
| `skill_slot_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 技能槽状态。 |
| `turn_effect_ids_json` | TEXT(JSON) | 否 | 系统生成 | 本回合临时状态。 |
| `source_event_id` | TEXT | 否 | 系统生成 | 触发快照生成的事件 ID。 |
| `snapshot_hash` | TEXT | 否 | 系统生成 | 快照内容哈希，用于计算缓存。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |

### 索引

```sql
CREATE INDEX idx_snapshot_battle_turn ON battle_effect_snapshot(battle_id, turn_number, timestamp);
CREATE INDEX idx_snapshot_hash ON battle_effect_snapshot(snapshot_hash);
```

### 开发注释

- 快照必须不可变。
- 不允许只保存实例 ID 而不保存完整 JSON 副本。
- 实时反推必须使用伤害事件关联的快照，而不是当前状态。

---

## 6. 事件日志表

## 6.1 `battle_event` 通用战斗事件表

### 用途

记录所有战斗事实的通用事件头。具体伤害、状态变化、资源变化分别写入子表。

### 建表 SQL

```sql
CREATE TABLE battle_event (
  event_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  turn_number INTEGER NOT NULL,
  action_order INTEGER,
  timestamp TEXT NOT NULL,
  event_type TEXT NOT NULL,

  actor_side TEXT,
  actor_elf_id TEXT,
  target_side TEXT,
  target_elf_id TEXT,

  skill_id TEXT,
  skill_confirmed INTEGER NOT NULL DEFAULT 0,

  snapshot_id TEXT,

  source TEXT NOT NULL,
  recognition_confidence REAL,
  manual_override INTEGER NOT NULL DEFAULT 0,
  corrected_event_id TEXT,
  is_voided INTEGER NOT NULL DEFAULT 0,
  notes TEXT,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (skill_id) REFERENCES skill_definition(skill_id),
  FOREIGN KEY (snapshot_id) REFERENCES battle_effect_snapshot(snapshot_id),
  FOREIGN KEY (corrected_event_id) REFERENCES battle_event(event_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `event_id` | TEXT | 是 | 系统生成 | 事件唯一 ID。 |
| `battle_id` | TEXT | 是 | 系统生成 | 所属战斗。 |
| `turn_number` | INTEGER | 是 | 系统维护 | 事件发生回合。 |
| `action_order` | INTEGER | 否 | 系统维护 | 同回合事件顺序。 |
| `timestamp` | TEXT | 是 | 系统生成 | 事件时间。 |
| `event_type` | TEXT | 是 | 输入层 / 系统 | 事件类型，如 `damage`、`combo_damage`、`effect_apply`、`switch_elf`。 |
| `actor_side` | TEXT | 否 | 用户输入 / 识别 | 行动方队伍。 |
| `actor_elf_id` | TEXT | 否 | 用户输入 / 识别 | 行动方精灵。 |
| `target_side` | TEXT | 否 | 用户输入 / 识别 | 目标队伍。 |
| `target_elf_id` | TEXT | 否 | 用户输入 / 识别 | 目标精灵。 |
| `skill_id` | TEXT | 否 | 用户输入 / 识别 | 关联技能。 |
| `skill_confirmed` | INTEGER | 是 | 用户 / 识别 | 技能是否确认。敌方技能未知时为 0。 |
| `snapshot_id` | TEXT | 否 | 系统生成 | 事件关联状态快照。伤害、治疗、能量变化、切换应尽量必填。 |
| `source` | TEXT | 是 | 输入层 | 来源：手动、识别、系统推算等。 |
| `recognition_confidence` | REAL | 否 | 识别模块 | 识别置信度。 |
| `manual_override` | INTEGER | 是 | 用户操作 | 是否被手动覆盖。 |
| `corrected_event_id` | TEXT | 否 | 纠错流程 | 当前事件修正了哪条历史事件。 |
| `is_voided` | INTEGER | 是 | 纠错流程 | 原事件是否作废。保留历史但不参与重放。 |
| `notes` | TEXT | 否 | 用户 / 系统 | 备注。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE INDEX idx_battle_event_battle_turn ON battle_event(battle_id, turn_number, action_order);
CREATE INDEX idx_battle_event_type ON battle_event(battle_id, event_type);
CREATE INDEX idx_battle_event_actor_target ON battle_event(battle_id, actor_elf_id, target_elf_id);
CREATE INDEX idx_battle_event_snapshot ON battle_event(snapshot_id);
```

---

## 6.2 `damage_event` 伤害事件详情表

### 用途

记录伤害事件详情，区分单次伤害、动画多段最终总伤害、连击伤害和特殊伤害。

### 建表 SQL

```sql
CREATE TABLE damage_event (
  damage_event_id TEXT PRIMARY KEY,
  battle_event_id TEXT NOT NULL UNIQUE,
  battle_id TEXT NOT NULL,

  attacker_side TEXT NOT NULL,
  attacker_elf_id TEXT NOT NULL,
  defender_side TEXT NOT NULL,
  defender_elf_id TEXT NOT NULL,
  skill_id TEXT,

  damage_display_type TEXT NOT NULL,

  damage_value INTEGER,
  final_total_damage_value INTEGER,

  per_hit_damage_value INTEGER,
  hit_count INTEGER,
  computed_total_damage_value INTEGER,
  combo_count_source TEXT,
  combo_confidence REAL,

  hp_percent_before REAL,
  hp_percent_after REAL,
  hp_percent_delta REAL,
  enemy_hp_percent_damage REAL,

  type_effectiveness REAL,
  formula_context_json TEXT,
  special_formula_id TEXT,

  calculation_confidence REAL,
  recognition_confidence REAL,
  manual_override INTEGER NOT NULL DEFAULT 0,
  notes TEXT,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_event_id) REFERENCES battle_event(event_id),
  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (skill_id) REFERENCES skill_definition(skill_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `damage_event_id` | TEXT | 是 | 系统生成 | 伤害详情 ID。 |
| `battle_event_id` | TEXT | 是 | 系统生成 | 对应通用事件。 |
| `battle_id` | TEXT | 是 | 系统复制 | 所属战斗，便于索引。 |
| `attacker_side` | TEXT | 是 | 输入层 | 攻击方队伍。 |
| `attacker_elf_id` | TEXT | 是 | 输入层 | 攻击方精灵 ID。 |
| `defender_side` | TEXT | 是 | 输入层 | 防御方队伍。 |
| `defender_elf_id` | TEXT | 是 | 输入层 | 防御方精灵 ID。 |
| `skill_id` | TEXT | 否 | 输入层 | 使用技能。未知技能时可为空。 |
| `damage_display_type` | TEXT | 是 | 输入层 | `single_damage`、`visual_total_damage`、`combo_repeated_damage`、`special_damage`。 |
| `damage_value` | INTEGER | 条件 | 输入层 | 单次伤害主值。动画多段时等于最终总伤害。连击时可为空或用于保存单段主值，但推荐用 `per_hit_damage_value`。 |
| `final_total_damage_value` | INTEGER | 条件 | 输入层 | 动画多段最终显示总伤害。`visual_total_damage` 必填。 |
| `per_hit_damage_value` | INTEGER | 条件 | 输入层 | 连击单段伤害。`combo_repeated_damage` 必填。 |
| `hit_count` | INTEGER | 条件 | 输入层 / 系统计算 | 连击次数。`combo_repeated_damage` 必填。 |
| `computed_total_damage_value` | INTEGER | 条件 | 系统计算 | 连击总伤害，等于单段伤害 × 连击次数。 |
| `combo_count_source` | TEXT | 否 | 输入层 / 系统 | 连击次数来源：手动、技能规则、状态修正、识别推断。 |
| `combo_confidence` | REAL | 否 | 系统计算 | 连击次数置信度。 |
| `hp_percent_before` | REAL | 否 | 输入层 | 受击前生命百分比。 |
| `hp_percent_after` | REAL | 否 | 输入层 | 受击后生命百分比。 |
| `hp_percent_delta` | REAL | 否 | 系统计算 / 输入 | 血量百分比变化。 |
| `enemy_hp_percent_damage` | REAL | 否 | 输入层 | 对敌方造成伤害时的敌方扣血百分比。 |
| `type_effectiveness` | REAL | 否 | 系统计算 | 属性克制倍率或结果。 |
| `formula_context_json` | TEXT(JSON) | 否 | 系统生成 | 本次伤害计算上下文快照，便于解释。 |
| `special_formula_id` | TEXT | 否 | 规则数据 | 特殊公式处理器 ID。 |
| `calculation_confidence` | REAL | 否 | 系统计算 | 伤害计算置信度。 |
| `recognition_confidence` | REAL | 否 | 识别模块 | 伤害数字识别置信度。 |
| `manual_override` | INTEGER | 是 | 用户操作 | 是否手动覆盖。 |
| `notes` | TEXT | 否 | 用户 / 系统 | 备注。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE INDEX idx_damage_event_battle_pair ON damage_event(battle_id, attacker_elf_id, defender_elf_id);
CREATE INDEX idx_damage_event_skill ON damage_event(battle_id, skill_id);
CREATE INDEX idx_damage_event_display_type ON damage_event(battle_id, damage_display_type);
```

### 开发注释

- `single_damage`：`damage_value` 必填。
- `visual_total_damage`：`damage_value` 和 `final_total_damage_value` 均填最终总伤害。
- `combo_repeated_damage`：`per_hit_damage_value`、`hit_count`、`computed_total_damage_value` 必填。
- 实时反推：单次和动画多段使用 `damage_value`；连击优先使用 `per_hit_damage_value`。
- 击杀判断：连击使用 `computed_total_damage_value`。

---

## 6.3 `effect_change_event` 状态变化事件详情表

### 用途

记录状态获得、移除、叠层、刷新、替换、转换、转移、驱散、切换清除、过期、消耗等变化。

### 建表 SQL

```sql
CREATE TABLE effect_change_event (
  effect_change_event_id TEXT PRIMARY KEY,
  battle_event_id TEXT NOT NULL,
  battle_id TEXT NOT NULL,
  turn_number INTEGER NOT NULL,
  timestamp TEXT NOT NULL,

  change_type TEXT NOT NULL,
  effect_instance_id TEXT,
  effect_id TEXT NOT NULL,
  effect_name TEXT NOT NULL,
  category TEXT NOT NULL,

  target_side TEXT,
  target_elf_id TEXT,
  target_skill_slot_id TEXT,
  owner_scope TEXT NOT NULL,

  layers_before INTEGER,
  layers_after INTEGER,
  duration_before INTEGER,
  duration_after INTEGER,

  source_skill_id TEXT,
  source_elf_id TEXT,
  condition_branch TEXT,
  reason TEXT,

  source TEXT NOT NULL,
  recognition_confidence REAL,
  manual_override INTEGER NOT NULL DEFAULT 0,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_event_id) REFERENCES battle_event(event_id),
  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (effect_instance_id) REFERENCES battle_effect_instance(instance_id),
  FOREIGN KEY (effect_id) REFERENCES effect_definition(effect_id),
  FOREIGN KEY (source_skill_id) REFERENCES skill_definition(skill_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `effect_change_event_id` | TEXT | 是 | 系统生成 | 状态变化详情 ID。 |
| `battle_event_id` | TEXT | 是 | 系统生成 | 对应通用事件。 |
| `battle_id` | TEXT | 是 | 系统复制 | 所属战斗。 |
| `turn_number` | INTEGER | 是 | 系统复制 | 回合数。 |
| `timestamp` | TEXT | 是 | 系统生成 | 时间。 |
| `change_type` | TEXT | 是 | 状态引擎 | `apply`、`remove`、`stack`、`refresh`、`replace`、`convert`、`transfer`、`dispel`、`switch_clear`、`switch_keep`、`expire`、`consume`。 |
| `effect_instance_id` | TEXT | 否 | 状态引擎 | 关联状态实例。应用新状态前可能为空，创建后回填。 |
| `effect_id` | TEXT | 是 | 规则数据 | 状态定义 ID。 |
| `effect_name` | TEXT | 是 | 系统复制 | 状态名称快照。 |
| `category` | TEXT | 是 | 系统复制 | 状态分类快照。 |
| `target_side` | TEXT | 否 | 事件目标 | 目标队伍。 |
| `target_elf_id` | TEXT | 否 | 事件目标 | 目标精灵。 |
| `target_skill_slot_id` | TEXT | 否 | 事件目标 | 目标技能槽。 |
| `owner_scope` | TEXT | 是 | 规则数据 | 归属范围。 |
| `layers_before` | INTEGER | 否 | 状态引擎 | 变化前层数。 |
| `layers_after` | INTEGER | 否 | 状态引擎 | 变化后层数。 |
| `duration_before` | INTEGER | 否 | 状态引擎 | 变化前持续值。 |
| `duration_after` | INTEGER | 否 | 状态引擎 | 变化后持续值。 |
| `source_skill_id` | TEXT | 否 | 事件来源 | 来源技能。 |
| `source_elf_id` | TEXT | 否 | 事件来源 | 来源精灵。 |
| `condition_branch` | TEXT | 否 | 规则引擎 | 触发分支，如 `normal`、`against_defense`、`enemy_switched`。 |
| `reason` | TEXT | 否 | 状态引擎 | 变化原因。 |
| `source` | TEXT | 是 | 输入层 | 信息来源。 |
| `recognition_confidence` | REAL | 否 | 识别模块 | 识别置信度。 |
| `manual_override` | INTEGER | 是 | 用户操作 | 是否手动覆盖。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE INDEX idx_effect_change_battle_turn ON effect_change_event(battle_id, turn_number, timestamp);
CREATE INDEX idx_effect_change_instance ON effect_change_event(effect_instance_id);
CREATE INDEX idx_effect_change_effect ON effect_change_event(battle_id, effect_id);
CREATE INDEX idx_effect_change_type ON effect_change_event(battle_id, change_type);
```

---

## 6.4 `resource_change_event` 生命 / 能量变化事件详情表

### 用途

记录回复生命、失去生命、获得能量、失去能量、偷取能量等资源变化。

### 建表 SQL

```sql
CREATE TABLE resource_change_event (
  resource_change_event_id TEXT PRIMARY KEY,
  battle_event_id TEXT NOT NULL,
  battle_id TEXT NOT NULL,

  resource_type TEXT NOT NULL,
  change_type TEXT NOT NULL,

  source_side TEXT,
  source_elf_id TEXT,
  target_side TEXT NOT NULL,
  target_elf_id TEXT NOT NULL,

  value_type TEXT NOT NULL,
  value REAL NOT NULL,
  before_value REAL,
  after_value REAL,

  confidence REAL,
  manual_override INTEGER NOT NULL DEFAULT 0,
  notes TEXT,

  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,

  FOREIGN KEY (battle_event_id) REFERENCES battle_event(event_id),
  FOREIGN KEY (battle_id) REFERENCES battle(battle_id)
);
```

### 字段说明

| 字段 | 类型 | 必填 | 来源 | 作用 |
|---|---|---:|---|---|
| `resource_change_event_id` | TEXT | 是 | 系统生成 | 资源变化详情 ID。 |
| `battle_event_id` | TEXT | 是 | 系统生成 | 对应通用事件。 |
| `battle_id` | TEXT | 是 | 系统复制 | 所属战斗。 |
| `resource_type` | TEXT | 是 | 输入层 | `hp` 或 `energy`。 |
| `change_type` | TEXT | 是 | 输入层 | `gain`、`loss`、`set`、`steal`、`recover`。 |
| `source_side` | TEXT | 否 | 事件来源 | 来源队伍。 |
| `source_elf_id` | TEXT | 否 | 事件来源 | 来源精灵。 |
| `target_side` | TEXT | 是 | 事件目标 | 目标队伍。 |
| `target_elf_id` | TEXT | 是 | 事件目标 | 目标精灵。 |
| `value_type` | TEXT | 是 | 输入层 | `flat`、`percent`、`delta_percent`。 |
| `value` | REAL | 是 | 输入层 | 变化值。 |
| `before_value` | REAL | 否 | 输入层 / 系统 | 变化前值。 |
| `after_value` | REAL | 否 | 输入层 / 系统 | 变化后值。 |
| `confidence` | REAL | 否 | 系统 / 识别 | 置信度。 |
| `manual_override` | INTEGER | 是 | 用户操作 | 是否手动覆盖。 |
| `notes` | TEXT | 否 | 用户 / 系统 | 备注。 |
| `created_at` | TEXT | 是 | 系统生成 | 创建时间。 |
| `updated_at` | TEXT | 是 | 系统生成 | 更新时间。 |

### 索引

```sql
CREATE INDEX idx_resource_change_battle_target ON resource_change_event(battle_id, target_elf_id, resource_type);
```

---

## 7. 计算与缓存表

## 7.1 计算缓存策略

历史 `calculation_cache` 表已通过 Alembic `0006_drop_legacy_candidate_tables` 删除。当前阶段不保留持久计算缓存；后续如需缓存，应重新设计为与实时估计、状态快照和公式上下文绑定的新结构，并新增独立迁移。

---

## 8. 视图设计

## 8.1 `mark_effect_view`

```sql
CREATE VIEW mark_effect_view AS
SELECT * FROM effect_definition
WHERE category = 'mark' AND deleted_at IS NULL;
```

用途：查询所有印记定义。注意该视图不是独立规则系统。

## 8.2 `weather_effect_view`

```sql
CREATE VIEW weather_effect_view AS
SELECT * FROM effect_definition
WHERE category = 'weather' AND deleted_at IS NULL;
```

用途：查询所有天气定义。

## 8.3 `active_battle_effect_view`

```sql
CREATE VIEW active_battle_effect_view AS
SELECT
  bei.*,
  ed.effect_name,
  ed.category,
  ed.polarity,
  ed.display_group,
  ed.clear_on_switch,
  ed.formula_hooks_json
FROM battle_effect_instance bei
JOIN effect_definition ed ON bei.effect_id = ed.effect_id
WHERE bei.is_active = 1;
```

用途：前端展示和计算前快速查询当前有效状态。

---

## 9. 第一阶段最小必须表

第一阶段 MVP 至少需要以下表：

1. `elf_definition`
2. `elf_learnable_skill`
3. `nature_definition`
4. `skill_definition`
5. `effect_definition`
6. `type_effectiveness_rule`
7. `player_elf_build`
8. `player_elf_build_skill`
9. `team_preset`
10. `team_preset_slot`
11. `battle`
12. `battle_elf_state`
13. `battle_skill_slot`
14. `battle_effect_instance`
15. `battle_effect_snapshot`
16. `battle_event`
17. `damage_event`
18. `effect_change_event`
19. `resource_change_event`
20. `enemy_panel_estimate`
21. `enemy_panel_estimate_evidence`

---

## 10. 数据一致性规则

### 10.1 精灵命名一致性

- 所有精灵字段必须使用 `elf`。
- 禁止新增 `pet_id`、`pet_name`、`owner_pet_id` 等旧字段。
- 精灵表不设置 `alias_names`。
- 技能表可以设置 `alias_names_json`。

### 10.2 状态系统一致性

- 所有持续状态必须落入 `effect_definition` 和 `battle_effect_instance`。
- 不建立独立 `mark_instance`、`weather_instance`、`abnormal_instance` 主表。
- `category` 只做标签；清除、叠层、公式、转移、转换等规则必须读取字段。
- 印记允许多个不同印记共存。
- 天气通过 `conflict_group` 和 `conflict_policy` 控制互斥。

### 10.3 快照一致性

- 伤害事件必须有关联快照。
- 快照必须保存完整状态实例副本。
- 实时反推不得直接读取已变化的当前状态冒充历史状态。
- 修正历史事件后，必须从修正点重放并重建后续快照。

### 10.4 伤害事件一致性

- `single_damage`：`damage_value` 必填。
- `visual_total_damage`：`damage_value` 和 `final_total_damage_value` 必填且相等。
- `combo_repeated_damage`：`per_hit_damage_value`、`hit_count`、`computed_total_damage_value` 必填。
- 连击总伤害必须由系统计算，不依赖用户手填总伤害。

### 10.5 实时估计一致性

- 当前推算状态只写 `enemy_panel_estimate` 和 `enemy_panel_estimate_evidence`。
- 不再为敌方配置生成、保存或筛选候选空间。
- 玩家默认配置只作为展示和计算入口；保存时必须按当前实时约束校验。
- 估计约束、冲突、unknown factors 和来源事件必须能追溯。

---

## 11. Alembic 迁移建议

建议迁移拆分：

```text
001_create_static_rule_tables.py
002_create_player_build_tables.py
003_create_battle_runtime_tables.py
004_create_event_tables.py
005_create_views.py
006_drop_legacy_candidate_tables.py
```

迁移顺序必须满足外键依赖：

```text
elf_definition / nature_definition / skill_definition / effect_definition
  ↓
player_elf_build / elf_learnable_skill
  ↓
team_preset / team_preset_slot
  ↓
battle / battle_elf_state / battle_skill_slot
  ↓
battle_effect_instance / battle_effect_snapshot
  ↓
battle_event / damage_event / effect_change_event / resource_change_event
  ↓
enemy_panel_estimate / enemy_panel_estimate_evidence
```

由于 `battle_effect_instance.source_event_id` 和 `battle_event.snapshot_id` 存在互相引用需求，实际实现时可：

1. 建表时先不加其中一个外键。
2. 或使用应用层保证一致性。
3. SQLite 对后续添加外键支持有限，建议迁移设计阶段确定依赖方向。

推荐做法：

- `battle_event.snapshot_id` 加外键。
- `battle_effect_instance.source_event_id` 不加数据库外键，由应用层校验。

---

## 12. 示例 JSON 结构

### 12.1 `damage_rule_json`

```json
{
  "damage_type": "normal_formula",
  "attack_stat": "physical_attack",
  "defense_stat": "physical_defense",
  "power_source": "base_power",
  "ignore_defense": false,
  "ignore_type_effectiveness": false,
  "affected_by_stat_modifier": true,
  "affected_by_damage_modifier": true,
  "affected_by_weather": true,
  "affected_by_mark": true,
  "affected_by_abnormal": true,
  "affected_by_skill_modifier": true,
  "rounding_policy": "pending_confirm",
  "special_formula_id": null
}
```

### 12.2 `hit_rule_json`

```json
{
  "damage_display_type": "combo_repeated_damage",
  "is_combo": true,
  "base_hit_count": 3,
  "hit_count_type": "fixed",
  "min_hit_count": 3,
  "max_hit_count": 3,
  "hit_count_modifier_allowed": true,
  "visual_total_damage_displayed": false,
  "runtime_record_strategy": "per_hit_value_and_count",
  "combo_calculation_mode": "per_hit_formula_then_repeat",
  "combo_total_displayed": false,
  "combo_per_hit_same_damage": true
}
```

### 12.3 `effect_operations_json`

```json
[
  {
    "op_id": "op_001",
    "op_type": "apply_effect",
    "target": "enemy_active_elf",
    "effect_id": "burn",
    "value_type": "layer_count",
    "layers": 2,
    "duration_turns": null,
    "condition": "normal",
    "timing": "after_damage",
    "probability": 1.0,
    "can_be_manual_corrected": true,
    "note": "造成伤害后附加灼烧"
  }
]
```

### 12.4 `effect_instances_json` 快照副本

```json
[
  {
    "instance_id": "eff_inst_001",
    "effect_id": "starfall",
    "category": "mark",
    "owner_scope": "side",
    "owner_side": "enemy",
    "owner_elf_id": null,
    "layers": 3,
    "remaining_turns": null,
    "is_active": true
  },
  {
    "instance_id": "eff_inst_002",
    "effect_id": "burn",
    "category": "abnormal",
    "owner_scope": "elf",
    "owner_side": "enemy",
    "owner_elf_id": "elf_abc",
    "layers": 2,
    "clear_on_switch": true,
    "is_active": true
  }
]
```

---

## 13. 后续扩展预留

### 13.1 图像识别扩展表

第二阶段可增加：

- `recognition_observation`
- `recognition_candidate`
- `recognition_template`

用于记录 OCR / 图像识别原始结果、候选匹配和人工确认过程。

### 13.2 规则版本管理表

后续可增加：

- `rule_data_version`
- `rule_import_log`
- `rule_change_log`

用于处理游戏平衡调整和规则库导入。

### 13.3 实时面板估计表

推算主流程已经切换为“实时面板估计 + 默认配置校验”。当前不再规划候选聚合表。完整方案见：

```text
docs/03_系统设计/实时面板估计落地方案.md
```

以下表用于保存敌方估计档案和估计 evidence。旧 `build_candidate` / `calculation_cache` 已由 Alembic `0006_drop_legacy_candidate_tables` 删除。

#### `enemy_panel_estimate`

用途：保存每只敌方精灵当前估计档案，包括玩家默认配置、当前估计面板、属性约束、unknown factors 和最近 evidence 摘要。

```sql
CREATE TABLE enemy_panel_estimate (
  estimate_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  battle_elf_state_id TEXT NOT NULL,
  elf_id TEXT NOT NULL,
  default_config_json TEXT,
  default_panel_json TEXT,
  estimated_panel_json TEXT,
  stat_constraints_json TEXT,
  confidence_json TEXT,
  unknown_factors_json TEXT,
  confirmed_skill_ids_json TEXT,
  evidence_summary_json TEXT,
  updated_by_event_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (battle_id) REFERENCES battle(battle_id),
  FOREIGN KEY (battle_elf_state_id) REFERENCES battle_elf_state(battle_elf_state_id),
  FOREIGN KEY (elf_id) REFERENCES elf_definition(elf_id)
);

CREATE INDEX idx_enemy_panel_estimate_battle_elf
ON enemy_panel_estimate(battle_id, elf_id);

CREATE INDEX idx_enemy_panel_estimate_state
ON enemy_panel_estimate(battle_elf_state_id);
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `default_config_json` | 玩家选择的默认配置方案，只用于未知面板时的临时展示。 |
| `default_panel_json` | 按默认配置计算出的六维面板。 |
| `estimated_panel_json` | 当前展示用估计面板，可包含具体值或范围。 |
| `stat_constraints_json` | HP/物防/魔防/物攻/魔攻/速度等推导范围或不等式；普通攻击最小公式上下文完整时会写入低置信范围。 |
| `confidence_json` | 各属性置信状态，不代表严格概率。 |
| `unknown_factors_json` | 影响推导但尚未确认的减伤、应对、状态、天气、先制等因素。上下文不足时保留具体缺失原因。 |
| `confirmed_skill_ids_json` | 已观测到的敌方技能。 |
| `evidence_summary_json` | 最近推导摘要，完整明细建议拆到 evidence 表。 |

#### `enemy_panel_estimate_evidence`

用途：保存估计档案每次变化的事件级解释链，避免将长 evidence 反复追加到估计主表。

```sql
CREATE TABLE enemy_panel_estimate_evidence (
  evidence_id TEXT PRIMARY KEY,
  estimate_id TEXT NOT NULL,
  battle_id TEXT NOT NULL,
  source_event_id TEXT NOT NULL,
  observation_type TEXT NOT NULL,
  inferred_stats_json TEXT,
  constraint_delta_json TEXT,
  formula_context_json TEXT,
  unknown_factors_json TEXT,
  conflict_json TEXT,
  confidence TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (estimate_id) REFERENCES enemy_panel_estimate(estimate_id),
  FOREIGN KEY (battle_id) REFERENCES battle(battle_id)
);

CREATE INDEX idx_enemy_panel_estimate_evidence_estimate
ON enemy_panel_estimate_evidence(estimate_id, created_at);

CREATE INDEX idx_enemy_panel_estimate_evidence_event
ON enemy_panel_estimate_evidence(source_event_id);
```

说明：`source_event_id` 是来源引用，不强制外键到 `battle_event`。Observation API 允许使用 `observation_<uuid>` 形式的轻量观测 ID，未必对应一条通用战斗事件。

一致性规则：

- 默认配置不得作为硬排除依据。
- Observation 更新估计档案时必须保留 unknown factors；只有普通攻击最小公式上下文完整时，才写入低置信反向属性范围。
- 新约束与旧约束冲突时，不直接覆盖为“确认失败”，应写入 `conflict_json` 并等待修正或重放。
- 事件作废、修正和重放完成后，估计档案应可从事件流重算。
- 默认配置保存时只校验当前实时约束，不写 `build_candidate`。

---

## 14. 总结

本数据库设计采用 SQLite 本地文件数据库，围绕 `elf` 命名规范、统一状态系统、事件日志、状态快照和敌方实时面板估计组织。

关键点：

1. 精灵统一使用 `elf` 命名，精灵表不设置别名字段。
2. 技能可以保留别名，用于 OCR 和搜索容错。
3. 所有状态统一由 `effect_definition` 和 `battle_effect_instance` 管理。
4. 印记和天气都是状态实例，不再建立独立主规则系统。
5. 伤害事件必须绑定不可变状态快照。
6. 动画多段和连击必须分开记录。
7. 敌方默认配置只保存展示配置，真实推导以实时约束和 evidence 为准。
8. 所有复杂规则使用 JSON 存储，并由 Pydantic 在代码层校验。

## battle_elf_state 运行时有效形态扩展（2026-06-12）

为支持退化、萌化面板回退等战斗中临时按另一种族值结算的场景，`battle_elf_state` 新增以下可空字段（Alembic `0007_battle_runtime_form`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `runtime_form_elf_id` | string nullable | 当前运行时有效形态精灵 ID；为空表示使用原始 `elf_id`。 |
| `runtime_form_elf_name` | string nullable | 有效形态显示名冗余。 |
| `runtime_form_avatar` | string nullable | 有效形态头像冗余。 |
| `runtime_form_reason` | text nullable | 形态调整原因，例如退化/萌化面板回退。 |
| `nature_id` | string nullable | 战斗中保留的性格快照，用于运行时形态重算。 |
| `individual_talent_distribution_json` | text nullable | 战斗中保留的六维个体培养快照。 |

设计原则：原始 `elf_id` 表示这只战斗精灵的身份，不随退化变化；伤害预览、本系、属性和展示面板在存在 `runtime_form_elf_id` 时使用有效形态。