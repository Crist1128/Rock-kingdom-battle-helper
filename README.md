# Rock PVP Helper

洛克王国世界 PVP 战斗信息获取与敌方配置推算系统。

当前仓库阶段：**后端 FastAPI 骨架 + SQLite 数据库模型 + Alembic 首版迁移**。

## 已确定技术栈

- 后端：Python 3.12+、FastAPI、Pydantic、SQLAlchemy 2.x、Alembic
- 数据库：SQLite 3，本地文件数据库
- 测试：pytest、FastAPI TestClient
- 第一阶段：纯手动输入 MVP，不做图像识别、不做自动出招建议

## 目录结构

```text
rock-pvp-helper/
  backend/                 # FastAPI 后端
    app/
      api/                 # API 路由
      calculation/         # 面板属性、伤害、速度计算
      core/                # 配置和枚举
      db/                  # 数据库 session、Base、初始化
      inference/           # 敌方候选推算
      models/              # SQLAlchemy ORM
      schemas/             # Pydantic schemas
      services/            # 业务服务
      tests/               # 单元测试
    alembic/               # Alembic 迁移
    pyproject.toml
  docs/                    # 需求、开发规格、系统设计、数据库设计
  data/                    # 本地 SQLite 数据库目录
  scripts/                 # 开发脚本
```

## 后端启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e '.[dev]'
cp ../.env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

访问：

- OpenAPI: http://127.0.0.1:8000/docs
- 健康检查: http://127.0.0.1:8000/api/v1/health

## 第一阶段开发顺序

1. 完成数据库迁移和最小规则数据 seed。
2. 完成 `StatCalculator` 单元测试。
3. 完成 `CandidateGenerator`。
4. 完成战斗创建、阵容录入、状态快照、伤害事件记录。
5. 接入候选过滤和速度判断。

