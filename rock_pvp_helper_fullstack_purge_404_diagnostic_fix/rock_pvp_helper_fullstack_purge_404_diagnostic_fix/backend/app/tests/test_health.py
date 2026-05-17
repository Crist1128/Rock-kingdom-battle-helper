"""
健康检查测试模块。

本模块包含健康检查端点的单元测试，验证 API 服务是否正常响应。
"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    """
    测试健康检查端点。

n    验证：
    - 端点返回 200 状态码
    - 响应体包含 status: "ok"

    Test:
        GET /api/v1/health
        Expect: 200 {"status": "ok"}
    """
    # 创建测试客户端
    client = TestClient(app)

    # 发送健康检查请求
    response = client.get("/api/v1/health")

    # 验证响应状态码
    assert response.status_code == 200

    # 验证响应内容
    assert response.json() == {"status": "ok"}
