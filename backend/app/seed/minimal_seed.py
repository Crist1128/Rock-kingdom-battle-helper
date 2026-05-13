"""最小规则数据 seed 占位。

后续建议填入：
- 3~5 只 elf
- 10~20 个 skill
- 30 个 nature
- 10~20 个 effect
"""

from app.db.init_db import init_db


def main() -> None:
    init_db()
    print("Database initialized. Add minimal seed data here.")


if __name__ == "__main__":
    main()
