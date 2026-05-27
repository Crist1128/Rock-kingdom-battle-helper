# Frontend MVP 范围说明

更新日期：2026-05-21

## 当前阶段

前端已经完成纯手动输入 MVP 的主要页面和后端联调入口。当前前端定位是：

- 不伪造真实伤害、速度和候选排除结果。
- 作为手动战斗事实录入、规则查看、候选摘要展示和数据管理入口。
- 等后端真实公式、状态规则和推断引擎补齐后，再逐步展示真实计算结果。

## 已实现页面

1. 战斗首页
   - 创建战斗。
   - 手动添加 battle_id。
   - 优先读取后端战斗列表。
   - localStorage 最近战斗记录作为兜底。
   - 后端 health 检测。
   - 最近战斗“移除”按归档处理，不物理删除。

2. 己方配置管理
   - 查询己方配置。
   - 创建 / 编辑 / 删除己方配置。
   - 精灵搜索、性格选择、技能搜索、个体资质录入。
   - 优先查询精灵可学习技能。
   - 面板属性只展示后端返回缓存，不做前端真实计算。

3. 准备阶段
   - 录入我方最多 6 个配置槽。
   - 录入敌方最多 6 个精灵槽。
   - 设置双方首发。
   - 调用 lineup 接口生成敌方候选。
   - 调用 start 接口进入 battle 阶段。

4. 战斗工作台
   - 双方队伍区。
   - 当前对位面板。
   - 快捷录入：伤害、资源、状态、切换。
   - 统一状态分组展示。
   - 候选摘要 / 速度分布展示。
   - 时间线简版展示。
   - 结束战斗入口。

5. 事件日志
   - battle_id 切换。
   - 时间线完整展示。
   - 事件作废、修正、重放入口按后端当前能力展示。

6. 规则库
   - 精灵、技能、状态、性格只读查询。
   - 精灵/技能分页和搜索。
   - 兼容 rocom 数据中的远程头像和 JSON 字段。

7. 设置 / 数据管理
   - API 地址显示。
   - health 检测。
   - Admin Token 本地保存。
   - rocom 远程检查。
   - rocom 远程同步 dry-run / commit。
   - 本地 cleaned JSON 导入 dry-run / commit。
   - 数据更新任务轮询。
   - 归档战斗 dry-run 预览。
   - 归档战斗物理清理。

## 真实计算处理原则

本项目当前由后端负责规则计算与候选推断，前端遵循以下约束：

- 不在前端计算真实伤害。
- 不在前端计算真实速度先手概率。
- 不展示伪伤害区间。
- 不根据占位公式或前端猜测排除候选。
- 伤害录入可同步提交 observation，由后端进行候选软评分。
- 候选面板展示后端返回的摘要、Top 候选、unknown 或 `formula_unavailable` 等状态。
- 技能伤害、击杀判断、速度概率只显示后端已提供的结果或明确的未实现状态。
- 前端只展示后端返回的事实和推断结果，不自行推断隐藏规则。

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
- `POST /api/v1/battles/{battle_id}/finish`
- `POST /api/v1/battles/{battle_id}/archive`
- `POST /api/v1/battles/{battle_id}/damage-events`
- `POST /api/v1/battles/{battle_id}/resource-events`
- `POST /api/v1/observations/{battle_id}`
- `GET /api/v1/battles/{battle_id}/timeline`
- `POST /api/v1/effects/instances`
- `DELETE /api/v1/effects/instances/{instance_id}`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/summary`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/detail`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/evidence`
- `POST /api/v1/admin/data-updates/rocom/check`
- `POST /api/v1/admin/data-updates/rocom/sync`
- `POST /api/v1/admin/data-updates/rocom/import-local`
- `GET /api/v1/admin/data-updates/rocom/jobs`
- `GET /api/v1/admin/data-updates/rocom/jobs/{job_id}`
- `GET/DELETE /api/v1/admin/battles/*`

## 技术栈

- React 18
- TypeScript
- Vite
- TanStack Query
- Zustand
- Tailwind CSS
- 本地 shadcn/ui 风格组件
- Recharts

## 下一步前端建议

1. 在规则库中增加状态定义维护/预览页面，用于配合 `effect_definition` 数据补充。
2. 在事件日志中增加快照详情查看。
3. 等后端提供真实速度上下文后，补速度区间/先手展示。
4. 基于后端 observation evidence，补候选匹配/冲突原因展示；硬排除原因等后端开启后再展示。
5. 对当前大包构建进行路由级代码分割，降低 Vite chunk 体积警告。
