"""已废弃的开发种子入口。

历史版本中本文件会插入示例精灵、示例技能和示例状态。当前项目已经通过
rocom 爬虫/清洗/导入流程维护真实精灵与技能数据库，因此不再插入任何示例
宠物或技能。

保留本入口仅为了兼容旧命令：

    python -m app.seed.minimal_seed

现在它只会调用正式核心规则初始化，幂等补齐 30 种性格定义。
"""

from app.seed.core_natures import build_core_nature_rows, ensure_core_natures_with_session


def seed_natures():
    """兼容旧代码的性格种子函数，返回 30 种核心性格定义行。"""
    return build_core_nature_rows()


def main() -> None:
    """兼容旧命令：只补齐核心性格，不插入示例精灵/技能/状态。"""
    result = ensure_core_natures_with_session()
    print(
        "minimal_seed is deprecated; only core natures were ensured: "
        f"expected={result.expected_count}, "
        f"created={result.created}, "
        f"updated={result.updated}, "
        f"restored={result.restored}"
    )


if __name__ == "__main__":
    main()
