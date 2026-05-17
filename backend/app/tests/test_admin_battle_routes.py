"""管理端战斗清理路由注册测试。

这个测试不依赖数据库内容，只确认 FastAPI 应用确实暴露了归档战斗
物理清理接口。它用于防止路由文件存在但忘记 include_router，导致
前端请求 /api/v1/admin/battles/{battle_id}/purge 时出现 404 Not Found。
"""

from app.main import create_app


def _has_route(path: str, method: str) -> bool:
    app = create_app()
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        if route.path == path and method in methods:
            return True
    return False


def test_admin_battle_purge_routes_are_registered() -> None:
    """确认单场和批量物理删除接口都已注册到应用路由表。"""
    assert _has_route("/api/v1/admin/battles/{battle_id}/purge", "DELETE")
    assert _has_route("/api/v1/admin/battles/{battle_id}/purge-plan", "GET")
    assert _has_route("/api/v1/admin/battles/purge-archived", "DELETE")
