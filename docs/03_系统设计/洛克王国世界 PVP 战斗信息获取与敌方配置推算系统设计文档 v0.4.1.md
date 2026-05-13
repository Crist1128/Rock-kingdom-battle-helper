# 洛克王国世界 PVP 战斗信息获取与敌方配置推算系统设计文档 v0.4.1-local

> 设计日期：2026-05-11  
> 设计依据：`需求说明 v0.4.1`、`开发规格 v0.4.1`  
> 应用形态：本地 Web 应用，前后端分离  
> 后端技术栈：Python + FastAPI + SQLite  
> 说明：本文件只描述系统架构、模块、流程、接口、部署和阶段计划；详细数据库表结构另见《SQLite 数据库设计文档 v0.4.1-local》。

---

## 1. 修订说明

本版相对前一版系统设计做以下重构：

1. 所有精灵相关英文命名统一改为 `elf`，包括 `elf_id`、`elf_name`、`ElfDefinition`、`BattleElfState`、`battle_elf_state`、`owner_elf_id`、`actor_elf_id`、`target_elf_id` 等。
2. 明确采用本地 Web 前后端分离架构，后端固定为 Python + FastAPI + SQLite。
3. 系统设计文档不再内嵌详细数据库表字段，只保留数据边界说明；数据库字段、索引、约束、注释全部拆到独立数据库设计文档。
4. 取消“一个增益印记槽 + 一个减益印记槽”的设计，印记统一作为 `BattleEffectInstance` 存在，允许同一队伍存在多个不同印记。
5. 天气也统一作为 `BattleEffectInstance` 管理，不再建立独立天气状态系统。
6. 不再持久化“战斗有效属性”；伤害计算统一使用 `DamageFormulaContext = 面板属性 + 技能规则 + 属性克制 + BattleEffectSnapshot + 伤害公式 + 特殊公式处理器`。
7. 区分“动画多段伤害”和“连击”：动画多段按最终显示总伤害作为一次伤害事件；连击记录单段伤害和连击次数，系统计算总伤害。
8. 第一阶段保持纯手动输入 MVP，不实现高级图像识别、动画多段逐段识别、连击每段触发独立状态、奉献具体公式。

---

## 2. 项目目标与系统边界

### 2.1 项目目标

本系统是《洛克王国世界》PVP 对战辅助工具。系统不自动替玩家做战斗决策，而是在对战过程中做以下事情：

1. 记录准备阶段双方六只精灵。
2. 读取己方完整配置。
3. 根据敌方 `elf_id` 生成敌方候选配置集合。
4. 记录技能、伤害、生命变化、能量变化、状态图标、天气、印记、异常、连击、切换等事实。
5. 基于面板属性、技能规则、属性克制、状态快照和伤害公式计算理论伤害。
6. 用实际伤害和扣血百分比过滤敌方候选配置。
7. 实时展示伤害区间、连击总伤害、速度先手关系、击杀判断和敌方配置置信度。
8. 提供可解释的证据链，让用户知道某个候选为什么保留或排除。

### 2.2 第一阶段范围

第一阶段是本地纯手动输入 MVP，目标是先验证核心规则、状态、事件、快照、推算链路。

必须实现：

- 本地启动后端服务和 Web 前端。
- 手动录入双方阵容。
- 手动录入己方完整配置。
- 基于数据库生成敌方候选配置。
- 手动录入技能使用、伤害、扣血百分比、连击单段伤害、连击次数、状态变化、天气、印记、切换。
- 统一维护 `BattleEffectInstance`。
- 伤害、治疗、能量变化、切换事件均绑定 `BattleEffectSnapshot`。
- 使用 `DamageFormulaContext` 进行伤害计算和敌方候选过滤。
- 展示双方技能伤害、生命百分比、速度先手概率、候选配置收敛结果。
- 支持历史事件修正，并从修正点重放重算。

第一阶段暂不实现：

- 奉献具体公式。
- 高级图像识别。
- 动画多段逐段伤害识别。
- 连击每段独立触发状态。
- 根据敌方行动习惯动态更新技能概率。
- 云端账号、多设备同步、多人共享。
- Redis、MySQL 或其他外部服务依赖。

### 2.3 后续阶段范围

第二阶段：半自动识别，包括当前双方精灵、技能名称、伤害数字、动画多段最终总伤害、连击单段伤害、状态图标、天气、印记、异常等。

第三阶段：实时辅助，包括自动刷新、自动维护候选集合、自动展示当前最优伤害数据、场下精灵伤害预估、切换前伤害预览。

第四阶段：高级推算，包括敌方技能组自动判断、遗漏状态提示、敌方行动习惯建模、奉献等复杂状态、连击每段触发规则、速度候选与伤害候选联合判断。

---

## 3. 技术架构选型

### 3.1 总体推荐技术栈

```text
前端：React + TypeScript + Vite
状态管理：Zustand + TanStack Query
UI：shadcn/ui 或 Ant Design（二选一，建议 shadcn/ui）
图表：Recharts 或 ECharts

后端：Python 3.12+ + FastAPI
数据校验：Pydantic v2
ORM：SQLAlchemy 2.x
迁移：Alembic
数据库：SQLite
服务运行：Uvicorn
测试：pytest

本地包装：第一阶段浏览器访问 localhost；后续可用 Tauri 做桌面壳
打包：前端构建为静态资源，由 FastAPI 挂载；后端可用 PyInstaller / uv 打包
```

### 3.2 为什么后端选择 Python + FastAPI

本项目后端核心不是传统 CRUD，而是规则计算、候选枚举、状态快照、伤害推算和回放重算。Python 在算法表达、数据处理、后续图像识别接入方面更合适。FastAPI 适合前后端分离的本地 API 服务，可以基于 Pydantic 模型输出清晰的接口结构和自动接口文档。

后端设计原则：

- API 层只负责请求、响应和基础校验。
- 业务逻辑放在 service 层。
- 伤害公式、速度判断、候选过滤放在 domain 层。
- SQLite 访问统一经过 repository 层。
- 计算缓存放在进程内，第一阶段不引入 Redis。

### 3.3 为什么数据库选择 SQLite

本系统第一阶段是本地单用户应用，SQLite 的优势是：

- 无需安装独立数据库服务。
- 数据就是本地文件，便于备份、导出和迁移。
- 适合本地规则库、战斗记录、事件日志和候选缓存。
- 配合 WAL 模式可以满足本地读写性能。
- 未来如需迁移 MySQL，可通过 SQLAlchemy 和 Alembic 降低迁移成本。

推荐 SQLite 运行配置：

```text
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
```

### 3.4 暂不使用 Redis 和 MySQL

第一阶段不建议引入 Redis 和 MySQL。

原因：

- 本地单用户场景不需要独立缓存服务。
- Redis 会增加安装、启动、打包和故障排查成本。
- MySQL 会显著增加本地部署复杂度。
- 第一阶段瓶颈主要在规则正确性、状态建模、候选过滤和 UI 输入效率，而不是数据库服务能力。

后续可以保留扩展边界：

- 多用户云端化时迁移 MySQL 或 PostgreSQL。
- 后台识别任务、跨进程缓存、WebSocket 广播变复杂时再引入 Redis。

---

## 4. 本地应用整体架构

### 4.1 进程形态

第一阶段推荐两个运行模式。

#### 开发模式

```text
浏览器
  ↓
Vite Dev Server: http://localhost:5173
  ↓ HTTP API
FastAPI Backend: http://localhost:8000
  ↓
SQLite DB: ./data/app.db
```

#### 本地发行模式

```text
浏览器或 Tauri WebView
  ↓
FastAPI Backend: http://127.0.0.1:{local_port}
  ├─ 挂载前端 dist 静态资源
  ├─ 提供 /api 接口
  └─ 访问 SQLite DB: ./data/app.db
```

### 4.2 分层架构

```text
Frontend Web UI
  ├─ 准备阶段页面
  ├─ 战斗面板页面
  ├─ 手动事件录入页面
  ├─ 状态编辑器
  ├─ 候选配置页面
  └─ 事件日志与回放页面

FastAPI API Layer
  ├─ battle_router
  ├─ elf_router
  ├─ skill_router
  ├─ effect_router
  ├─ event_router
  ├─ calculation_router
  └─ candidate_router

Application Service Layer
  ├─ BattleSessionService
  ├─ ManualInputService
  ├─ EventReplayService
  ├─ RuleDataService
  ├─ CandidateService
  ├─ CalculationService
  └─ CorrectionService

Domain Layer
  ├─ StatCalculator
  ├─ DamageFormulaEngine
  ├─ ComboEngine
  ├─ SpeedJudgeEngine
  ├─ BattleEffectEngine
  ├─ CandidateGenerator
  ├─ InferenceEngine
  └─ ExplanationEngine

Repository Layer
  ├─ ElfRepository
  ├─ SkillRepository
  ├─ EffectRepository
  ├─ BattleRepository
  ├─ EventRepository
  ├─ CandidateRepository
  └─ SnapshotRepository

SQLite Database
  ├─ 静态规则表
  ├─ 用户配置表
  ├─ 战斗运行时表
  ├─ 事件日志表
  ├─ 快照表
  └─ 推算结果表
```

### 4.3 数据流

```text
创建战斗
  ↓
录入双方阵容
  ↓
读取 ElfDefinition / SkillDefinition / NatureDefinition / EffectDefinition
  ↓
己方生成确定面板属性
  ↓
敌方生成 BuildCandidate 集合
  ↓
进入战斗阶段
  ↓
用户录入一条事实事件
  ↓
事件标准化为 BattleEvent + 子事件
  ↓
状态引擎应用事件并维护 BattleEffectInstance
  ↓
SnapshotService 生成 BattleEffectSnapshot
  ↓
DamageFormulaEngine 形成 DamageFormulaContext 并计算理论伤害
  ↓
InferenceEngine 更新候选配置 match_score / confidence / is_excluded
  ↓
SpeedJudgeEngine 更新速度区间和先手概率
  ↓
前端刷新当前对位、伤害、状态、候选和解释
```

---

## 5. 领域模型设计

### 5.1 静态规则数据

静态规则数据表示游戏规则本身，主要用于“查规则”。

包括：

- `ElfDefinition`：精灵基础信息、系别、种族资质、可学习技能和常见配置。
- `NatureDefinition`：性格正负修正。
- `SkillDefinition`：技能基础信息、伤害规则、命中 / 连击规则、效果操作。
- `EffectDefinition`：统一状态定义，包括普通属性修正、异常、印记、天气、技能槽修正、行动规则等。
- `TypeEffectivenessRule`：属性克制规则。

规则数据的版本必须可追踪，避免游戏平衡改动后旧战斗记录无法解释。

### 5.2 用户配置数据

用户配置数据主要是己方精灵完整配置。

包括：

- 己方精灵 `elf_id`。
- 性格 `nature_id`。
- 个体资质分布。
- 技能组。
- 面板属性缓存。
- 是否常用、备注、更新时间。

己方配置是确定数据，战斗开始时复制到 `BattleElfState` 中作为本场战斗的己方初始状态。

### 5.3 战斗运行时数据

战斗运行时数据表示某一场战斗的当前状态，主要用于“算当前结果”。

包括：

- `Battle`：战斗主状态、当前回合、双方当前在场精灵。
- `BattleElfState`：本场战斗中每只精灵的当前生命、能量、技能、状态关联等。
- `BattleEffectInstance`：当前存在的状态实例。
- `BuildCandidate`：敌方候选配置集合。

### 5.4 事件日志数据

事件日志表示某个时间点发生的事实，主要用于“回放、纠错、推算、解释”。

包括：

- `BattleEvent`：通用战斗事件。
- `DamageEvent`：伤害详情。
- `EffectChangeEvent`：状态变化详情。
- `ResourceChangeEvent`：生命 / 能量变化详情。
- `BattleEffectSnapshot`：事件发生瞬间的状态快照。

事件日志是系统可解释性的基础，不应只保存当前状态而丢失历史事实。

---

## 6. 核心模块设计

### 6.1 BattleSessionService 战斗会话服务

职责：管理一场战斗从准备阶段到结束的生命周期。

主要能力：

- 创建战斗。
- 录入双方六只精灵。
- 绑定己方配置。
- 初始化敌方候选配置。
- 维护当前回合。
- 维护当前上场精灵。
- 查询当前战斗完整状态。
- 结束或归档战斗。

关键规则：

- `battle.phase = preparation` 时允许调整阵容和己方配置。
- 进入 `battle` 阶段后，阵容不应直接修改；若识别错误，走手动纠错事件。
- 当前上场精灵通过 `self_active_elf_id` 和 `enemy_active_elf_id` 维护。

### 6.2 RuleDataService 规则数据服务

职责：统一读取精灵、性格、技能、状态、属性克制等静态规则。

主要能力：

- 按 `elf_id` 查询精灵定义。
- 按 `skill_id` 查询技能定义。
- 按 `effect_id` 查询状态定义。
- 搜索精灵名称和技能名称。
- 读取技能伤害规则、连击规则、效果操作。
- 读取状态 `clear_on_switch`、`owner_scope`、`formula_hooks` 等字段。

关键规则：

- 精灵不支持 `alias_names`。
- 技能可以支持 `alias_names`。
- 规则数据修改后需要更新 `data_version`。

### 6.3 ManualInputService 手动输入服务

职责：处理第一阶段所有用户手动录入。

支持输入：

- 双方阵容。
- 己方完整配置。
- 当前上场精灵。
- 技能使用。
- 单次伤害。
- 动画多段最终总伤害。
- 连击单段伤害和连击次数。
- 扣血百分比和血量百分比变化。
- 状态获得、移除、叠层、驱散、转换、转移。
- 天气变化。
- 印记变化。
- 精灵切换。
- 历史事件纠错。

输入优先级：

```text
manual_input > auto_recognition > system_inferred > database_rule
```

### 6.4 BattleEffectEngine 统一状态引擎

职责：统一管理所有持续存在或会影响计算的状态效果。

核心对象：

- `EffectDefinition`：规则定义。
- `BattleEffectInstance`：战斗中的状态实例。
- `BattleEffectSnapshot`：某一时点的状态快照。

重要设计：

- 不拆 `BuffSystem`、`DebuffSystem`、`AbnormalSystem`、`MarkSystem`、`WeatherSystem`。
- `category` 只是分类标签，不直接决定规则。
- 状态是否切换清除由 `clear_on_switch` 决定。
- 状态归属由 `owner_scope` 和挂载目标字段决定。
- 印记和天气也通过 `BattleEffectInstance` 管理。
- 星陨是 `category = mark` 的状态实例，不是异常或普通减益。

切换处理：

```text
发生 switch_elf
  ↓
读取离场精灵 owner_scope = elf 的 active BattleEffectInstance
  ↓
clear_on_switch = true：失效并记录 switch_clear
clear_on_switch = false：保留并记录 switch_keep
  ↓
owner_scope = side / field 的状态不受普通切换影响
  ↓
生成新的 BattleEffectSnapshot
```

### 6.5 SnapshotService 快照服务

职责：保存事件发生瞬间的状态快照。

要求：

- 伤害事件必须引用快照。
- 治疗事件必须引用快照。
- 能量变化事件必须引用快照。
- 精灵切换事件必须引用切换前或切换后的快照，具体由事件类型标注。
- 快照应保存完整状态实例副本，不能只保存会随时间变化的实例 ID。

快照用途：

- 伤害计算。
- 候选过滤。
- 事件回放。
- 纠错后重算。
- UI 解释“当时为什么是这个伤害”。

### 6.6 StatCalculator 属性计算器

职责：根据精灵种族资质、个体资质、性格和 PVP 固定参数计算面板属性。

PVP 固定参数：

- 等级固定 60。
- 生命成长值 100。
- 非生命成长值 50。
- 6 星、0 觉醒、50 成长等级。

计算输出：

- `final_hp`
- `final_physical_attack`
- `final_physical_defense`
- `final_magic_attack`
- `final_magic_defense`
- `final_speed`

注意：

- 候选配置只保存面板属性。
- 不保存经过状态修正后的“战斗有效属性”。
- 状态修正在 `DamageFormulaContext` 或 `SpeedContext` 中即时应用。

### 6.7 DamageFormulaEngine 伤害公式引擎

职责：根据公式上下文计算理论伤害。

输入：

```text
DamageFormulaContext = {
  attacker_elf_id,
  defender_elf_id,
  skill_id,
  attacker_panel_stats,
  defender_panel_stats,
  effect_snapshot_id,
  active_effect_instance_ids,
  type_effectiveness,
  damage_rule,
  hit_rule,
  damage_display_type,
  hit_count,
  special_formula_id,
  rounding_policy
}
```

输出：

- 单次伤害单值或区间。
- 动画多段最终总伤害。
- 连击单段伤害。
- 连击次数。
- 连击总伤害。
- 生命百分比。
- 是否可击杀。
- 计算置信度。
- 公式解释。

关键规则：

- 伤害计算不读取“当前状态”，只读取事件绑定的快照。
- 如果存在未实现特殊状态，例如奉献，则降低计算置信度。
- 如果伤害公式或取整策略尚未确认，则结果标注为公式待校验。

### 6.8 ComboEngine 连击引擎

职责：处理连击次数、单段伤害和总伤害。

规则：

- 动画多段不是连击。
- 动画多段使用最终显示总伤害，按一次伤害事件处理。
- 连击记录 `per_hit_damage_value` 和 `hit_count`。
- 连击总伤害由系统计算：`computed_total_damage_value = per_hit_damage_value * hit_count`。
- 候选过滤优先使用连击单段伤害。
- 击杀判断使用连击总伤害。

第一阶段连击次数优先级暂定：

```text
固定连击 > 加减连击 > 倍率连击 > 技能基础连击
```

该优先级后续可通过规则表调整。

### 6.9 SpeedJudgeEngine 速度判断引擎

职责：基于 `SpeedContext` 判断出手顺序和先手概率。

速度判断分两层：

1. 行动规则修正：先手、迅捷、蓄力、无法行动、冰冻、眩晕、打断、无法更换等。
2. 常规速度比较。

常规比较：

```text
if self_speed > enemy_speed:
    self first
elif self_speed < enemy_speed:
    enemy first
else:
    each side 50%
```

敌方速度未知时：

```text
遍历敌方未排除候选配置
按候选权重计算 self_first_probability / enemy_first_probability
输出敌方速度区间、是否存在同速候选和综合先手概率
```

### 6.10 CandidateGenerator 候选生成器

职责：准备阶段为敌方每只精灵生成候选配置集合。

生成维度：

- 性格：六维中选一个正面维度、一个不同的负面维度。
- 个体资质维度：1 到 3 个维度存在个体资质。
- 个体资质数值：7 到 10。
- 技能：初始可能技能来自 `ElfDefinition.learnable_skill_ids`。

常见技能组、常见性格、常见个体资质分布只影响候选初始权重，不直接排除冷门配置。

优化策略：

- 候选生成后缓存六维面板属性。
- 对相同面板属性的候选可做聚合。
- 当前上场敌方精灵优先全量计算。
- 后备敌方精灵可延迟计算或只生成摘要。

### 6.11 InferenceEngine 敌方配置推算引擎

职责：根据伤害事件和状态快照更新敌方候选配置。

流程：

```text
读取 DamageEvent
  ↓
读取关联 BattleEffectSnapshot
  ↓
读取攻击方与防御方配置
  ↓
形成 DamageFormulaContext
  ↓
枚举候选配置或 技能 × 候选配置
  ↓
计算理论伤害
  ↓
与实际伤害、扣血百分比对比
  ↓
更新 BuildCandidate.match_score / confidence / is_excluded
  ↓
记录证据与解释
```

排除策略：

- 高置信手动事件可以强过滤。
- 低置信识别事件只调低分数，不立即排除。
- 公式待确认、状态不完整、特殊规则未实现时不强排除。
- 伤害值与扣血百分比明显矛盾时，事件自身标记为低置信。

### 6.12 EventReplayService 事件回放服务

职责：从事件日志重建战斗状态和推算结果。

用途：

- 历史事件纠错。
- 规则更新后重新计算。
- 解释候选变化。
- 复盘战斗。

设计原则：

- 原始事件尽量不物理删除。
- 纠错记录为新事件或修订记录。
- 从修正点开始重放后续事件。
- 重放后刷新 BattleElfState、BattleEffectInstance、BuildCandidate 和计算缓存。

### 6.13 ExplanationEngine 解释引擎

职责：为 UI 提供可读解释。

解释内容：

- 某个候选为什么被保留。
- 某个候选为什么被排除。
- 某次伤害用了哪些状态快照。
- 伤害区间为什么存在不确定性。
- 速度概率由哪些候选速度构成。
- 哪些状态规则尚未实现或需要实测。

---

## 7. 关键业务流程设计

### 7.1 准备阶段流程

```text
创建 Battle
  ↓
录入己方六只 elf
  ↓
读取玩家己方配置 PlayerElfBuild
  ↓
计算己方面板属性并写入 BattleElfState
  ↓
录入敌方六只 elf
  ↓
读取 ElfDefinition / SkillDefinition / NatureDefinition
  ↓
为敌方每只 elf 生成 BuildCandidate
  ↓
选择双方当前首发 elf
  ↓
进入 battle 阶段
```

### 7.2 伤害事件流程

```text
用户录入伤害事实
  ↓
判断 damage_display_type
  ├─ single_damage：记录 damage_value
  ├─ visual_total_damage：记录 final_total_damage_value，并作为 damage_value
  ├─ combo_repeated_damage：记录 per_hit_damage_value + hit_count，计算 computed_total_damage_value
  └─ special_damage：交给特殊规则
  ↓
生成或读取事件发生瞬间 BattleEffectSnapshot
  ↓
保存 BattleEvent + DamageEvent
  ↓
更新 BattleElfState 生命百分比
  ↓
调用 InferenceEngine 更新候选
  ↓
刷新 DamageResult / SpeedContext / UI
```

### 7.3 状态变化流程

```text
用户录入状态变化或技能 effect_operations 触发状态变化
  ↓
读取 EffectDefinition
  ↓
根据 owner_scope 和目标生成 BattleEffectInstance
  ↓
处理 stack_rule / conflict_group / conflict_policy
  ↓
保存 BattleEvent + EffectChangeEvent
  ↓
生成新的 BattleEffectSnapshot
  ↓
刷新 UI 状态图标和后续计算结果
```

### 7.4 精灵切换流程

```text
用户录入 switch_elf
  ↓
读取离场 elf 的 active BattleEffectInstance
  ↓
clear_on_switch = true：失效并记录 switch_clear
clear_on_switch = false：保留并记录 switch_keep
  ↓
side / field 状态不受普通切换影响
  ↓
更新 active elf
  ↓
保存切换事件和状态变化事件
  ↓
生成 BattleEffectSnapshot
  ↓
刷新速度、伤害、候选展示
```

### 7.5 手动纠错流程

```text
用户选择历史事件
  ↓
提交修正内容
  ↓
写入 correction 记录或生成 manual correction 事件
  ↓
从修正事件开始回放后续事件
  ↓
重建运行时状态、状态实例、快照和候选配置
  ↓
刷新 UI 并提示哪些结果发生变化
```

---

## 8. 前端页面设计

### 8.1 页面结构

建议前端包含以下页面：

1. 首页 / 战斗列表。
2. 规则数据库维护页。
3. 己方配置管理页。
4. 准备阶段阵容页。
5. 战斗实时面板。
6. 手动事件录入面板。
7. 状态编辑器。
8. 候选配置与推算解释页。
9. 事件日志与回放页。
10. 设置与数据导入导出页。

### 8.2 战斗实时面板

展示内容：

- 我方当前精灵、敌方当前精灵。
- 双方生命、能量、技能组。
- 当前所有状态图标。
- 当前天气和场地效果。
- 当前印记列表。
- 速度区间、同速情况、综合先手概率。
- 我方技能对敌方的伤害区间和击杀判断。
- 敌方已知 / 可能技能对我方的伤害区间和击杀判断。
- 连击单段伤害、连击次数、连击总伤害。
- 敌方配置置信度。
- 未实现规则提示。

### 8.3 手动输入效率设计

第一阶段实时性依赖手动输入效率，必须提供：

- 精灵名称搜索。
- 技能名称搜索。
- 常见技能一键选择。
- 状态图标快速选择。
- 天气快速选择。
- 印记快速选择。
- 最近使用项。
- 常用伤害事件快捷录入。
- 连击单段伤害和次数快捷录入。
- 一键修正上一条事件。

### 8.4 候选配置展示

每只敌方精灵展示：

- 候选数量。
- 配置状态：未知、低置信度、中置信度、高置信度、已基本确认。
- 可能性格。
- 可能个体资质分布。
- 面板属性区间。
- 速度区间。
- 可能技能和已确认技能。
- 证据数量。
- 最近一次更新原因。
- 已排除候选及排除原因。

---

## 9. API 设计草案

接口统一前缀：`/api`。

### 9.1 规则数据接口

```text
GET    /api/elves
GET    /api/elves/{elf_id}
POST   /api/elves
PUT    /api/elves/{elf_id}

GET    /api/natures
GET    /api/skills
GET    /api/skills/{skill_id}
POST   /api/skills
PUT    /api/skills/{skill_id}

GET    /api/effects
GET    /api/effects/{effect_id}
POST   /api/effects
PUT    /api/effects/{effect_id}

GET    /api/type-effectiveness
```

### 9.2 己方配置接口

```text
GET    /api/player-elf-builds
GET    /api/player-elf-builds/{build_id}
POST   /api/player-elf-builds
PUT    /api/player-elf-builds/{build_id}
DELETE /api/player-elf-builds/{build_id}
```

### 9.3 战斗会话接口

```text
GET    /api/battles
POST   /api/battles
GET    /api/battles/{battle_id}
PUT    /api/battles/{battle_id}
POST   /api/battles/{battle_id}/lineup
POST   /api/battles/{battle_id}/start
POST   /api/battles/{battle_id}/finish
GET    /api/battles/{battle_id}/state
```

### 9.4 事件接口

```text
GET    /api/battles/{battle_id}/events
POST   /api/battles/{battle_id}/events/skill-use
POST   /api/battles/{battle_id}/events/damage
POST   /api/battles/{battle_id}/events/effect-change
POST   /api/battles/{battle_id}/events/resource-change
POST   /api/battles/{battle_id}/events/switch-elf
POST   /api/battles/{battle_id}/events/{event_id}/correct
POST   /api/battles/{battle_id}/replay
```

### 9.5 计算和推算接口

```text
GET    /api/battles/{battle_id}/damage-preview
POST   /api/battles/{battle_id}/calculate-damage
GET    /api/battles/{battle_id}/speed-judge
GET    /api/battles/{battle_id}/candidates
GET    /api/battles/{battle_id}/candidates/{candidate_id}
GET    /api/battles/{battle_id}/candidates/{candidate_id}/explanation
POST   /api/battles/{battle_id}/recalculate
```

### 9.6 数据导入导出接口

```text
GET    /api/export/rules
POST   /api/import/rules
GET    /api/export/battle/{battle_id}
POST   /api/import/battle
GET    /api/export/database-backup
```

---

## 10. 后端项目结构建议

```text
backend/
  app/
    main.py
    core/
      config.py
      logging.py
      database.py
      sqlite_pragmas.py
    api/
      routers/
        elf_router.py
        skill_router.py
        effect_router.py
        battle_router.py
        event_router.py
        calculation_router.py
        candidate_router.py
    schemas/
      elf_schema.py
      skill_schema.py
      effect_schema.py
      battle_schema.py
      event_schema.py
      calculation_schema.py
      candidate_schema.py
    models/
      static_models.py
      player_models.py
      battle_models.py
      event_models.py
      candidate_models.py
    repositories/
      elf_repository.py
      skill_repository.py
      effect_repository.py
      battle_repository.py
      event_repository.py
      candidate_repository.py
      snapshot_repository.py
    services/
      battle_session_service.py
      manual_input_service.py
      rule_data_service.py
      snapshot_service.py
      event_replay_service.py
      correction_service.py
    domain/
      stat_calculator.py
      damage_formula_engine.py
      combo_engine.py
      speed_judge_engine.py
      battle_effect_engine.py
      candidate_generator.py
      inference_engine.py
      explanation_engine.py
    migrations/
      env.py
      versions/
  tests/
    unit/
    integration/
  pyproject.toml
```

---

## 11. 性能设计

### 11.1 主要性能压力

- 单只敌方精灵候选量较大。
- 敌方技能未知时需要枚举 `possible_skill × candidate`。
- 每次事件后可能触发伤害、速度和候选展示刷新。
- 快照和事件日志持续增长。

### 11.2 优化策略

1. 候选生成后缓存六维面板属性。
2. 对相同面板属性的候选做聚合。
3. 已排除候选默认不参与实时伤害展示，但保留证据。
4. 只对当前上场敌方精灵做高频实时计算。
5. 伤害计算结果按 `skill_id + attacker_stats_hash + defender_stats_hash + snapshot_hash` 做进程内缓存。
6. 快照生成 `snapshot_hash`，状态未变时复用结果。
7. SQLite 开启 WAL 模式。
8. UI 对候选列表分页，只展示摘要和 Top-K。
9. 重放重算时可显示进度，不阻塞主 UI。

---

## 12. 可靠性与可解释性设计

### 12.1 事件可信度

每条事件必须记录：

- `source`：manual_input / auto_recognition / system_inferred / system_calculated / database_rule。
- `recognition_confidence`。
- `manual_override`。
- `notes`。

### 12.2 候选排除可解释

候选被排除时必须记录：

- 触发排除的事件。
- 实际伤害。
- 理论伤害或理论区间。
- 误差。
- 快照 ID。
- 排除原因。

### 12.3 低置信事件处理

低置信事件不应强排除候选，只降低候选分数。

低置信来源包括：

- 自动识别置信度低。
- 伤害值与扣血百分比矛盾。
- 状态快照不完整。
- 伤害公式取整策略未确认。
- 存在未实现特殊状态。
- 连击次数来源不可靠。

---

## 13. 本地部署与数据管理

### 13.1 本地目录结构

```text
app_root/
  data/
    app.db
    backups/
  logs/
    app.log
  rules/
    import/
    export/
  frontend_dist/
  backend/
```

### 13.2 数据备份

必须提供：

- 一键备份 SQLite 数据库。
- 导出规则数据。
- 导出单场战斗记录。
- 导入规则数据。
- 导入历史战斗。

### 13.3 配置项

建议配置：

```text
APP_ENV=local
DB_PATH=./data/app.db
API_HOST=127.0.0.1
API_PORT=8000
ENABLE_AUTO_RECOGNITION=false
LOG_LEVEL=INFO
```

---

## 14. 阶段计划

### M1：基础规则库与己方配置

- 精灵、性格、技能、状态规则维护。
- 己方配置录入。
- 面板属性计算。
- 前端基础搜索和选择组件。

### M2：战斗会话与手动事件录入

- 创建战斗。
- 录入双方阵容。
- 当前上场精灵管理。
- 手动录入技能、伤害、连击、状态、切换。

### M3：统一状态系统与快照

- `BattleEffectInstance`。
- `BattleEffectSnapshot`。
- 切换清除规则。
- 印记和天气作为状态实例。
- 状态编辑器。

### M4：候选生成与推算

- 敌方候选配置生成。
- 我方攻击敌方过滤防御侧候选。
- 敌方攻击我方过滤攻击侧候选。
- 技能未知时 `skill × candidate` 联合枚举。

### M5：伤害、连击与速度展示

- 我方技能伤害区间。
- 敌方技能伤害区间。
- 动画多段最终总伤害处理。
- 连击单段和总伤害处理。
- 速度区间和先手概率。

### M6：纠错、回放和解释

- 历史事件修正。
- 从修正点重放。
- 候选排除原因。
- 伤害公式解释。
- 低置信事件提示。

---

## 15. 第一阶段验收标准

1. 能本地启动 FastAPI 后端和 Web 前端。
2. 能创建战斗并录入双方六只精灵。
3. 能录入己方完整配置并正确计算面板属性。
4. 能为敌方精灵生成候选配置集合。
5. 能手动录入单次伤害、动画多段最终总伤害、连击单段伤害和连击次数。
6. 能统一维护普通状态、异常、印记、天气、技能槽修正、行动规则状态。
7. 能按 `clear_on_switch` 正确处理切换清除和保留。
8. 能为伤害、治疗、能量变化、切换事件保存状态快照。
9. 能使用 `DamageFormulaContext` 计算理论伤害。
10. 能根据伤害事件过滤敌方候选配置。
11. 能展示伤害区间、生命百分比、连击总伤害、速度先手概率。
12. 能展示候选配置置信度和排除原因。
13. 能修改历史事件并触发重放重算。
14. 系统设计和数据库设计中所有精灵相关英文命名均使用 `elf`。
