# Rock PVP Helper Backend

这是“洛克王国世界 PVP 战斗信息获取与敌方配置推算系统”的 FastAPI 后端。

当前版本重点完成 **手动输入 MVP 后端闭环**：己方配置、战斗阵容、敌方候选、统一状态实例、伤害事件记录、状态快照、数据管线管理接口和公式占位推算。

## 常用命令

Windows CMD 推荐使用双引号：

```bash
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
python -m pytest -q
```

> `app.seed.minimal_seed` 已废弃为示例种子入口；当前仅兼容性地补齐 30 种核心性格，不再插入示例精灵/技能/状态。

## 当前已包含

- FastAPI 应用入口与 API v1 路由。
- SQLAlchemy 2.x ORM 模型与 Alembic 迁移。
- SQLite PRAGMA 初始化。
- 静态规则查询：精灵、技能、性格、状态。
- 己方配置管理：`/api/v1/player-builds`。
- 战斗流程：创建战斗、录入阵容、进入战斗、切换精灵。
- 敌方候选配置生成和摘要/详情查询：`/api/v1/candidates`。
- 统一状态实例：手动施加、手动移除、切换清除/保留。
- 伤害事件记录：支持单次伤害、动画多段最终总伤害、连击伤害。
- 资源变化事件记录：支持治疗、能量获得、能量消耗等手动事实。
- 战斗时间线：按回合聚合技能、伤害、状态和资源变化等事件。
- 伤害公式占位：明确返回 `formula_unavailable`，不执行候选排除。
- 数据管线管理接口：远程检查、远程同步、本地 cleaned JSON 导入。

## 手动输入 MVP 流程

1. `alembic upgrade head` 确保数据库结构最新。
2. 通过数据管线或已有数据库准备完整精灵、技能、性格、状态数据。
3. 创建己方精灵配置。
4. 创建战斗。
5. 录入双方阵容；己方使用 `build_id`，敌方使用 `elf_id`。
6. 系统为敌方精灵自动生成候选配置。
7. 确认双方首发，进入战斗阶段。
8. 手动记录技能、伤害、状态变化、切换、资源变化等事件。
9. 每个关键事件生成状态快照。
10. 伤害公式未确认时，只记录事实，不排除候选。

## 重要边界

当前版本不会实现真实伤害公式，不会自动识图，也不会自动推荐出招。所有计算相关入口都已经预留，后续确认公式后可在 `app/calculation/damage_calculator.py` 和 `app/inference/inference_engine.py` 中接入。

阵容录入当前采用“每方最多 6 只”的校验，不强制必须 6 只，便于开发、联调和非完整阵容测试。

## BWIKI 精灵数据更新策略

不建议后端每次启动都检查或自动爬取远程数据。默认配置保持：

```env
ROCOM_AUTO_UPDATE_ON_STARTUP=false
```

推荐流程是主动管理：

```text
检查远程列表是否可能有新增
↓
执行 dry-run 同步或 dry-run 本地导入
↓
查看 import_summary / warnings
↓
确认后 commit=true 写库
```

### 管理接口

```text
POST /api/v1/admin/data-updates/rocom/check
POST /api/v1/admin/data-updates/rocom/sync
POST /api/v1/admin/data-updates/rocom/import-local
GET  /api/v1/admin/data-updates/rocom/jobs/{job_id}
GET  /api/v1/admin/data-updates/rocom/jobs
```

如果配置了 `ADMIN_UPDATE_TOKEN`，以上接口需要请求头：

```text
X-Admin-Token: <your-token>
```

### 只检查是否可能有新增精灵

```bash
curl -X POST http://localhost:8000/api/v1/admin/data-updates/rocom/check \
  -H "Content-Type: application/json" \
  -d '{"limit": 0, "include_new_elves_limit": 100}'
```

该接口只抓取图鉴列表页，不抓详情页、不清洗、不写库。它适合判断“是否可能有新增精灵”。详情页字段变化仍需 dry-run 同步确认。

### 远程同步 dry-run

```bash
curl -X POST http://localhost:8000/api/v1/admin/data-updates/rocom/sync \
  -H "Content-Type: application/json" \
  -d '{"commit": false, "limit": 10, "force": false}'
```

确认后提交：

```bash
curl -X POST http://localhost:8000/api/v1/admin/data-updates/rocom/sync \
  -H "Content-Type: application/json" \
  -d '{"commit": true, "limit": 0, "force": true}'
```

### 本地 cleaned JSON 导入

适合你已经用爬虫生成 cleaned JSON，只需要导入数据库的场景。

```bash
curl -X POST http://localhost:8000/api/v1/admin/data-updates/rocom/import-local \
  -H "Content-Type: application/json" \
  -d '{"commit": false, "cleaned_dir": "../data/rocom/cleaned"}'
```

确认后提交：

```bash
curl -X POST http://localhost:8000/api/v1/admin/data-updates/rocom/import-local \
  -H "Content-Type: application/json" \
  -d '{"commit": true, "cleaned_dir": "../data/rocom/cleaned", "data_version": "rocom_bwiki_20260516"}'
```

## CLI 数据管线

爬取并清洗：

```bash
python -m app.data_pipeline.rocom.scraper \
  --output ../data/rocom/raw/sprites_raw.json \
  --clean-output-dir ../data/rocom/cleaned
```

Dry-run 导入数据库：

```bash
python -m app.data_pipeline.rocom.importer --cleaned-dir ../data/rocom/cleaned
```

确认后提交：

```bash
python -m app.data_pipeline.rocom.importer --cleaned-dir ../data/rocom/cleaned --commit
```

默认不下载图片；需要图片时显式追加 `--with-images`。数据库、raw/cleaned JSON、图片和 `.env` 不应提交到 GitHub。

## 数据目录约定

本项目默认使用与 `backend/` 同级的 `data/` 目录作为本地运行数据目录：

```text
project-root/
├── backend/
└── data/
    ├── app.db
    └── rocom/
```

`app/core/config.py` 会按 `backend/` 目录解析相对路径，避免从不同目录启动后写到错误位置。

## 2026-05-19 进度补充

当前后端已经完成手动输入 MVP 的主要闭环：己方配置、战斗流程、事件日志、状态实例、快照、候选生成、rocom 数据管线和管理接口均已具备。

后续重点不是继续扩接口数量，而是补齐正式规则数据和真实计算：

1. 将 30 种性格从开发用 `minimal_seed` 拆成正式 core seed。
2. 补充 `effect_definition` 状态定义数据，并提供 dry-run 导入能力。
3. 确认并实现真实伤害公式。
4. 基于真实公式实现候选过滤、证据链和事件重放。

空库初始化建议保持三步：

```text
Alembic 建表
  ↓
core seed 写入性格和基础状态定义
  ↓
rocom 数据管线导入精灵、技能、技能池和属性克制
```

普通后端启动默认不应远程爬取或大规模写库；核心基础规则是否启动时自动补齐，建议后续用配置项控制，默认关闭。
