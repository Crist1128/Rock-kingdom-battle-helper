"""
最小规则数据种子模块。

本模块用于初始化数据库的最小规则数据，便于开发和测试。
建议在开发环境运行此脚本，创建基础数据以便进行功能验证。

后续建议填入：
- 3~5 只常见精灵
- 10~20 个常用技能
- 30 个性格（完整或常用）
- 10~20 个常见状态效果
"""

from app.db.init_db import init_db


def main() -> None:
    """
    初始化数据库并提示添加种子数据。

n    当前为占位实现，初始化数据库结构后提示用户添加数据。
    后续将实现自动导入精灵、技能、性格等基础数据。
    """
    init_db()
    print("Database initialized. Add minimal seed data here.")


if __name__ == "__main__":
    main()
