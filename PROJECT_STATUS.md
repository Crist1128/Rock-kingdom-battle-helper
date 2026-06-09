# 当前项目状态

更新日期：2026-06-08

## 总体阶段

项目已经从“后端骨架”推进到 **前后端可联调的手动输入 MVP + 实时面板反推主流程阶段**。

当前核心目标是：在保持本地规则库、己方配置、战斗事件和状态快照稳定的基础上，继续巩固“实时面板估计 + 默认配置校验”的新反推方式，并补齐天气/状态公式修正、完整应对/防御结算、速度判断和事件重放。后端 MVP 完成路线已记录在 `docs/03_系统设计/后端MVP完成路线_v0.1.md`。旧候选表、旧候选接口和按需配置展开接口已从主流程下线，旧表暂不删除，后续迁移清理。

## 已完成内容

### 后端

- 已建立 FastAPI 应用入口和 API v1 路由聚合。
- 已建立 SQLAlchemy ORM 模型，覆盖静态规则、己方配置、战斗运行时、实时估计、状态实例、快照和事件日志；旧候选表模型仍保留为待清理遗留结构。
- 已建立 Alembic 迁移：
  - `0001_initial_schema.py`
  - `0002_event_correction_resource_mvp.py`
- 已建立 SQLite PRAGMA 初始化：foreign_keys、WAL、synchronous、busy_timeout。
- 已实现静态规则查询接口：精灵、技能、性格、状态定义。
- 已实现己方配置管理接口：创建、查询、更新、技能替换、软删除。
- 已实现配队预设接口：可保存己方 6 配置配队和敌方热门精灵阵容，支持查询、更新和软删除；新增 Alembic 迁移 `0003_team_presets.py`。
- 已实现战斗流程接口：创建、列表、详情、阵容录入、开始、切换、结束、归档、状态查询。
- 已实现事件接口：通用事件、伤害事件、资源事件、时间线、作废、修正、重放占位。
- 已实现状态实例接口：施加、移除、切换清除/保留。
- 已实现状态快照服务。
- 已实现旧敌方候选生成和候选摘要/详情/分页代码，但 `/candidates/*` 已不再挂载；`build_candidate` 不再由主流程写入，后续确认无兼容需求后删除。
- 已实现 Observation API：支持伤害值、扣血百分比、技能出现、速度先后手等观测写入实时估计 evidence 和属性约束。
- 已实现普通攻击最小伤害计算、P0 状态伤害计算、星陨伤害计算、伤害观测匹配、`RuleResolver` 雏形、`ModifierResolver` 与 `ResponseResolver` 最小闭环。
- 星陨已按独立公式接入 `DamageCalculator`：触发条件看非幻系攻击技能，伤害按幻系计算克制/抵抗，攻防属性跟随触发技能类别。
- Observation API 的伤害观测上下文已允许通过 payload 指定 `formula_type = status | starfall`；非普通攻击最小公式会先记录 unknown，后续纳入状态/天气新反推规则。
- 阶段 A 已完成：`EffectDefinitionOut` 已扩展完整审阅字段，effect importer 已新增 `--status` 只读状态查询，前端类型和接口文档已同步。
- 阶段 B 已开始：`EffectService.apply_effect` 按 `EffectDefinition.owner_scope` 归一化状态挂载目标，避免星陨、天气等状态被挂错位置。
- 阶段 C 最小闭环已完成：`turns/end` 已接入灼烧、中毒、中毒印记、寄生、冻结阈值和暴风雪施加冻结；伤害事件后已接入星陨；切换入场已接入棘刺。自动结算会生成系统事件、资源变化、必要的状态变化和快照，敌方受击伤害会写入实时估计 evidence。
- 阶段 D 已完成：已新增 `EffectOperationExecutor` 并接入 `skill_use`；后端已提供专用 `POST /battles/{battle_id}/skill-events` 入口，支持 `apply_effect`、`add_layers`、`dynamic_apply_effect`、`remove_effect`、`clear_effects`、`change_weather`、`resource_change`、`multiply_layers` 和 `conditional_branch`。星陨相关技能规则已整理为 `backend/app/seed/starfall_skill_operations_p0.json`，并提供 dry-run/commit 导入器写入 `SkillDefinition.effect_operations_json`；当前本地库已 commit 10 个星陨相关技能的操作规则。
- 阶段 E 已进入最小闭环：`ModifierResolver` 可解析 payload、`defense_skill_id` 和历史快照状态中的结构化减伤来源；`ResponseResolver` 可解析应对倍率，并在应对成功未知时只记录 unknown；手动伤害事件已可把 `defense_skill_id` 与 `response_attack_success` / `response_defense_success` / `response_status_success` 写入事件 payload、公式上下文和 observation payload；rocom cleaner 可从 raw/cleaned 技能定义中提取稳定的“减伤 X% / 应对目标”规则，正式运行以入库后的 `skill_definition` 为准。
- 核心默认战斗规则已补齐：后端启动时幂等写入通用技能“聚能”（状态技能、能耗 0、获得 5 能量），阵容录入后的双方精灵初始能量为 10，精灵可学技能查询会虚拟包含该默认技能。
- Observation 伤害 payload 已标准化为 `observation_payload_v1` 并保留旧平铺字段兼容；Observation、手动伤害事件和自动结算伤害现在默认只更新实时估计，不再更新旧候选 `match_score` / `confidence` / `is_excluded`。
- 已完成“实时面板估计 + 默认配置校验”落地：敌方精灵会创建估计档案，可查询估计、设置默认配置并计算默认展示面板；默认配置按种族值启发式选择性格和生命/主攻/速度资质；Observation 会同步写入受影响属性、unknown factors，并在普通攻击最小公式上下文完整时写入低置信 HP/攻防范围；整数剩余百分比模式已支持反推出可用 HP 区间。前端默认配置选择不再依赖配置展开；保存时由后端按当前约束校验完整面板。复杂公式、天气/状态反推和重放重算尚未接入。
- 已实现 BWIKI 数据管线：爬取、清洗、dry-run、导入。
- 已实现管理接口：远程检查、远程同步、本地 cleaned JSON 导入、任务查询。
- 已实现归档战斗物理清理管理接口，支持 dry-run。

### 前端

- 已建立 React + TypeScript + Vite 前端。
- 已实现页面：战斗首页、己方配置、准备阶段、战斗工作台、事件日志、规则库、设置/数据管理。
- 已封装主要后端 API。
- 已接入 health 检测、战斗列表、战斗归档、己方配置 CRUD、规则库查询。
- 已接入己方配置页配队管理，可把 6 个已保存配置组合为己方配队，也可录入敌方热门阵容。
- 已接入准备阶段阵容录入、配队快速填充和开始战斗。
- 已接入战斗工作台快捷录入：伤害、资源、状态、切换。
- 战斗工作台已接入 `turns/end`：可从顶部或快捷录入区结束当前回合，刷新状态、时间线与实时估计信息，并展示最近一次自动结算摘要。
- 战斗工作台已接入专用 `skill-events` 录入：可测试已入库 `effect_operations_json` 的状态、天气和资源操作。
- 已接入实时面板估计、默认配置编辑、默认面板、估计 evidence、实时推导范围、unknown factors、按约束限制默认性格选择、当前对位展示玩家选择性格、事件作废/通用修正、重放占位和快照详情展示，方便测试普通攻击、状态/星陨、技能结构化操作和应对/防御上下文对实时估计的影响；旧候选 Top 选择、旧候选重新生成和按需配置展开已从主面板移除。
- 已接入 rocom 数据更新管理入口和归档战斗清理入口。

### 数据

- 本地 cleaned 数据已包含：
  - 精灵：465
  - 技能：469
  - 精灵可学习技能：21447
  - 属性克制规则：113
- 本地数据库已有真实 rocom 静态数据，当前 `skill_definition` 已统一导入 `rocom_bwiki_20260603` 版本；45 个防御技能中 44 个固定减伤规则已写入 `damage_rule_json`，无固定减伤的“硬门”保持未解析。
- 30 种性格已拆为正式核心规则，后端启动时会幂等自检查并写入/修正。
- P0 状态定义已可通过 `backend/app/seed/effect_definitions_p0.json` 和 effect importer 写入；当前工作库已导入 10 条 P0 状态定义。

## 当前未完成内容

- 完整真实伤害体系尚未全部实现：当前已有普通攻击最小公式、P0 状态伤害、星陨、阶段 C 自动结算、阶段 D 技能效果操作和阶段 E 最小减伤/应对解析；复杂公式分支、天气/状态 modifier、完整应对/防御独立结算仍需补齐。
- 实时面板估计仍处在第一阶段：已有估计档案、自动默认配置、默认配置展示接口、Observation evidence 写入、普通攻击最小公式反向约束、整数 HP 百分比反推、默认配置校验、可选性格约束和前端主面板切换；复杂公式、天气/状态 modifier、速度概率和重放重算尚未接入。
- 旧候选空间方案已放弃作为业务方案；遗留 `build_candidate` 表、旧 candidate service/schema/tests 暂不删除，后续做数据库迁移和代码清理。
- 速度先手概率未实现；当前只有基础面板速度观测匹配。
- 事件重放重算仍为占位。
- 实时估计 evidence 仍需升级为完整解释页；当前已可展示 observation evidence，但还缺少面向公式上下文、状态/天气 modifier 和冲突处理的完整解释视图。
- 图像识别未开始。
- 正式 `effect_definition` 状态定义数据仍需继续扩展；P0 状态定义已有 JSON 种子、dry-run 导入器和本地 commit 验证，但不会在普通启动时自动写入。

## 当前验证情况

最近进度文档记录的验证结果：

- 旧候选默认生成关闭、前端主面板切实时估计后，后端定向测试 `python -m pytest app\tests\test_estimate_service.py app\tests\test_candidate_generation.py app\tests\test_core_default_skill.py -q`：`13 passed`。
- 旧候选默认生成关闭、前端主面板切实时估计后，后端 Ruff `python -m ruff check app` 通过。
- 旧候选默认生成关闭、前端主面板切实时估计后，前端 `npm.cmd run typecheck` 和 `npm.cmd run build` 通过。
- 旧候选默认生成关闭、前端主面板切实时估计后，相关后端/前端/文档文件 mojibake 扫描通过，`git diff --check` 未发现 whitespace 错误。
- 按需展开可能配置接入后，后端定向测试 `python -m pytest app\tests\test_estimate_service.py app\tests\test_candidate_generation.py app\tests\test_observation_api.py -q`：`14 passed`。
- 按需展开可能配置接入后，后端 Ruff `python -m ruff check app` 通过。
- 按需展开可能配置接入后，前端 `npm.cmd run typecheck` 和 `npm.cmd run build` 通过。
- 按需展开可能配置接入后，相关后端/前端/文档文件 mojibake 扫描通过，`git diff --check` 未发现 whitespace 错误。
- 前端 `npm.cmd run typecheck` 通过。
- 前端结束回合接入后，`npm.cmd run typecheck` 通过，`BattleWorkbenchPage.tsx` 编码扫描通过。
- 前端 `npm.cmd run build` 通过。
- 后端阶段 D 新增测试 `python -m pytest app/tests/test_effect_operation_executor.py -q`：`9 passed`。
- 后端阶段 E 聚焦测试 `python -m pytest app/tests/test_modifier_resolver.py app/tests/test_rule_resolver.py app/tests/test_rocom_cleaner_defense_rules.py app/tests/test_starfall_damage_calculator.py -q`：`15 passed`。
- rocom cleaned 重新生成与导入已验证：`python -m app.data_pipeline.rocom.cleaner --raw-json ../data/rocom/raw/sprites_raw.json --image-urls-json ../data/rocom/raw/image_urls.json --output-dir ../data/rocom/cleaned` 生成 469 个技能且无 warning；`python -m app.data_pipeline.rocom.importer --cleaned-dir ../data/rocom/cleaned` dry-run 后再 `--commit` 写入本地 DB；星陨技能操作 seed dry-run 后 commit，最终保留 10 个结构化星陨技能操作。
- 后端全量测试 `python -m pytest -q`：`60 passed`，仍有 FastAPI `on_event` deprecation warnings。
- 后端全量 Ruff `python -m ruff check app` 通过。

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

1. 完善前端伤害后/切换后反馈，展示自动结算了哪些状态、跳过了哪些状态、为什么跳过。
2. 继续推进阶段 E：扩展天气/状态 modifier、更多结构化防御技能规则和完整应对/防御独立结算层。
3. 扩展实时面板估计反向推导：把当前普通攻击最小公式的 HP/双防/双攻低置信范围，继续扩展到应对、减伤、天气、状态上下文和速度先后手约束。
4. 继续推进前端实时估计面板：按需展开已接入，下一步补展开结果的约束解释、未命中原因和模式差异展示。
5. 实现事件重放重算，使实时面板估计可从事件流重建；随后删除旧候选表和未挂载旧接口。

## 当前推进路线记录

后续围绕“通过计算解释伤害，并用观测伤害倒推敌方配置”的核心目标推进：

1. 先修基础一致性：统一状态分类枚举和叠层规则取值，避免状态导入后行为不一致。
2. 设计状态定义数据源格式，提供 dry-run 导入 `effect_definition` 的能力。
3. 先补 P0 状态定义：灼烧、中毒、寄生、冻结、棘刺印记、中毒印记、星陨印记，以及必要天气。
4. 实现状态伤害计算：灼烧、中毒、寄生、冻结阈值、棘刺。
5. 实现星陨伤害计算：触发技能只负责判定和选择物攻/魔攻分支，实际伤害按幻系计算克制/抵抗。
6. 规则可审阅接口、状态实例挂载校验、最小结束回合接口和阶段 C 自动结算已落地。
7. 自动结算稳定后，`EffectOperationExecutor` 已完成阶段 D；`ModifierResolver` / `ResponseResolver` 已有阶段 E 最小闭环，后续补完整应对/防御独立结算层。
8. 计算稳定后继续收敛实时面板估计主流程：Observation 默认更新属性约束和估计 evidence，旧候选生成不再作为业务方案，只保留待删除遗留代码。
