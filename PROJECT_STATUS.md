# 当前项目状态

更新日期：2026-06-12

## 总体阶段

项目已经从“后端骨架”推进到 **前后端可联调的手动输入 MVP + 实时面板反推主流程阶段**。

当前核心目标是：在保持本地规则库、己方配置、战斗事件和状态快照稳定的基础上，继续巩固“实时面板估计 + 默认配置校验”的新反推方式，并补齐天气/状态公式修正、完整应对/防御结算、速度判断和完整战斗状态重放。后端 MVP 完成路线已记录在 `docs/03_系统设计/后端MVP完成路线_v0.1.md`。旧候选接口、旧候选 service/schema/model/tests 已清理，`build_candidate` / `calculation_cache` 由 Alembic `0006_drop_legacy_candidate_tables` 删除。

## 已完成内容

### 后端

- 已建立 FastAPI 应用入口和 API v1 路由聚合。
- 已建立 SQLAlchemy ORM 模型，覆盖静态规则、己方配置、战斗运行时、实时估计、状态实例、快照和事件日志；旧候选表模型已删除。
- 已建立 Alembic 迁移：
  - `0001_initial_schema.py`
  - `0002_event_correction_resource_mvp.py`
  - `0003_team_presets.py`
  - `0004_enemy_panel_estimates.py`
  - `0005_relax_estimate_evidence_source.py`
  - `0006_drop_legacy_candidate_tables.py`
- 已建立 SQLite PRAGMA 初始化：foreign_keys、WAL、synchronous、busy_timeout。
- 已实现静态规则查询接口：精灵、技能、性格、状态定义；技能接口新增 `GET /skills/review` 审阅队列和 `PUT /skills/{skill_id}/rules` 人工维护入口，可保存明确规则或标记模糊/待确认。
- 已实现己方配置管理接口：创建、查询、更新、技能替换、软删除。
- 已实现配队预设接口：可保存己方 6 配置配队和敌方热门精灵阵容，支持查询、更新和软删除；新增 Alembic 迁移 `0003_team_presets.py`。
- 已实现战斗流程接口：创建、列表、详情、阵容录入、开始、切换、结束、归档、状态查询。
- 已实现事件接口：通用事件、伤害事件、资源事件、时间线、作废、修正；重放接口已可重建实时估计/evidence，并重算基础运行时状态（切换、HP、能量）。
- 已实现状态实例接口：施加、移除、切换清除/保留。
- 已实现状态快照服务。
- 旧敌方候选生成、候选摘要/详情/分页代码和 `/candidates/*` 已从当前代码中删除；主流程只维护实时面板估计。
- 已实现 Observation API：支持伤害值、扣血百分比、技能出现、速度先后手等观测写入实时估计 evidence 和属性约束。
- 已实现普通攻击最小伤害计算、P0 状态伤害计算、星陨伤害计算、伤害观测匹配、`RuleResolver` 雏形、`ModifierResolver` 与 `ResponseResolver` 最小闭环。
- 星陨已按独立公式接入 `DamageCalculator`：触发条件看非幻系攻击技能，伤害按幻系计算克制/抵抗，攻防属性跟随触发技能类别。
- Observation API 的伤害观测上下文已允许通过 payload 指定 `formula_type = status | starfall`；非普通攻击最小公式会先记录 unknown，后续纳入状态/天气新反推规则。
- 阶段 A 已完成：`EffectDefinitionOut` 已扩展完整审阅字段，effect importer 已新增 `--status` 只读状态查询，前端类型和接口文档已同步。
- 阶段 B 已开始：`EffectService.apply_effect` 按 `EffectDefinition.owner_scope` 归一化状态挂载目标，避免星陨、天气等状态被挂错位置。
- 阶段 C 最小闭环已完成：`turns/end` 已接入灼烧、中毒、中毒印记、寄生、冻结阈值和暴风雪施加冻结；伤害事件后已接入星陨；切换入场已接入棘刺。自动结算会生成系统事件、资源变化、必要的状态变化和快照，敌方受击伤害会写入实时估计 evidence。
- 阶段 D 已完成：已新增 `EffectOperationExecutor` 并接入 `skill_use`；后端已提供专用 `POST /battles/{battle_id}/skill-events` 入口，支持 `apply_effect`、`add_layers`、`dynamic_apply_effect`、`remove_effect`、`clear_effects`、`change_weather`、`resource_change`、`multiply_layers` 和 `conditional_branch`。星陨相关技能规则已整理为 `backend/app/seed/starfall_skill_operations_p0.json`，基础技能操作规则已整理为 `backend/app/seed/basic_skill_operations_p0.json`；当前本地库已 commit 星陨技能操作，以及落雨、冬至、力量增效 3 个基础技能操作。
- 阶段 E 已进入最小闭环：`ModifierResolver` 可解析 payload、`defense_skill_id`、历史快照状态中的结构化减伤来源、雨天天气倍率、暴风雪天气识别和力量增效这类基础物攻增益；`ResponseResolver` 可解析应对倍率，并在应对成功未知时只记录 unknown；手动伤害事件已可把 `defense_skill_id` 与 `response_attack_success` / `response_defense_success` / `response_status_success` 写入事件 payload、公式上下文和 observation payload；同回合已记录的防御技能事件会自动成为该防御方下一次受击伤害的防御/应对上下文，默认只自动消费一次；攻击技能自身 `damage_rule_json.response_rule` 已可自动装载，支持应对状态成功时写入 `power_multiplier`；伤害事件新增 `condition_flags`，可承载先后手、目标切换、本次击败等通用条件，并自动推断同回合切换条件；rocom cleaner 可从 raw/cleaned 技能定义中提取稳定的“减伤 X% / 应对目标”、基础天气切换和力量增效规则，正式运行以入库后的 `skill_definition` 为准。规则库已提供技能规则人工维护入口，便于逐条补齐当前数据库技能的应对和延伸效果；2026-06-11 已完成 cleaned 技能前 190 条人工审阅入库，并记录结构缺口。
- 核心默认战斗规则已补齐：后端启动时幂等写入通用技能“聚能”（状态技能、能耗 0、获得 5 能量），阵容录入后的双方精灵初始能量为 10，精灵可学技能查询会虚拟包含该默认技能。
- 技能槽运行时基础已接入：`skill_use` 会确保已确认技能拥有 `BattleSkillSlot`，扣能优先使用 `current_energy_cost` 覆盖值并在事件 payload 回写 `skill_runtime`；`RuleResolver` 会读取 `current_power` 作为伤害威力覆盖。`future_hooks` 仍默认保留为 `reserved`，只有显式标记 `status="executable"` 的简单技能槽费用/威力修正才会执行。
- 战斗状态接口已补充技能槽、性格和理论伤害展示字段：`/battles/{battle_id}/state` 的 `elves` 会返回当前可用性格与有效六维面板来源，`skill_slots` 会返回技能名称、属性、类别、基础威力、有效费用、`power_preview` 和 `damage_preview`。`damage_preview` 由后端复用 `RuleResolver` 与 `DamageCalculator`，按当前真实/估计面板、状态、技能规则、本系、克制抵抗、天气和应对分支等上下文计算理论伤害。敌方技能开局未知；`skill_use` 和已确认技能的伤害事件都会把敌方新技能记录为运行时技能槽，供工作台展示其对我方的理论伤害。
- 战斗状态接口已新增精简速度观察 `speed_preview`：不做速度反推或先手硬判断，只把我方当前上场速度与敌方当前/全队的推定配置、未加速性格 + 速度资质 10、加速性格 + 速度资质 10 做直观对比，并计入当前已结构化的速度 flat 状态修正。
- Observation 伤害 payload 已标准化为 `observation_payload_v1` 并保留旧平铺字段兼容；Observation、手动伤害事件和自动结算伤害现在默认只更新实时估计。
- 已完成“实时面板估计 + 默认配置校验”落地，并补齐阶段 F 解释增强：敌方精灵会创建估计档案，可查询估计、设置默认配置并计算默认展示面板；默认配置按种族值启发式选择性格和生命/主攻/速度资质；Observation 会同步写入受影响属性、unknown factors，并在普通攻击最小公式上下文完整时写入低置信 HP/攻防范围；整数剩余百分比模式已支持反推出可用 HP 区间。evidence 已返回来源事件、快照 ID、公式输入缺项、关键倍率、约束变化、天气/状态 modifier 概览、未收窄原因和冲突摘要；前端默认配置选择直接使用实时约束，并能展示这些解释内容；保存时由后端按当前约束校验完整面板；`EventReplayService` 可从非作废事件流重建实时估计/evidence，并重算切换、HP、能量、最终状态实例和事件后快照链。复杂公式、完整天气/状态规则和自动结算副作用重演尚未接入。
- 已实现 BWIKI 数据管线：爬取、清洗、dry-run、导入；新版本支持当前 BWIKI 精灵/技能页面、技能图鉴权威覆盖、全量刷新和缺六维线上空页保护。
- 已实现管理接口：远程检查、远程同步、本地 cleaned JSON 导入、任务查询。
- 已实现归档战斗物理清理管理接口，支持 dry-run。

### 前端

- 已建立 React + TypeScript + Vite 前端。
- 已实现页面：战斗首页、己方配置、准备阶段、战斗工作台、事件日志、规则库、设置/数据管理。
- 已封装主要后端 API。
- 已接入 health 检测、战斗列表、战斗归档、己方配置 CRUD、规则库查询和技能规则人工维护。
- 已接入己方配置页配队管理，可把 6 个已保存配置组合为己方配队，也可录入敌方热门阵容。
- 已接入准备阶段阵容录入、配队快速填充和开始战斗；准备阶段已合并为“提交阵容并进入战斗”单按钮流程，提交阵容时同步初始化敌方实时估计。
- 已接入战斗工作台快捷录入：伤害、资源、状态、切换。
- 战斗工作台已接入 `turns/end`：可从顶部或快捷录入区结束当前回合，刷新状态、时间线与实时估计信息，并展示最近一次自动结算摘要。
- 战斗工作台已接入专用 `skill-events` 录入：可测试已入库 `effect_operations_json` 的状态、天气和资源操作。
- 战斗工作台已接入通用条件标记和技能槽运行时展示：技能/伤害录入可勾选应对成功、先后手、目标本回合切换、本次击败等条件；当前对位面板可显示上场精灵技能槽的运行时费用、威力和冷却，最近技能/伤害反馈会展示 `skill_runtime`、攻击技能应对分支和条件 flags。
- 战斗工作台当前对位面板已改为：我方固定展示 4 个携带技能槽，并提供第 5 个本地临时技能槽；敌方同样展示 4 个主槽和 1 个额外技能输入，开局主槽显示“未知”，每次确认敌方使用新技能后自动填入对应运行时技能槽。技能卡会展示技能名、属性、类别、费用、基础威力，以及对当前对位目标的理论伤害和生命百分比，展开后可查看对方全队的理论伤害。
- 战斗工作台当前对位卡片已新增可展开的“速度观察”区域，默认折叠，只在展开后显示当前敌方和敌方全队的速度档位对比。
- 已接入实时面板估计、默认配置编辑、默认面板、估计 evidence 解释、实时推导范围、unknown factors、按约束限制默认性格选择、当前对位展示精灵性格、事件作废/通用修正、估计层重放入口和快照详情展示，方便测试普通攻击、状态/星陨、技能结构化操作和应对/防御上下文对实时估计的影响。战斗工作台现在会展示最近技能事件的结构化操作执行结果，estimate evidence 会把天气倍率、能力等级和减伤来源翻译为可读说明。
- 已接入 rocom 数据更新管理入口和归档战斗清理入口。

### 数据

- 本地 cleaned 数据已包含：
  - 精灵：469
  - 技能：496
  - 精灵可学习技能：22188
  - 属性克制规则：113
- 本地数据库已有真实 rocom 静态数据，当前活跃 rocom 精灵/技能已刷新到 `rocom_bwiki_20260609` 版本；数据库中活跃精灵 469 个、技能 497 个（含核心默认技能 1 个）、精灵可学习技能 22387 条、属性克制规则 113 条。线上详情页缺六维的 4 个精灵保留旧版本有效数据和旧 BWIKI 技能关系，避免空页面覆盖面板反推基础数据。
- 30 种性格已拆为正式核心规则，后端启动时会幂等自检查并写入/修正。
- P0 状态定义已可通过 `backend/app/seed/effect_definitions_p0.json` 和 effect importer 写入；当前工作库已导入 11 条 P0 状态定义，其中新增 `effect_physical_attack_up_100` 支撑力量增效。技能人工审阅、机制补齐和确认印记/蓄力时序机制额外补入 57 条属性/速度/技能层数/印记/行动修正状态，当前 active `effect_definition` 共 68 条。
- 技能人工审阅已完成 cleaned 全量 496 条：第一批 `backend/app/seed/manual_skill_rule_reviews_batch_20260611.json` 覆盖 cleaned 技能前 40 条；第二批 `backend/app/seed/manual_skill_rule_reviews_batch_20260611_02.json` 覆盖第 41-90 条；第三批 `backend/app/seed/manual_skill_rule_reviews_batch_20260611_03.json` 覆盖第 91-190 条；第四批 `backend/app/seed/manual_skill_rule_reviews_batch_20260612.json` 覆盖第 191-290 条；第五批 `backend/app/seed/manual_skill_rule_reviews_batch_20260612_02.json` 覆盖第 291-390 条；第六批 `backend/app/seed/manual_skill_rule_reviews_batch_20260612_03.json` 覆盖第 391-490 条；收尾批 `backend/app/seed/manual_skill_rule_reviews_batch_20260612_04.json` 覆盖第 491-496 条。结构缺口和后续方案记录在 `docs/03_系统设计/技能规则人工审阅记录_v0.1.md`。

## 当前未完成内容

- 完整真实伤害体系尚未全部实现：当前已有普通攻击最小公式、P0 状态伤害、星陨、阶段 C 自动结算、阶段 D 技能效果操作和阶段 E 最小减伤/应对解析；复杂公式分支、天气/状态 modifier、完整应对/防御独立结算仍需补齐。
- 技能逐条审阅已完成，但机制缺口仍需逐类落地：当前已有审阅队列、人工维护入口和 `GET /skills/capability-audit` 能力审计接口，明确规则可写入 `damage_rule_json` / `hit_rule_json` / `effect_operations_json`，模糊技能只标记 `needs_review` / `ambiguous` 和备注，不进入计算链。湿润/光合/攻击/降灵/蓄势/减速/龙噬等已确认印记、萌化记录、萌化印记属性增益加层、基础迸发窗口/记录、蓄力最小状态机和返场后端语义已先落地；后续重点是迸发历史继承、蓄力高级分支、传动/槽位、迅捷、动态威力公式、萌化面板回退、风起先手自动判定、脱离/打断事件流等机制的统一方案；统筹清单见 `docs/03_系统设计/技能机制缺口统筹_v0.1.md`，审计清单见 `docs/03_系统设计/技能规则执行能力审计_v0.1.md`。
- 实时面板估计仍处在第一阶段：已有估计档案、自动默认配置、默认配置展示接口、Observation evidence 写入、阶段 F evidence 解释增强、普通攻击最小公式反向约束、整数 HP 百分比反推、默认配置校验、可选性格约束、前端主面板切换和 `EventReplayService` 最小闭环；复杂公式、完整天气/状态 modifier 规则、速度概率和自动结算副作用重演尚未接入。
- 旧候选空间方案已从业务和代码中删除；后续开发不再新增候选空间落库筛选逻辑。
- 速度先手概率未实现；当前只有基础面板速度观测匹配。
- 事件重放重算已完成最小闭环：`replay-from` 会重建实时估计/evidence，并重算切换、HP、能量、最终状态实例和事件后快照链；自动结算副作用重演仍未实现。
- 实时估计 evidence 已有阶段 F 解释页，可展示事件来源、快照、关键倍率、约束变化、未收窄原因和冲突摘要；后续还需补全复杂技能规则和更多天气/状态 modifier 数值来源。
- 图像识别未开始。
- 正式 `effect_definition` 状态定义数据仍需继续扩展；P0 状态定义和前三批人工属性/速度状态已有 JSON 种子、dry-run 导入器和本地 commit 验证，但不会在普通启动时自动写入。攻击印记、光合印记、萌芽、湿润、蓄电、奉献、传动等机制仍待确认。

## 当前验证情况

最近进度文档记录的验证结果：

- 默认配置校验接入后，后端 Ruff、前端 typecheck/build、相关中文文件 mojibake 扫描和 `git diff --check` 曾通过。
- 前端 `npm.cmd run typecheck` 通过。
- 前端结束回合接入后，`npm.cmd run typecheck` 通过，`BattleWorkbenchPage.tsx` 编码扫描通过。
- 前端 `npm.cmd run build` 通过。
- 后端阶段 D 新增测试 `python -m pytest app/tests/test_effect_operation_executor.py -q`：`9 passed`。
- 后端阶段 E 聚焦测试 `python -m pytest app/tests/test_modifier_resolver.py app/tests/test_rule_resolver.py app/tests/test_rocom_cleaner_defense_rules.py app/tests/test_starfall_damage_calculator.py -q`：`15 passed`。
- rocom cleaned 重新生成与导入已验证：`python -m app.data_pipeline.rocom.cleaner --raw-json ../data/rocom/raw/sprites_raw.json --image-urls-json ../data/rocom/raw/image_urls.json --output-dir ../data/rocom/cleaned` 生成 469 个技能且无 warning；`python -m app.data_pipeline.rocom.importer --cleaned-dir ../data/rocom/cleaned` dry-run 后再 `--commit` 写入本地 DB；星陨技能操作 seed dry-run 后 commit，最终保留 10 个结构化星陨技能操作。
- 后端全量测试 `python -m pytest -q`：`60 passed`，仍有 FastAPI `on_event` deprecation warnings。
- 后端全量 Ruff `python -m ruff check app` 通过。
- BWIKI 2026-06-09 全量重爬与导入已验证：爬虫获取 469 条精灵、496 条技能图鉴记录；cleaned 输出 469 个精灵、496 个技能、22188 条精灵可学习技能、113 条属性克制规则。导入前 dry-run 摘要与正式 commit 摘要一致：新增 28 个精灵、更新 437 个精灵、跳过 4 个缺六维线上空页、创建 27 个技能、更新 469 个技能，并保留 199 条缺六维精灵旧 BWIKI 技能关系。此前旧候选存量数据已清空并 VACUUM，数据库从约 1.33GB 回收到约 6.1MB；本轮 0006 迁移负责删除旧表结构。
- 本轮数据管线重构和数据库刷新后，后端全量测试 `python -m pytest -q`：`108 passed`，仍有 FastAPI `on_event` deprecation warnings；后端 Ruff、前端 typecheck/build、相关中文文件 mojibake 扫描和 `git diff --check` 均通过。
- 2026-06-10 最终解耦清理后，后端全量测试 `python -m pytest -q`：`89 passed`，仍有 FastAPI `on_event` deprecation warnings；`python -m ruff check app`、前端 `npm.cmd run typecheck`、`npm.cmd run build`、本轮改动范围 mojibake 扫描和 `git diff --check` 均通过。旧候选模块名、旧观察字段和旧硬筛选字段扫描未发现后端/前端残留；当前工作库执行 Alembic 到 `0006_drop_legacy_candidate_tables` 后，`build_candidate` / `calculation_cache` 表不存在。
- 2026-06-10 继续完善 `EventReplayService` 后，`replay-from` 已可按非作废事件流重建最终状态实例，并为每个非作废事件重新生成事件后快照、回填 `BattleEvent.snapshot_id`，旧绑定快照会软删除以避免重复重放堆积；后端全量测试 `python -m pytest -q`：`89 passed`，仍有 FastAPI `on_event` deprecation warnings；`python -m ruff check app` 和前端 `npm.cmd run build` 均通过。
- 2026-06-10 完成实时估计解释与天气/状态 modifier 最小闭环后，estimate evidence 已返回 `explanation`，前端可展示公式输入缺项、快照状态数量、天气/状态未映射提示和 unknown factors；后端全量测试 `python -m pytest -q`：`90 passed`，仍有 FastAPI `on_event` deprecation warnings；`python -m ruff check app` 和前端 `npm.cmd run build` 均通过。
- 2026-06-10 补齐基础天气/状态规则后，`ModifierResolver` 已可从快照解析雨天水系 1.75 天气倍率、识别暴风雪无直接攻击增伤、解析力量增效物攻+100% 能力等级；rocom cleaner 已可把落雨、冬至、力量增效清洗为结构化 `effect_operations_json`，本地库已通过 dry-run 后 commit 相关 effect/skill operation 数据。聚焦测试 `python -m pytest app/tests/test_modifier_resolver.py app/tests/test_rocom_cleaner_defense_rules.py app/tests/test_estimate_service.py -q`：`23 passed`。
- 2026-06-11 完成阶段 F evidence 解释增强后，`EnemyPanelEstimateEvidence.explanation` 已包含来源事件、快照 ID、公式关键倍率、约束变化、未收窄原因和冲突摘要，前端实时估计面板已展示这些内容。聚焦验证：`python -m pytest app/tests/test_estimate_service.py -q`：`12 passed`；`python -m ruff check app/services/estimate_service.py app/tests/test_estimate_service.py` 通过；前端 `npm.cmd run typecheck` 通过。
- 2026-06-11 新增技能规则人工维护入口后，后端 `GET /skills/review` 可按审阅状态列出技能，`PUT /skills/{skill_id}/rules` 可保存明确结构化规则或仅标记模糊/待确认；前端规则库技能页已接入 JSON 编辑器。聚焦验证：`python -m pytest app/tests/test_skill_rules_api.py -q`：`3 passed`；`python -m ruff check app/api/v1/endpoints/skills.py app/schemas/static.py app/tests/test_skill_rules_api.py` 通过；前端 `npm.cmd run typecheck` 通过。
- 2026-06-11 完成技能逐条审阅第一批后，新增技能审阅批次导入器，默认 dry-run、显式 `--commit` 写库；本地库已 commit 6 条人工属性/速度状态定义和 40 条技能审阅结果。导入 dry-run 与 commit 摘要一致：状态定义新增 6 条；技能更新 40 条，状态分布为 20 structured、10 partial、9 needs_review、1 ambiguous。聚焦验证：`python -m pytest app/tests/test_skill_rule_review_importer.py app/tests/test_skill_rules_api.py app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py -q`：`23 passed`；`python -m ruff check app/data_pipeline/skill_rule_reviews/importer.py app/tests/test_skill_rule_review_importer.py` 通过；回读 `python -m app.data_pipeline.effects.importer --status --skip-init-db` 显示 active effect_definition 共 17 条。
- 2026-06-11 完成技能逐条审阅第二批后，导入器支持把 `future_hooks` 写入 `manual_review` 元信息，给体重公式、奉献、变形、复制等暂不实现机制保留接口但不进入执行链；本地库已 commit 6 条新属性/速度状态定义和第 41-90 条技能审阅结果。导入 dry-run 与 commit 摘要一致：状态定义新增 6 条；技能更新 50 条，状态分布为 18 structured、22 partial、10 needs_review。聚焦验证：`python -m pytest app/tests/test_skill_rule_review_importer.py app/tests/test_skill_rules_api.py app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py -q`：`23 passed`；`python -m ruff check app` 通过；后端全量测试最终 `python -m pytest -q`：`107 passed`，仍有 16 个 FastAPI `on_event` deprecation warnings。第一次全量测试曾出现一次同回合防御消费测试未通过，单测复跑和全量复跑均通过，暂按时间戳排序相关间歇风险记录。
- 2026-06-11 完成技能逐条审阅第三批后，本地库已 commit 6 条新属性/速度状态定义和第 91-190 条技能审阅结果。导入 dry-run 与 commit 摘要一致：状态定义新增 6 条；技能更新 100 条，状态分布为 40 structured、47 partial、13 needs_review。新增保留接口覆盖动态天气系别、按印记层数修正威力/费用、蓄力受击监听、携带技能组分支、生命比例交换、按增益极性驱散、减免转治疗等。聚焦验证：`python -m pytest app/tests/test_skill_rule_review_importer.py app/tests/test_skill_rules_api.py app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py -q`：`23 passed`；`python -m ruff check app` 通过；后端全量测试 `python -m pytest -q`：`107 passed`，仍有 16 个 FastAPI `on_event` deprecation warnings；本轮中文文件 mojibake 扫描通过。
- 2026-06-11 完成第一优先级机制补齐后，攻击技能 `response_rule` 可自动装载，技能槽运行时费用/威力覆盖接入，伤害事件 `condition_flags` 与同回合切换条件推断已同步到前后端。聚焦验证：`python -m pytest app/tests/test_rule_resolver.py app/tests/test_core_default_skill.py app/tests/test_damage_event_service_real_case.py -q`：`17 passed`；`python -m ruff check app/calculation/response_resolver.py app/calculation/rule_resolver.py app/services/battle_service.py app/services/damage_event_service.py app/schemas/event.py app/schemas/battle.py app/tests/test_rule_resolver.py app/tests/test_core_default_skill.py app/tests/test_damage_event_service_real_case.py` 通过；前端 `npm.cmd run typecheck` 和 `npm.cmd run build` 通过。
- 2026-06-11 完成工作台性格与理论伤害预览后，`/battles/{battle_id}/state` 已返回精灵当前性格、有效六维面板来源和技能 `damage_preview`；前端当前对位技能卡会展示对当前敌方的理论伤害/百分比，并可展开查看敌方场下全队。验证：`python -m pytest app/tests/test_core_default_skill.py -q`：`5 passed`；`python -m pytest -q`：`112 passed`，仍有 16 个 FastAPI `on_event` deprecation warnings；`python -m ruff check app` 通过；前端 `npm.cmd run typecheck` 和 `npm.cmd run build` 通过；本轮改动文件 mojibake 扫描和 `git diff --check` 通过。
- 2026-06-12 补齐敌方技能发现链路后，敌方 `skill_use` 和带 `skill_confirmed=true` 的伤害事件都会把新技能写入运行时技能槽；工作台敌方对位区域改为 4 个“未知”主槽 + 1 个额外技能输入，确认技能后显示该技能对我方的理论伤害。验证：`python -m pytest app/tests/test_core_default_skill.py -q`：`5 passed`；`python -m pytest -q`：`112 passed`，仍有 16 个 FastAPI `on_event` deprecation warnings；`python -m ruff check app` 通过；前端 `npm.cmd run build` 通过；本轮改动文件 mojibake 扫描和 `git diff --check` 通过。
- 2026-06-12 完成技能逐条审阅第四批后，本地库已 commit 6 条新属性修正状态定义和第 191-290 条技能审阅结果。导入 dry-run 与 commit 摘要一致：状态定义新增 6 条；技能更新 100 条，状态分布为 53 structured、33 partial、14 needs_review。新增保留接口覆盖吸血按伤害治疗、连击数修正、技能槽位置/交换、按生命/费用/力竭数量修正威力、换宠锁定、按极性/层数清除或转换状态、萌化/湿润等未确认状态。聚焦验证：`python -m pytest app/tests/test_skill_rule_review_importer.py app/tests/test_skill_rules_api.py app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py -q`：`23 passed`；`python -m ruff check app/data_pipeline/skill_rule_reviews/importer.py app/data_pipeline/effects/importer.py app/tests/test_skill_rule_review_importer.py` 通过；回读 `python -m app.data_pipeline.effects.importer --status --skip-init-db` 显示 active effect_definition 共 35 条。
- 2026-06-12 完成技能逐条审阅第五批和机制状态补齐后，本地库已 commit 机制/层数状态定义和第 291-390 条技能审阅结果。导入 dry-run 与 commit 摘要一致：状态定义累计 active 55 条；技能更新 100 条，状态分布为 48 structured、44 partial、8 needs_review。聚焦验证：`python -m pytest app/tests/test_skill_rule_review_importer.py app/tests/test_skill_rules_api.py app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py -q`：`29 passed`；`python -m ruff check app` 通过；本轮中文文件 mojibake 扫描和 `git diff --check` 通过。
- 2026-06-12 完成技能逐条审阅第六批后，本地库已 commit 第 391-490 条技能审阅结果。导入 dry-run 与 commit 摘要一致：技能更新 100 条，状态分布为 49 structured、36 partial、15 needs_review；未新增状态定义，active effect_definition 仍为 55 条。聚焦验证：`python -m pytest app/tests/test_skill_rule_review_importer.py app/tests/test_skill_rules_api.py app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py app/tests/test_core_default_skill.py -q`：`34 passed`；`python -m ruff check app` 通过；本轮改动文件 mojibake 扫描和 `git diff --check` 通过。
- 2026-06-12 完成技能逐条审阅收尾批后，本地库已 commit 第 491-496 条技能审阅结果。导入 dry-run 与 commit 摘要一致：技能更新 6 条，状态分布为 3 structured、2 partial、1 needs_review；全量 cleaned 技能 496 条累计状态为 231 structured、194 partial、70 needs_review、1 ambiguous。新增缺口主要是龙噬印记和蓄力/下次无需蓄力。
- 2026-06-12 阅读 `docs/03_系统设计/技能机制缺口回应.txt` 后，完成确认印记/萌化机制首批落地：新增 `manual_skill_effect_definitions_confirmed_marks_20260612.json` 11 条状态定义，并用 `manual_skill_rule_reviews_confirmed_marks_20260612.json` 更新 17 条技能规则；后端新增按层数百分比技能修正、回合末/入场资源变化、龙噬印记 3 能耗技能触发双攻增益。追加确认后又新增 `manual_skill_effect_definitions_confirmed_timing_20260612.json` 2 条行动状态，落地萌化印记属性增益 +1 层、初始首发/返场迸发窗口与具体效果记录、蓄力第一次扣能和同技能释放、返场后端语义。仍保留迸发历史继承、蓄力受击/可用防御技能高级分支、风起先手自动判定、萌化面板回退、迅捷、传动、脱离/打断和特殊动态公式。

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
2. 继续推进阶段 G：逐条审阅已收尾，下一步回到高优先级结构缺口（萌化、减速/降灵/风起/龙噬印记、迅捷/先手、蓄力、迸发历史、传动/槽位）确认与落地。
3. 扩展实时面板估计反向推导：把当前普通攻击最小公式的 HP/双防/双攻低置信范围，继续扩展到应对、减伤、天气、状态上下文和速度先后手约束。
4. 继续推进前端实时估计面板：补充重放结果提示，以及更多复杂规则未命中原因展示。
5. 在 `EventReplayService` 当前闭环基础上，继续覆盖自动结算副作用重演。

## 当前推进路线记录

后续围绕“通过计算解释伤害，并用观测伤害倒推敌方配置”的核心目标推进：

1. 先修基础一致性：统一状态分类枚举和叠层规则取值，避免状态导入后行为不一致。
2. 设计状态定义数据源格式，提供 dry-run 导入 `effect_definition` 的能力。
3. 先补 P0 状态定义：灼烧、中毒、寄生、冻结、棘刺印记、中毒印记、星陨印记，以及必要天气。
4. 实现状态伤害计算：灼烧、中毒、寄生、冻结阈值、棘刺。
5. 实现星陨伤害计算：触发技能只负责判定和选择物攻/魔攻分支，实际伤害按幻系计算克制/抵抗。
6. 规则可审阅接口、状态实例挂载校验、最小结束回合接口和阶段 C 自动结算已落地。
7. 自动结算稳定后，`EffectOperationExecutor` 已完成阶段 D；`ModifierResolver` / `ResponseResolver` 已有阶段 E 最小闭环，后续补完整应对/防御独立结算层。
8. 计算稳定后继续收敛实时面板估计主流程：Observation 默认更新属性约束和估计 evidence，不再回到旧候选空间落库筛选。

- 2026-06-12 完成状态层数/吸血/锁定机制补齐后，新增手动指定消层、按极性驱散/翻倍、吸血向下取整、状态型技能威力/连击/能耗层数修正和换宠锁定冲突提示。验证：机制状态定义 seed dry-run 通过；`python -m pytest app/tests/test_effect_operation_executor.py app/tests/test_modifier_resolver.py app/tests/test_core_default_skill.py -q`：`29 passed`；后端全量 `python -m pytest -q`：`118 passed`，仍有 16 个 FastAPI `on_event` deprecation warnings；`python -m ruff check app`、前端 `npm.cmd run build`、本轮改动文件 mojibake 扫描和 `git diff --check` 均通过。
- 2026-06-12 完成技能逐条审阅第六批后，`backend/app/seed/manual_skill_rule_reviews_batch_20260612_03.json` 已覆盖 cleaned 技能第 391-490 条并 commit 到本地库：100 条技能中 `structured` 49 条、`partial` 36 条、`needs_review` 15 条。新增记录的缺口包括迸发历史、传动/槽位、迅捷/先手、蓄力、返场/脱离、动态威力公式、萌化/减速/降灵/风起印记等；体重公式、奉献、变形/复制仍按要求只保留 future hook。
- 2026-06-12 完成技能逐条审阅收尾批后，`backend/app/seed/manual_skill_rule_reviews_batch_20260612_04.json` 已覆盖 cleaned 技能第 491-496 条并 commit 到本地库；全量 cleaned 技能 496 条审阅完成，累计 `structured` 231 条、`partial` 194 条、`needs_review` 70 条、`ambiguous` 1 条。后续进入机制缺口统筹与逐类落地阶段。

- 2026-06-12 新增运行时有效形态/退化手动处理：前后端提供 `runtime-form` 调整入口，原始精灵身份保持不变，保留性格与六维培养并按所选有效形态种族值重算面板；伤害预览、本系与属性读取已改为使用有效形态。该操作不会触发普通切换、返场、入场结算或首回合机制。
