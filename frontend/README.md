# Rock PVP Helper Frontend

这是洛克王国世界 PVP 战斗辅助工具的前端。当前前端已经切换到实时面板估计主流程，不再调用旧 `/api/v1/candidates/*` 接口。

## 技术栈

- React + TypeScript + Vite
- TanStack Query
- Zustand
- Tailwind CSS
- Recharts

## 启动方式

```bash
cd frontend
npm.cmd install --no-audit --no-fund
npm.cmd run dev
```

默认 API 地址通过 Vite 代理访问：

```text
VITE_API_BASE_URL=/api/v1
```

## 当前能力

- 战斗创建、准备阶段阵容录入、首发确认、切换和归档。
- 己方配置 CRUD、配队预设和敌方热门阵容预设。
- 战斗工作台录入伤害、资源、状态、切换、技能事件和结束回合。
- 当前对位展示实时面板估计、默认配置、默认面板、属性约束、unknown factors 和 evidence。
- 事件日志支持作废、修正、估计重放和快照详情。
- 规则库查询精灵、技能、状态和性格。
- 设置页支持 rocom 数据更新、任务轮询和归档战斗清理。

## 主要后端接口

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
- `POST /api/v1/admin/data-updates/rocom/import-local`
- `POST /api/v1/admin/data-updates/rocom/sync`
- `GET /api/v1/admin/data-updates/rocom/jobs`
- `GET /api/v1/admin/data-updates/rocom/jobs/{job_id}`

## 边界

- 前端不实现伤害公式。
- 前端不计算速度概率。
- 前端不自行收窄敌方面板。
- 旧候选摘要、Top 候选、候选详情和候选 evidence 页面已经移除。
