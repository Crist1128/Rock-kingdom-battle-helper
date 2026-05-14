"""
业务服务包。

本包包含应用的业务逻辑服务层，为 API 层提供高层次的业务接口：
- battle_service: 战斗服务
- candidate_service: 候选配置生成服务
- effect_service: 状态效果服务
- snapshot_service: 快照服务

服务层负责：
- 协调多个数据模型的操作
- 实现业务规则
- 处理事务边界
- 为 API 层提供清晰的接口
"""
