# 当前交付状态

本压缩包完成内容：

- 已建立项目仓库目录结构。
- 已建立后端 FastAPI 骨架。
- 已固定后端技术栈：Python + FastAPI + SQLite + SQLAlchemy + Alembic。
- 已复制系统设计、数据库设计、需求说明、开发规格到 `docs/`。
- 已建立 SQLAlchemy ORM 模型，覆盖 v0.4.1 数据库设计中的核心表。
- 已建立 Alembic 首版迁移 `0001_initial_schema.py`。
- 已建立 API v1 路由，包括健康检查、精灵、技能、状态、战斗和事件基础接口。
- 已建立 SQLite PRAGMA 初始化：foreign_keys、WAL、synchronous、busy_timeout。
- 已建立面板属性计算器 `StatCalculator`。
- 已建立候选生成器骨架 `CandidateGenerator`。
- 已建立状态服务、快照服务、战斗服务骨架。
- 已建立基础测试文件。

当前未实现内容：

- 还未录入真实规则数据。
- 还未实现完整候选落库生成。
- 还未实现完整伤害公式。
- 还未实现敌方候选过滤引擎。
- 还未实现前端页面。
- 还未实现图像识别。

下一步建议：

1. 在本地安装依赖并运行 `alembic upgrade head`。
2. 补充最小规则数据 seed。
3. 完成 `CandidateGenerator` 到 `build_candidate` 表的落库逻辑。
4. 编写状态切换清除、快照生成、伤害事件记录的单元测试。
