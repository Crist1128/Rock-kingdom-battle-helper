# Rock PVP Helper

洛克王国世界 PVP 战斗信息获取与敌方配置推算系统。

当前仓库阶段：**前后端可联调的纯手动输入 MVP 已成型，并已把敌方配置推算主流程切到实时面板估计；Observation、手动伤害事件和自动结算伤害都会写入估计 evidence。项目已接入真实样本校正后的 PVP 面板公式、普通攻击最小公式反向约束、普通攻击伤害、P0 状态伤害、星陨计算、阶段 C 自动结算、阶段 D 技能效果操作执行器、RuleResolver 雏形、阶段 E 的 ModifierResolver/ResponseResolver 最小闭环和 `EventReplayService` 状态实例/事件后快照链重建闭环；下一阶段继续补齐天气/状态 modifier、完整应对/防御结算和自动结算副作用重演**。

## 当前已具备能力

- 后端：FastAPI + SQLAlchemy 2.x + SQLite + Alembic。
- 前端：React + TypeScript + Vite + TanStack Query + Zustand + Tailwind CSS。
- 本地数据库：默认使用 `data/app.db`。
- 静态规则数据：已接入洛克王国 BWIKI 爬虫、清洗、dry-run、导入流程。
- 已有真实数据：精灵、技能、精灵可学习技能、属性克制规则。
- 手动 MVP：己方配置、战斗创建、阵容录入、首发确认、切换、伤害/资源/状态手动事件、状态快照、时间线、实时估计摘要。
- 面板属性：PVP 个体资质按界面输入值 `×6` 转为有效个体资质；生命与非生命均按已验证的分段四舍五入公式计算，火神、龙息帕尔真实样本已纳入测试。
- 实时面板估计：敌方精灵阵容录入后会创建估计档案，并按种族值启发式自动生成默认性格/资质；可设置默认配置、查看默认面板、接收 Observation evidence，并在普通攻击最小公式上下文完整时写入低置信 HP/攻防范围。阶段 F 已增强 evidence 解释：可展示来源事件、快照 ID、关键倍率、约束变化、未收窄原因、天气/状态 modifier 概览和冲突摘要；整数剩余百分比模式会按显示百分比反推生命区间，例如 76 伤害、100% 到 83% 会推导 HP 为 448 到 474。
- 默认配置校验：玩家可直接选择默认性格和资质，后端保存时按当前实时推导约束校验完整面板。只在已经明确推导出物攻、魔攻或速度时，前端才收紧对应正修性格和资质投入；HP/双防约束只禁用明显冲突的正修性格。旧候选接口、旧候选 service/schema/model 和旧候选专项测试已删除，`build_candidate` / `calculation_cache` 由 Alembic `0006_drop_legacy_candidate_tables` 删除。
- 配队预设：己方配置页可把 6 个已保存己方配置组合为配队，也可录入只包含精灵种类的敌方热门阵容；准备阶段可选择配队快速填充双方阵容。
- 伤害与规则解析：已实现普通攻击最小公式、P0 状态伤害、星陨伤害、伤害观测匹配、`RuleResolver` 雏形、`ModifierResolver` 与 `ResponseResolver` 最小闭环；可解析技能基础信息、本系、属性克制、双属性合并、应对倍率、防御技能减伤、payload 减伤来源、快照状态减伤来源、雨天天气倍率和基础物攻增益状态；手动伤害事件已可把 `defense_skill_id`、应对成功标记和 `condition_flags` 写入事件 payload 和公式上下文，攻击技能自身 `damage_rule_json.response_rule` 可自动装载到公式链。
- 技能规则维护：规则库已提供技能审阅队列、手动录入入口和规则能力审计页，可逐条保存明确的 `damage_rule_json`、`hit_rule_json`、`effect_operations_json`，并检查哪些规则已有执行链、哪些仍只是 `future_hooks` 接口；模糊技能可标记 `needs_review` / `ambiguous` 并保留备注，不写入可执行效果，避免污染公式和候选反推。2026-06-12 已完成 cleaned 技能 496 条人工审阅入库，`future_hooks` 元信息用于保留体重公式、奉献、变形、复制、蓄力高级监听、迸发历史、传动/槽位、按技能组组成分支等未来接口；已先落地萌化印记属性增益加层、基础迸发窗口/记录和蓄力最小状态机。
- 状态定义：已有 P0 状态定义 JSON 种子、dry-run/commit 导入器和 `--status` 只读查询；`/effects` 已返回完整审阅字段。本地库在 P0 之外已补入 18 条人工审阅属性/速度修正状态，用于承载前三批明确技能效果。
- 自动结算：阶段 C 最小闭环已完成，支持回合末灼烧/中毒/中毒印记/寄生/冻结阈值/暴风雪施加冻结，伤害后星陨，切换入场棘刺；敌方受击的自动伤害会进入实时估计 evidence。
- 技能结构化操作：阶段 D 已接入 `EffectOperationExecutor`，`skill_use` 可按 `effect_operations_json` 自动施加/移除/清除状态，切换天气，修改 HP/energy，执行条件分支和层数翻倍；后端已提供专用 `POST /battles/{battle_id}/skill-events` 入口，并已接入 `BattleSkillSlot` 运行时费用/威力覆盖基础，星陨相关技能规则和基础规则（落雨、冬至、力量增效）已有可 dry-run 导入的种子。
- 工作台技能槽：`/battles/{battle_id}/state` 会返回技能槽静态信息、`power_preview` 和后端计算的 `damage_preview`；我方当前对位面板固定展示 4 个携带技能槽，并提供第 5 个本地临时技能槽。敌方技能开局默认显示 4 个“未知”占位和一个额外技能输入；每次录入敌方使用技能或敌方伤害事件确认新技能后，会自动填入对应运行时技能槽，并显示该技能对我方当前上场和场下全队的理论伤害。
- 核心默认战斗规则：后端启动时会幂等补齐通用默认技能“聚能”（`core_skill_focus_energy`），所有精灵运行时初始能量为 10，聚能能耗 0，使用后增加 5 能量。
- 前端联动：战斗工作台伤害录入可同步提交 observation，技能使用可触发已入库的结构化操作，右侧面板已转为实时面板估计，可设置敌方默认配置、查看默认面板、展示属性推导范围、unknown factors、约束变化、关键倍率、未收窄原因和冲突摘要；当前对位会显示精灵性格，并用当前真实/估计六维驱动技能理论伤害展示。工作台已接入结束回合按钮和最近回合结算摘要，事件日志可选择事件、作废/修正/触发估计层重放并查看快照详情。
- 管理功能：规则数据更新入口、归档战斗 dry-run 与物理清理入口。

## 当前明确未完成内容

- 完整真实伤害体系尚未全部实现；当前已有普通攻击最小公式、P0 状态伤害、星陨、阶段 C 自动结算和阶段 E 最小减伤/应对解析，复杂技能分支、天气/状态 modifier、完整应对/防御独立结算仍需补齐。
- cleaned 技能逐条审阅已完成；当前已有审阅队列与手动录入入口，后续重点从“逐条录入”转为“机制缺口统筹落地”，统筹清单见 `docs/03_系统设计/技能机制缺口统筹_v0.1.md`。已依据机制回应先落地湿润/光合/攻击/降灵/蓄势/减速/龙噬等确认印记、萌化状态记录、萌化印记属性增益加层、基础迸发窗口/记录、蓄力最小状态机和返场后端语义；模糊描述不会自动转成规则。
- 实时面板估计已完成第一阶段表结构、后端接口、阵容录入初始化、自动默认配置、Observation 同步 evidence、阶段 F 解释增强、前端主面板切换和 `EventReplayService` 最小闭环：敌方精灵会创建估计档案，可查询当前估计、设置默认配置并计算默认展示面板；Observation 会记录受影响属性、unknown factors、来源事件、快照 ID、关键倍率、约束变化、未收窄原因和冲突摘要，并在普通攻击最小公式上下文完整时写入低置信 HP/攻防范围；保存默认配置时由后端按当前约束校验完整面板；`replay-from` 可重建实时估计/evidence，并重算切换、HP、能量、最终状态实例和事件后快照链。复杂公式、完整天气/状态规则和自动结算副作用重演尚未接入。
- 旧候选配置方案已从项目中清理：`/candidates/*` 不再挂载，旧候选 service/schema/model/tests 已删除，数据库旧表由 Alembic `0006_drop_legacy_candidate_tables` 迁移删除。
- 速度先手概率尚未实现；当前只有基础面板速度观测匹配。
- 事件重放重算已完成最小闭环：实时估计/evidence、切换、HP、能量、最终状态实例和事件后快照链可从非作废事件流重建；自动结算副作用重演仍未实现。
- 图像识别尚未开始。
- 状态定义数据仍需继续扩展；P0 已可导入并在当前工作库验证，后续重点是自动结算覆盖面和技能结构化操作。

## 目录结构

```text
Rock-kingdom-battle-helper/
  backend/                 # FastAPI 后端
    app/
      api/                 # API 路由
      calculation/         # 面板属性、速度、普通攻击伤害、规则解析
      core/                # 配置和枚举
      data_pipeline/       # BWIKI 数据爬取、清洗、导入
      db/                  # 数据库 session、Base、初始化
      inference/           # Observation 类型与 payload 标准化，供实时面板估计使用
      models/              # SQLAlchemy ORM
      schemas/             # Pydantic schemas
      seed/                # 开发/基础种子数据
      services/            # 业务服务
      tests/               # 单元测试
    alembic/               # Alembic 迁移
    PROJECT_PROGRESS_UPDATE.md
  frontend/                # React 前端
    src/
      components/
      lib/
      pages/
      store/
      types/
    PROJECT_PROGRESS_UPDATE.md
  docs/                    # 需求、开发规格、系统设计、接口文档
  data/                    # 本地数据库、爬虫 raw/cleaned 数据，不应提交正式敏感数据
  scripts/                 # 开发脚本
```

## 启动方式

### 一键启动（Windows）

仓库根目录下可直接双击：

```text
scripts/start_dev.cmd
```

它会分别打开两个 CMD 窗口：

- 后端窗口：在 `backend/` 下启动 `uvicorn`
- 前端窗口：在 `frontend/` 下执行 `npm.cmd run dev`

### 后端

```bash
cd backend
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --access-log --log-level info
```

访问：

- OpenAPI: http://127.0.0.1:8001/docs
- 健康检查: http://127.0.0.1:8001/api/v1/health

### 前端

```bash
cd frontend
npm install --no-audit --no-fund
npm run dev
```

前端地址：

```text
http://127.0.0.1:5173
```

PowerShell 如果拦截 `npm.ps1`，可使用：

```bash
npm.cmd run dev
npm.cmd run build
```

## 空库初始化策略

当前空库初始化拆成两类：

1. **数据库结构**：只由 Alembic 负责，执行 `python -m alembic upgrade head`。
2. **核心性格与默认技能规则**：后端启动时会自动幂等自检查并写入/修正 30 种性格，以及通用默认技能“聚能”。

启动自检查只处理 `nature_definition`，不会插入示例精灵、示例技能或示例状态。

精灵、技能、可学习技能和属性克制等外部静态规则，仍通过 rocom 数据管线 dry-run 后再提交写库；后端普通启动不会自动远程爬取或大规模写入这些数据。

## 下一步重点

1. 扩展实时面板估计反向推导：把当前普通攻击最小公式的 HP/双防/双攻低置信范围，继续扩展到应对、减伤、天气、状态上下文和速度先后手约束。
2. 完善默认配置校验和解释能力：展示保存失败时命中的约束、冲突属性和必要的 unknown factors。
3. 继续扩展 `ModifierResolver`：在已接入雨天、暴风雪识别和力量增效的基础上，补更多天气/状态 modifier、快照状态修正与特殊公式。
4. 补完整应对/防御独立结算层，并在 `EventReplayService` 当前闭环基础上实现自动结算副作用重演。
