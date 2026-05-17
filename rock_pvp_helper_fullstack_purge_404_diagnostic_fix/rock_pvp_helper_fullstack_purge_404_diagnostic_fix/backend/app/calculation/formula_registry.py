"""
特殊公式注册表占位。

后续如果某些技能不走普通公式，可以用 special_formula_id 注册专门处理器。
当前不注册任何处理器，调用方应将缺失处理为 formula_unavailable。
"""

SPECIAL_FORMULA_HANDLERS: dict[str, object] = {}
