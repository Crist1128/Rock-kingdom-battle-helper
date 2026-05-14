"""
计算模块异常。

当前项目的伤害公式尚未确认。为了避免误导用户，所有真实伤害计算入口
都应在公式缺失时显式返回 formula_unavailable，而不是使用临时假公式。
"""


class FormulaUnavailableError(RuntimeError):
    """当请求的公式尚未确认或尚未实现时抛出。"""
