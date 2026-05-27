# 洛克王国世界 PVP 推算工具 - Frontend MVP

这是基于最新 FastAPI 后端接口制作的前端 MVP。技术栈遵循项目文档：

- React + TypeScript + Vite
- TanStack Query
- Zustand
- Tailwind CSS + shadcn/ui 风格本地组件
- Recharts

## 启动方式

```bash
cd rock-pvp-helper-frontend-mvp
cp .env.example .env
npm install
npm run dev
```

默认 `.env.example` 使用相对路径：

```text
VITE_API_BASE_URL=/api/v1
```

Vite 已配置 `/api` 代理到：

```text
http://127.0.0.1:8000
```

如果不想使用代理，也可以把 `.env` 改成完整地址：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## 针对本次后端更新的适配

本版前端已适配：

- `GET /api/v1/elves?q=&limit=&offset=`：精灵搜索、分页、远程头像展示。
- `GET /api/v1/skills?q=&limit=&offset=`：技能搜索、分页、规则字段展示。
- `element_types_json`：前端统一 `JSON.parse()` 为属性数组。
- `avatar`：按远程 URL 展示，并增加图片加载失败 fallback。
- `data_version === "dev"`：规则库可切换显示；选择器默认优先隐藏 dev 示例数据。
- `GET /api/v1/candidates/{battle_id}/{elf_id}/detail`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/evidence`
- `POST /api/v1/admin/data-updates/rocom/check`
- `POST /api/v1/admin/data-updates/rocom/import-local`
- `POST /api/v1/admin/data-updates/rocom/sync`
- `GET /api/v1/admin/data-updates/rocom/jobs`
- `GET /api/v1/admin/data-updates/rocom/jobs/{job_id}`。
- `POST /api/v1/observations/{battle_id}`：伤害录入后可同步提交候选反推观察。
- 候选详情按最新 `speed_buckets`、`nature_distribution`、`pattern_distribution` 和 Top 候选结构展示。
- Vite `/api` proxy：减少本地开发跨域和地址硬编码。

设置 / 数据管理页面已经接入主动数据更新入口：

```text
POST /api/v1/admin/data-updates/rocom/check
POST /api/v1/admin/data-updates/rocom/import-local
POST /api/v1/admin/data-updates/rocom/sync
GET  /api/v1/admin/data-updates/rocom/jobs
GET  /api/v1/admin/data-updates/rocom/jobs/{job_id}
```

这些接口仍由 `X-Admin-Token` 保护。前端只允许用户手动输入管理令牌并保存在浏览器 localStorage，不会把 `ADMIN_UPDATE_TOKEN` 写入公开代码。推荐流程是：先检查更新或 dry-run，再确认提交写库。

## 当前设计边界

本前端明确遵守“计算由后端负责、前端不伪造规则”的项目边界：

- 不在前端实现伤害公式。
- 不展示伪伤害区间。
- 不在前端实现速度先手概率。
- 不基于占位公式或前端猜测排除候选。
- 伤害录入可把 observation 提交给后端，由后端进行软评分；存在未知因素时仍展示后端返回的 unknown / `formula_unavailable` / manual only 等状态。

## 后端接口依赖

已对接当前后端已有接口：

- `GET /api/v1/health`
- `GET /api/v1/elves`
- `GET /api/v1/elves/{elf_id}/skills`
- `GET /api/v1/skills`
- `GET /api/v1/natures`
- `GET /api/v1/effects`
- `GET/POST/PUT/DELETE /api/v1/player-builds`
- `GET /api/v1/battles`
- `POST /api/v1/battles`
- `GET /api/v1/battles/{battle_id}`
- `POST /api/v1/battles/{battle_id}/lineup`
- `POST /api/v1/battles/{battle_id}/start`
- `GET /api/v1/battles/{battle_id}/state`
- `POST /api/v1/battles/{battle_id}/switch`
- `POST /api/v1/battles/{battle_id}/finish`
- `POST /api/v1/battles/{battle_id}/archive`
- `POST /api/v1/battles/{battle_id}/damage-events`
- `POST /api/v1/battles/{battle_id}/resource-events`
- `GET /api/v1/battles/{battle_id}/timeline`
- `GET /api/v1/battles/{battle_id}/snapshots/{snapshot_id}`
- `POST /api/v1/battles/{battle_id}/events/{event_id}/void`
- `POST /api/v1/battles/{battle_id}/events/{event_id}/correct`
- `POST /api/v1/battles/{battle_id}/replay-from/{event_id}`
- `POST /api/v1/effects/instances`
- `DELETE /api/v1/effects/instances/{instance_id}`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/summary`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/detail`
- `GET /api/v1/candidates/{battle_id}/{elf_id}/evidence`
- `POST /api/v1/admin/data-updates/rocom/check`
- `POST /api/v1/admin/data-updates/rocom/import-local`
- `POST /api/v1/admin/data-updates/rocom/sync`
- `GET /api/v1/admin/data-updates/rocom/jobs`
- `GET /api/v1/admin/data-updates/rocom/jobs/{job_id}`

## 已知后端边界与前端处理

1. 事件修正接口已提供通用入口，但复杂伤害/资源/状态子事件修正仍建议通过专用录入接口重新创建事实事件。
2. 从修正点重放接口当前为占位返回，不会执行真实重算；后续需要 EventReplayService。
3. `BattleStateOut.elves` 和 `active_effects` 仍返回 `dict`，前端用宽松类型接收，并在 UI 层容错。
4. 完整真实伤害体系、速度先手概率和候选硬排除仍未完成；前端只展示后端 observation 软评分、Top 候选、unknown 或 `formula_unavailable` 等结果。

详见 `BACKEND_NOTES.md`。
