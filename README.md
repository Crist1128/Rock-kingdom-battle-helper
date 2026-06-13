# Rock PVP Helper

洛克王国世界 PVP 战斗信息获取与敌方配置推算系统。

当前仓库阶段：**前后端可联调的纯手动输入 MVP 已成型，并已把敌方配置推算主流程切到实时面板估计；Observation、手动伤害事件和自动结算伤害都会写入估计 evidence。项目已接入真实样本校正后的 PVP 面板公式、普通攻击最小公式反向约束、普通攻击伤害、P0 状态伤害、星陨计算、阶段 C 自动结算、阶段 D 技能效果操作执行器、RuleResolver 雏形、阶段 E 的 ModifierResolver/ResponseResolver 最小闭环和 `EventReplayService` 状态实例/事件后快照链重建闭环；下一阶段继续补齐天气/状态 modifier、完整应对/防御结算和自动结算副作用重演**。

## 当前已具备能力

- **基础架构**：FastAPI 后端、React/Vite 前端、SQLite + Alembic 本地数据库已可联调运行。
- **静态数据管线**：支持洛克王国世界 BWIKI 数据爬取、清洗、dry-run 和导入；已覆盖精灵、技能、可学习技能、属性克制等基础规则数据。
- **手动战斗 MVP**：支持己方配置、队伍预设、敌方阵容录入、战斗创建、首发确认、切换、伤害/资源/状态/技能事件录入、时间线和状态快照。
- **战斗工作台**：可展示当前对位、六维面板、性格、技能槽、理论伤害、速度观察、状态结算入口和实时估计摘要。
- **实时面板估计**：敌方精灵会生成估计档案，Observation、手动伤害和自动结算会写入 evidence；旧候选空间方案已移除。
- **伤害与规则解析**：已接入基础 PVP 面板公式、普通攻击最小公式、部分状态/星陨伤害、属性克制/本系/部分天气与应对减伤解析。
- **状态与技能效果**：已落地 P0 状态定义、层数状态统一、部分回合末/入场/切换结算，以及技能结构化操作执行器。
- **技能规则维护**：496 条 cleaned 技能已完成人工审阅；正式导入入口收敛为 `manual_skill_effect_definitions_all_20260612.json` 和 `manual_skill_rule_reviews_all_20260612.json`。
- **事件重放基础**：已具备从非作废事件流重建实时估计、HP/能量、最终状态实例和事件后快照的最小闭环。
- **管理功能**：提供规则数据更新、效果定义查询、战斗归档和物理清理 dry-run 等管理入口。


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
