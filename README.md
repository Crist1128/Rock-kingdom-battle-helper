# Rock PVP Helper

洛克王国世界 PVP 战斗信息获取与敌方配置推算系统。

当前仓库阶段：**前后端可联调的纯手动输入 MVP 已基本成型，正在进入真实规则、状态定义与伤害公式补齐阶段**。

## 当前已具备能力

- 后端：FastAPI + SQLAlchemy 2.x + SQLite + Alembic。
- 前端：React + TypeScript + Vite + TanStack Query + Zustand + Tailwind CSS。
- 本地数据库：默认使用 `data/app.db`。
- 静态规则数据：已接入洛克王国 BWIKI 爬虫、清洗、dry-run、导入流程。
- 已有真实数据：精灵、技能、精灵可学习技能、属性克制规则。
- 手动 MVP：己方配置、战斗创建、阵容录入、首发确认、切换、伤害/资源/状态手动事件、状态快照、时间线、候选摘要。
- 管理功能：规则数据更新入口、归档战斗 dry-run 与物理清理入口。

## 当前明确未完成内容

- 真实伤害公式尚未实现，后端会返回 `formula_unavailable`。
- 候选配置真实排除/收敛尚未实现，当前只生成候选并展示摘要。
- 速度先手概率尚未实现。
- 事件重放重算仍是占位能力。
- 图像识别尚未开始。
- 状态定义数据需要补充；代码层已有统一状态系统，但本地正式状态库仍需导入。

## 目录结构

```text
Rock-kingdom-battle-helper/
  backend/                 # FastAPI 后端
    app/
      api/                 # API 路由
      calculation/         # 面板属性、伤害、速度计算/占位
      core/                # 配置和枚举
      data_pipeline/       # BWIKI 数据爬取、清洗、导入
      db/                  # 数据库 session、Base、初始化
      inference/           # 敌方候选推算/占位
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
3. 确认并实现真实伤害公式。
4. 在伤害公式基础上实现候选过滤、证据链和事件重放。
