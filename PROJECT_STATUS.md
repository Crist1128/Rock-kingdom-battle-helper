# 当前项目状态

更新日期：2026-05-31

## 总体阶段

项目已经从“后端骨架”推进到 **前后端可联调的手动输入 MVP + 候选反推软评分初步闭环阶段**。

当前核心目标是：在保持本地规则库、己方配置、战斗事件、状态快照和候选配置链路稳定的基础上，继续补齐状态自动结算、技能规则分支、候选解释链、速度判断和事件重放。后端 MVP 完成路线已记录在 `docs/03_系统设计/后端MVP完成路线_v0.1.md`。候选推算当前坚持软评分，不因未验证公式进行硬排除。

## 已完成内容

### 后端

- 已建立 FastAPI 应用入口和 API v1 路由聚合。
- 已建立 SQLAlchemy ORM 模型，覆盖静态规则、己方配置、战斗运行时、候选配置、状态实例、快照和事件日志。
- 已建立 Alembic 迁移：
  - `0001_initial_schema.py`
  - `0002_event_correction_resource_mvp.py`
- 已建立 SQLite PRAGMA 初始化：foreign_keys、WAL、synchronous、busy_timeout。
- 已实现静态规则查询接口：精灵、技能、性格、状态定义。
- 已实现己方配置管理接口：创建、查询、更新、技能替换、软删除。
- 已实现战斗流程接口：创建、列表、详情、阵容录入、开始、切换、结束、归档、状态查询。
- 已实现事件接口：通用事件、伤害事件、资源事件、时间线、作废、修正、重放占位。
- 已实现状态实例接口：施加、移除、切换清除/保留。
- 已实现状态快照服务。
- 已实现敌方候选生成和候选摘要/详情/分页接口。
- 已实现 Observation API：支持伤害值、扣血百分比、技能出现、速度先后手等观测驱动候选软评分。
- 已实现普通攻击最小伤害计算、P0 状态伤害计算、星陨伤害计算、伤害观测匹配和 `RuleResolver` 雏形。
- 星陨已按独立公式接入 `DamageCalculator`：触发条件看非幻系攻击技能，伤害按幻系计算克制/抵抗，攻防属性跟随触发技能类别。
- Observation API 的伤害观测上下文已允许通过 payload 指定 `formula_type = status | starfall`，可先进入候选软评分。
- 阶段 A 已完成：`EffectDefinitionOut` 已扩展完整审阅字段，effect importer 已新增 `--status` 只读状态查询，前端类型和接口文档已同步。
- 阶段 B 已开始：`EffectService.apply_effect` 按 `EffectDefinition.owner_scope` 归一化状态挂载目标，避免星陨、天气等状态被挂错位置。
- 阶段 C 最小闭环已完成：`turns/end` 已接入灼烧、中毒、中毒印记、寄生、冻结阈值和暴风雪施加冻结；伤害事件后已接入星陨；切换入场已接入棘刺。自动结算会生成系统事件、资源变化、必要的状态变化和快照，敌方受击伤害会写入 Observation 软评分 evidence。
- 阶段 D 已完成：已新增 `EffectOperationExecutor` 并接入 `skill_use` 通用事件；支持 `apply_effect`、`add_layers`、`dynamic_apply_effect`、`remove_effect`、`clear_effects`、`change_weather`、`resource_change`、`multiply_layers` 和 `conditional_branch`。星陨相关技能规则已整理为 `backend/app/seed/starfall_skill_operations_p0.json`，并提供 dry-run/commit 导入器写入 `SkillDefinition.effect_operations_json`；当前本地库已 commit 10 个星陨相关技能的操作规则。
- 已实现候选 `match_score`、`confidence`、匹配/冲突事件与 evidence 写入；默认不硬排除。
- 已实现 BWIKI 数据管线：爬取、清洗、dry-run、导入。
- 已实现管理接口：远程检查、远程同步、本地 cleaned JSON 导入、任务查询。
- 已实现归档战斗物理清理管理接口，支持 dry-run。

### 前端

- 已建立 React + TypeScript + Vite 前端。
- 已实现页面：战斗首页、己方配置、准备阶段、战斗工作台、事件日志、规则库、设置/数据管理。
- 已封装主要后端 API。
- 已接入 health 检测、战斗列表、战斗归档、己方配置 CRUD、规则库查询。
- 已接入准备阶段阵容录入和开始战斗。
- 已接入战斗工作台快捷录入：伤害、资源、状态、切换。
- 已接入候选摘要、速度分布占位和时间线展示。
- 已接入 Observation API：伤害录入后可按条件同步提交候选反推观察，并刷新候选摘要/详情/Top 候选。
- 已接入候选 Top 5 展示。
- 已接入 rocom 数据更新管理入口和归档战斗清理入口。

### 数据

- 本地 cleaned 数据已包含：
  - 精灵：465
  - 技能：469
  - 精灵可学习技能：21447
  - 属性克制规则：113
- 本地数据库已有真实 rocom 静态数据。
- 30 种性格已拆为正式核心规则，后端启动时会幂等自检查并写入/修正。
- P0 状态定义已可通过 `backend/app/seed/effect_definitions_p0.json` 和 effect importer 写入；当前工作库已导入 10 条 P0 状态定义。

## 当前未完成内容

- 完整真实伤害体系尚未全部实现：当前已有普通攻击最小公式、P0 状态伤害、星陨、阶段 C 自动结算和阶段 D 技能效果操作；复杂公式分支、天气/状态 modifier、应对/防御独立结算仍需补齐。
- 候选硬排除尚未开启；当前只做软评分、置信度和 evidence 记录。
- 速度先手概率未实现；当前只有基础面板速度观测匹配。
- 事件重放重算仍为占位。
- 候选证据链接口仍需升级为完整解释页；当前 evidence 主要由 observation 处理过程写入候选记录。
- 图像识别未开始。
- 正式 `effect_definition` 状态定义数据仍需继续扩展；P0 状态定义已有 JSON 种子、dry-run 导入器和本地 commit 验证，但不会在普通启动时自动写入。

## 当前验证情况

最近进度文档记录的验证结果：

- 前端 `npm.cmd run typecheck` 通过。
- 前端 `npm.cmd run build` 通过。
- 后端阶段 D 新增测试 `python -m pytest app/tests/test_effect_operation_executor.py -q`：`9 passed`。
- 后端全量测试 `python -m pytest -q`：`54 passed`，仍有 FastAPI `on_event` deprecation warnings。
- 后端阶段 D 相关 Ruff 检查通过；全量 `python -m ruff check app` 仍受既有 rocom/config 等历史行宽和导入顺序问题影响，非本阶段新增问题。
- 后端相关模块 Ruff 检查通过。

新环境仍需先安装依赖：

```bash
cd backend
python -m pip install -e ".[dev]"
python -m pytest -q
```

## 下一步建议

后端 MVP 的完整阶段路线见：

```text
docs/03_系统设计/后端MVP完成路线_v0.1.md
```

当前建议立即推进：

1. 完善前端结束回合/伤害后/切换后反馈，展示自动结算了哪些状态、跳过了哪些状态、为什么跳过。
2. 进入阶段 E：补应对/防御独立结算层、`ModifierResolver`，把天气、状态、减伤和应对结果统一解析进公式上下文。
3. 标准化 Observation payload 与候选 evidence，增强状态/星陨/技能触发的解释链。
4. 实现事件重放重算，并继续保持候选硬排除默认关闭。

## 当前推进路线记录

后续围绕“通过计算解释伤害，并用观测伤害倒推敌方配置”的核心目标推进：

1. 先修基础一致性：统一状态分类枚举和叠层规则取值，避免状态导入后行为不一致。
2. 设计状态定义数据源格式，提供 dry-run 导入 `effect_definition` 的能力。
3. 先补 P0 状态定义：灼烧、中毒、寄生、冻结、棘刺印记、中毒印记、星陨印记，以及必要天气。
4. 实现状态伤害计算：灼烧、中毒、寄生、冻结阈值、棘刺。
5. 实现星陨伤害计算：触发技能只负责判定和选择物攻/魔攻分支，实际伤害按幻系计算克制/抵抗。
6. 规则可审阅接口、状态实例挂载校验、最小结束回合接口和阶段 C 自动结算已落地。
7. 自动结算稳定后，`EffectOperationExecutor` 已完成阶段 D；后续补应对/防御独立结算层和 `ModifierResolver`。
8. 计算稳定后接入更多候选软评分和前端解释链，仍不急于开启硬排除。
