# Rock PVP Helper

洛克王国世界 PVP 战斗信息获取与敌方配置推算系统。

当前仓库阶段：**前后端可联调的纯手动输入 MVP 已成型，并已接入候选反推软评分、普通攻击伤害计算与 RuleResolver 雏形；正在继续补齐正式状态定义、技能规则分支、状态结算和事件重放**。

## 当前已具备能力

- 后端：FastAPI + SQLAlchemy 2.x + SQLite + Alembic。
- 前端：React + TypeScript + Vite + TanStack Query + Zustand + Tailwind CSS。
- 本地数据库：默认使用 `data/app.db`。
- 静态规则数据：已接入洛克王国 BWIKI 爬虫、清洗、dry-run、导入流程。
- 已有真实数据：精灵、技能、精灵可学习技能、属性克制规则。
- 手动 MVP：己方配置、战斗创建、阵容录入、首发确认、切换、伤害/资源/状态手动事件、状态快照、时间线、候选摘要。
- 候选反推：已提供 Observation API，可根据伤害值、扣血百分比、技能出现、速度先后手等观测更新 `match_score`、`confidence` 和 evidence；默认只软评分，不硬排除。
- 伤害与规则解析：已实现普通攻击最小公式、伤害观测匹配和 `RuleResolver` 雏形，可解析技能基础信息、本系、属性克制、双属性合并、应对倍率和基础减伤。
- 前端联动：战斗工作台伤害录入可同步提交 observation，候选面板可展示 Top 候选。
- 管理功能：规则数据更新入口、归档战斗 dry-run 与物理清理入口。

## 当前明确未完成内容

- 完整真实伤害体系尚未全部实现；当前仅有普通攻击最小公式，状态伤害、星陨、复杂技能分支、天气/状态 modifier 等仍需补齐。
- 候选配置硬排除尚未开启；当前以软评分、置信度和 evidence 记录为主，避免未验证公式污染候选。
- 速度先手概率尚未实现；当前只有基础面板速度观测匹配。
- 事件重放重算仍是占位能力。
- 图像识别尚未开始。
- 状态定义数据需要补充；代码层已有统一状态系统，但本地正式状态库仍需导入。

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
      inference/           # 敌方候选生成、观测匹配与软评分
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

### 后端

```bash
cd backend
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

访问：

- OpenAPI: http://127.0.0.1:8000/docs
- 健康检查: http://127.0.0.1:8000/api/v1/health

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
2. **核心性格规则**：后端启动时会自动幂等自检查并写入/修正 30 种性格。

启动自检查只处理 `nature_definition`，不会插入示例精灵、示例技能或示例状态。

精灵、技能、可学习技能和属性克制等外部静态规则，仍通过 rocom 数据管线 dry-run 后再提交写库；后端普通启动不会自动远程爬取或大规模写入这些数据。

## 下一步重点

1. 基于现有资料补充 `effect_definition` 状态定义数据。
2. 为状态定义新增导入格式、dry-run 和校验流程。
3. 继续扩展 `RuleResolver`：接入技能规则分支 DSL、天气/状态 modifier、减伤与特殊公式。
4. 实现状态自动结算与星陨等特殊伤害。
5. 在足够样例验证后，再逐步开启候选硬排除。
6. 实现事件重放重算，并完善候选证据链展示。
