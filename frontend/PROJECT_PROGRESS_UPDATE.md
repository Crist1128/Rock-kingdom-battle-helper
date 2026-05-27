# 前端项目进展更新

更新日期：2026-05-21

## 当前前端阶段

前端已经完成纯手动输入 MVP 的主要功能，可以作为本地战斗记录、规则查询、候选摘要查看和数据管理工具使用。

当前前端不负责真实伤害、速度和候选过滤计算；这些逻辑由后端公式和推断引擎负责。前端已接入 Observation API，可在伤害录入后同步提交候选反推观察并展示 Top 候选。

## 已完成页面

### 1. 战斗首页 `/`

- 后端 health 检测。
- 创建战斗。
- 展示后端最近战斗列表。
- localStorage 最近战斗兜底。
- 手动添加 battle_id。
- 进入战斗。
- 移除最近战斗时调用归档接口，不物理删除。

### 2. 己方配置 `/builds`

- 查询己方配置。
- 创建己方配置。
- 编辑己方配置。
- 删除己方配置。
- 精灵搜索。
- 性格选择。
- 技能搜索。
- 优先使用精灵可学习技能池。
- 个体资质录入。
- 展示后端计算后的面板缓存。

### 3. 准备阶段 `/preparation`

- 录入我方配置槽。
- 录入敌方精灵槽。
- 设置双方首发。
- 调用 lineup 生成敌方候选。
- 调用 start 进入 battle 阶段。

### 4. 战斗工作台 `/battle`

- 展示双方队伍。
- 展示当前上场对位。
- 快捷录入伤害事件。
- 快捷录入资源事件。
- 快捷施加/移除状态。
- 快捷切换精灵。
- 展示统一状态面板。
- 展示候选摘要、速度分布占位和 Top 候选。
- 伤害录入可按条件同步提交 observation，触发后端候选软评分。
- 展示简版时间线。
- 结束战斗入口。

### 5. 事件日志 `/events`

- 切换 battle_id。
- 展示完整时间线。
- 对接事件作废、修正、重放占位能力。

### 6. 规则库 `/rules`

- 精灵查询。
- 技能查询。
- 性格查询。
- 状态定义查询。
- 兼容远程图片 URL 和 JSON 字段展示。

### 7. 设置 / 数据管理 `/settings`

- API 地址显示。
- 后端 health 重新检测。
- Admin Token 本地保存。
- rocom 远程检查。
- rocom 远程同步 dry-run / commit。
- 本地 cleaned JSON 导入 dry-run / commit。
- 数据更新任务轮询。
- 归档战斗列表。
- 单场归档战斗 dry-run / 物理清理。
- 批量归档战斗 dry-run / 物理清理。

## 当前前端边界

前端明确不做以下事情：

- 不计算真实伤害。
- 不计算真实速度先手概率。
- 不伪造击杀判断。
- 不根据占位公式排除候选。
- 不直接访问 BWIKI。
- 不把 Admin Token 写死在代码里。

## 验证情况

当前已验证：

```bash
npm.cmd run typecheck
npm.cmd run build
```

均通过。

构建存在 Vite chunk 体积提示，当前不影响功能，后续可通过路由级懒加载优化。

## 当前依赖风险

- 规则库如果缺少 `effect_definition`，状态搜索和施加状态功能会缺少可选项。
- 30 种性格已由后端启动自检查自动补齐；如果仍创建失败，应检查 Alembic 迁移是否已执行。
- 候选数量较大时，候选详情页面可能需要分页和性能优化。
- 完整真实公式未实现前，候选面板仍需兼容 `formula_unavailable` / unknown；目前可展示后端 observation 软评分后的 Top 候选。

## 下一步前端优先级

1. 增加状态定义数据管理/预览页面，辅助整理 `effect_definition`。
2. 在事件日志中增加快照详情查看。
3. 候选详情增加更清晰的分页和性能提示。
4. 等后端提供真实速度上下文后，补速度先手展示。
5. 基于后端 observation evidence，补候选匹配/冲突原因和置信度展示；候选硬排除原因等后端开启后再展示。
6. 进行路由级代码分割，降低构建 chunk 体积。

---

## 2026-05-21 补充：前后端 Observation 对齐

后端已完成候选软评分、普通伤害计算、Observation API 和 RuleResolver 雏形。本次前端完成对应接入：

- `src/types/api.ts` 增加 Observation API 类型；
- `src/lib/api.ts` 增加 `api.observations.process()`；
- `ManualEventDrawer` 的伤害录入会在记录 DamageEvent 后，按条件提交 `damage_value` observation；
- observation payload 默认带 `resolve_rules=true`，让后端解析技能、本系、克制和应对倍率；
- `CandidatePanel` 增加候选 Top 5，便于观察录入后立刻查看候选分布变化。

验证命令：

```bash
npm.cmd run typecheck
npm.cmd run build
cd ../backend
python -m pytest -q
```

验证结果：

```text
frontend typecheck passed
frontend build passed
backend pytest: 17 passed
```

---

## 2026-05-21 补充：前端中文显示巡检

- 已检查 `frontend/src` 内主要源码文案，当前未发现真实 UTF-8 解码错误或 mojibake 残留。
- 全局 CSS 已补充中文字体回退栈，表单控件继承同一字体，避免不同控件出现中文字体缺字或显示不一致。
- `FRONTEND_SCOPE.md` 已统一为无 BOM UTF-8。

建议后续所有前端源码与 Markdown 文档继续保存为 **UTF-8 无 BOM**。
