"""
API v1 端点子模块。

本目录包含 API v1 的各个功能端点模块：
- health.py: 健康检查
- elves.py: 精灵管理
- skills.py: 技能管理
- effects.py: 状态效果管理
- battles.py: 战斗管理

每个模块通过 FastAPI 的 APIRouter 定义路由，在 router.py 中统一挂载。
"""
