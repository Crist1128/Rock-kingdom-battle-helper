# Backend

本目录是 FastAPI 后端骨架。

## 常用命令

```bash
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

## 当前已包含

- FastAPI 应用入口
- API v1 路由
- SQLAlchemy 2.x ORM 模型
- Alembic 初始化和首版迁移
- SQLite PRAGMA 初始化
- 健康检查接口
- 精灵 / 技能 / 状态 / 战斗基础接口
- 面板属性计算器雏形
