# Frontend MVP 范围说明

更新日期：2026-06-09

## 当前阶段

前端已经切换到实时面板估计主流程。当前定位：

- 手动录入战斗事实、状态、伤害、资源和切换。
- 展示后端返回的实时估计、默认配置、属性约束、unknown factors 和 evidence。
- 提供 rocom 数据更新、归档战斗 dry-run / 物理清理入口。
- 不再展示旧候选摘要、Top 候选或 `/candidates/*` 相关结果。

## 已实现页面

1. 战斗首页：创建战斗、读取战斗列表、归档战斗、health 检测。
2. 己方配置管理：己方配置 CRUD、配队预设、敌方热门阵容预设。
3. 准备阶段：录入双方阵容、设置首发、进入 battle 阶段；敌方会创建实时估计档案。
4. 战斗工作台：快捷录入伤害、资源、状态、切换和技能事件；展示当前对位实时估计。
5. 事件日志：时间线展示、事件作废、修正、估计重放、快照详情。
6. 规则库：精灵、技能、状态、性格只读查询。
7. 设置 / 数据管理：rocom 更新、任务轮询、归档战斗清理。

## 真实计算处理原则

- 不在前端实现真实伤害公式。
- 不在前端计算速度先手概率。
- 不基于占位公式或前端猜测收窄敌方面板。
- 伤害录入可同步提交 observation，由后端更新 `EnemyPanelEstimate`。
- 前端只展示后端返回的约束、冲突、unknown factors 和 evidence。

## 当前依赖的主要后端接口

- `GET /api/v1/health`
- `GET /api/v1/elves`
- `GET /api/v1/elves/{elf_id}/skills`
- `GET /api/v1/skills`
- `GET /api/v1/natures`
- `GET /api/v1/effects`
- `GET/POST/PUT/DELETE /api/v1/player-builds`
- `GET/POST /api/v1/battles`
- `POST /api/v1/battles/{battle_id}/lineup`
- `POST /api/v1/battles/{battle_id}/start`
- `GET /api/v1/battles/{battle_id}/state`
- `POST /api/v1/battles/{battle_id}/switch`
- `POST /api/v1/battles/{battle_id}/damage-events`
- `POST /api/v1/battles/{battle_id}/resource-events`
- `POST /api/v1/battles/{battle_id}/skill-events`
- `POST /api/v1/battles/{battle_id}/turns/end`
- `GET /api/v1/battles/{battle_id}/timeline`
- `POST /api/v1/battles/{battle_id}/events/{event_id}/void`
- `POST /api/v1/battles/{battle_id}/events/{event_id}/correct`
- `POST /api/v1/battles/{battle_id}/replay-from/{event_id}`
- `POST /api/v1/observations/{battle_id}`
- `GET /api/v1/estimates/{battle_id}/{elf_id}`
- `PUT /api/v1/estimates/{battle_id}/{elf_id}/default-config`
- `GET /api/v1/estimates/{battle_id}/{elf_id}/evidence`
- `POST /api/v1/admin/data-updates/rocom/check`
- `POST /api/v1/admin/data-updates/rocom/sync`
- `POST /api/v1/admin/data-updates/rocom/import-local`
- `GET /api/v1/admin/data-updates/rocom/jobs`
- `GET /api/v1/admin/data-updates/rocom/jobs/{job_id}`
- `GET/DELETE /api/v1/admin/battles/*`

## 下一步前端建议

1. 完善 estimate evidence 解释页，展示公式上下文、约束来源和冲突原因。
2. 增强事件重放反馈，说明哪些状态和副作用已经重算。
3. 等后端提供速度约束后，补速度先后手解释视图。
4. 对当前大包构建进行路由级代码分割，降低 Vite chunk 体积警告。
