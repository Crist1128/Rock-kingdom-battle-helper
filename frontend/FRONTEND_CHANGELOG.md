# 本次前端修改说明

## 2026-07-21 深浅模式切换性能优化

1. **主题切换收缩过渡范围**：取消 `theme-animating` 对全局子树的统一 transition，改为只让主壳层平滑过渡。
2. **降低切换热点**：主题切换期间临时关闭 `backdrop-filter` 和阴影绘制，减少侧栏、顶栏、抽屉、弹窗等区域的大面积重绘。
3. **保留风格一致性**：继续保留黑夜 / 白天双主题，页面进入动效、Toast、Sheet、Confirm、骨架屏等既有动效不变，只优化切换时的卡顿感。

---

## 2026-07-21 全局动效增强收尾

1. **统一动效工具类**：在 `styles.css` 中补齐页面进入、局部淡入、遮罩、弹窗、抽屉、Toast、骨架屏流光等命名动画，替换零散 `animate-[...]` 写法。
2. **进入/退出闭环**
   - 路由内容按 `pathname` 做轻量页面进入动画。
   - Confirm 对话框补齐遮罩和弹窗的进入/退出动画。
   - Sheet 抽屉补齐滑入/滑出动画，关闭时不再直接瞬间卸载。
   - Toast 补齐关闭动画，并统一清理自动关闭定时器。
3. **交互反馈与加载态**
   - Button 点击反馈改为 `motion-safe` 缩放，尊重系统减弱动效设置。
   - 懒加载骨架屏从单纯 pulse 改为科技风流光骨架。
   - 伤害计算器模式切换继续使用统一的局部淡入工具类。
4. **主题切换稳定性**：主题切换过渡增加定时器清理，连续点击或组件卸载时不会残留 `theme-animating`。

---

## 2026-07-21 P4 页面打磨 + P5 体验收尾（Toast/确认框/代码分割）

1. **EnergyPips 调整**：能量点按能量值一一对应显示，上限 99 点，移除溢出 +N 标记，点数多自动换行。
2. **P4 页面改造**
   - 伤害计算器：攻击/防御双卡间加居中 VS 徽章；预计伤害改 4xl 等宽渐变（青→蓝）大数字。
   - 首页：最近战斗从卡片堆改为紧凑列表行（状态色点 + 名称 + 等宽 ID/时间 + 阶段徽章 + 行内按钮）。
   - 设置页：数据更新 section 编号修正为 0-5 连续（原有两个"2."）。
3. **P5 Toast 与确认对话框**（新增 `ui/toast.tsx`、`ui/confirm.tsx`）
   - ToastProvider：右上角浮层，default/success/error 三态，4.2s 自动关闭，最多同时 4 条。
   - ConfirmProvider：Promise 式 `confirm({title, description, confirmText, danger})`，居中模态 + 背景模糊，危险操作红色描边 + 红色确认键。
   - 全局 19 处 `window.alert/confirm` 全部替换（Dashboard 4、Workbench 4、Builds 2、Preparation 1、Settings 8），Provider 挂载于 main.tsx。
4. **P5 路由级代码分割**（`App.tsx` 重写）
   - 8 个页面全部 React.lazy + Suspense（骨架屏 fallback）；主包 513KB → 259KB（gzip 150→83KB），500KB chunk 警告消除。
   - 新增 `ui/skeleton.tsx`（Skeleton + PageLoadingSkeleton）；工作台"正在读取战斗状态"改三栏骨架屏。
   - 卸载未使用的 recharts 死依赖（36 个包）。
5. 验证：`npm.cmd run typecheck`、`npm.cmd run build` 通过，构建产物按页面分 chunk；dev server 各新模块转换正常。

---

## 2026-07-21 深浅双主题 + P3 战斗工作台 HUD 改造

1. **深浅双主题**（`styles.css` / `index.html` / `Layout.tsx` / `tailwind.config.ts`）
   - tokens 拆分为 `:root`（浅色）与 `.dark`（深色）双套；`index.html` 内联脚本在首帧前按 localStorage 恢复主题（默认深色），避免闪烁。
   - 侧边栏底部新增 Sun/Moon 主题切换按钮，选择持久化到 `rock-pvp-helper.theme`。
   - 18 系别色从 JS 常量改为 CSS 变量（`--el-*`，浅色系加深版 / 深色系亮色版），`ElementTypeChip` 全主题可读。
   - 字面色二次语义化迁移：`amber→warning`、`red→destructive`、`emerald→success`、`sky/blue→info`、`violet→accentv`、`indigo→accenti`，所有提示块随主题变量自适应。
2. **对位对峙卡**（`BattleWorkbenchPage.tsx` / `ElfCard.tsx` / `EnergyPips.tsx`）
   - 新增 `EnergyPips` 能量格组件（发光菱形 + 等宽数字，超出上限折叠 +N），替换"能量 X"文字。
   - ActiveSide 对位卡按侧着色（我方青边 / 敌方红边 + 侧色圆点），两卡之间加居中 VS 徽章。
   - ElfCard 上场卡对抗色描边 + 微发光，"上场"标记改侧色胶囊；TeamPanel 标题加侧色圆点。
3. **回合操作台**：行动类型从下拉框改为 5 段分段控件（未知/攻击/防御/状态/切换），选中段青色高亮微发光；速度先后手关系色改为对抗色（我方快=text-self、敌方快=text-enemy、同速=text-warning）。
4. **事件时间线战斗日志风**（`EventTimeline.tsx` 重构）：工作台 compact 模式改终端日志样式——等宽字体、T{n} 回合分隔线、我方 ▸ 青 / 敌方 ◂ 红行前缀、行 hover 高亮；完整模式（事件日志页）保留快照面板与选择事件能力。
5. 验证：`npm.cmd run typecheck`、`npm.cmd run build` 通过；构建 CSS 确认双主题变量与全部语义类生成；dev server 各模块转换正常。

---

## 2026-07-20 深空科技风视觉重构（P1 设计基座 + P2 框架）

1. **设计 tokens 深色化**（`styles.css` / `tailwind.config.ts` / `index.html`）
   - 全局切换为深色单主题：深空三色背景层级（base/card/raised）、电光青主色、`--self` 青 / `--enemy` 玫瑰红对抗色、success/warning/info 功能色。
   - 圆角收紧（xl 16→10px、2xl 20→12px）、新增 `glow` 发光阴影、`font-num` 等宽数字工具类、深色滚动条与选中色。
   - `index.html` 声明 `color-scheme: dark` 并内联底色避免启动白屏。
2. **基础组件重绘**：Button/Card/Badge/Input/Select/Sheet/Avatar 全部改为玻璃拟态深色风格（细描边、弱底色、青色聚焦环、主按钮微发光）。
3. **全站 token 迁移**：`bg-white`、`bg-slate-50`、`text-slate-*`、`border-slate-*` 及各彩色 info 块（emerald/amber/sky/red/violet/indigo/blue 50~950）批量替换为深色语义类（`bg-raised/60`、`text-foreground`、`amber-400/10` 等），共 28 个文件。
4. **系别色板**：新增 `lib/elementTypeColors.ts`（18 系专属色）与 `components/ElementTypeChip.tsx`（色点+文字 chip）。
5. **Layout 重构**：侧边栏 256→208px，支持折叠为 56px 图标栏（localStorage 持久化）；导航选中态改为左侧 2px 青色指示条 + 弱底色；新增顶栏战斗 HUD（战斗名、阶段、回合数等宽大数字、进入工作台快捷键，战斗中每 15s 轮询）。
6. **其他**：FormulaUnavailableBanner 改细长可关闭警示条（localStorage 记忆）；HealthBar 改渐变血条（>50% 绿 / 20-50% 黄 / ≤20% 红）+ 等宽数字；移除 `body min-width: 1280px`。
7. 验证：`npm.cmd run typecheck`、`npm.cmd run build` 通过；dev server 模块转换正常。构建单 chunk 513KB 警告仍在，路由级代码分割留待后续。

---

## 2026-05-16 己方配置体验修正

1. 己方配置列表不再直接展示 `elf_id`、`skill_id` 作为主要名称。
   - 精灵名称通过 `GET /api/v1/elves?limit=500` 建立映射。
   - 技能名称通过 `GET /api/v1/skills?limit=500` 建立映射。
   - ID 只保留为辅助调试信息，并进行缩略显示。

2. 己方配置增加删除入口。
   - 前端已调用 `DELETE /api/v1/player-builds/{build_id}`。
   - 当前后端未实现时会给出明确提示。
   - 后端补齐接口后前端无需再改。

3. 新建/编辑配置时，选中精灵后的可见性增强。
   - 搜索列表中的已选精灵高亮。
   - 表单中增加“已选择：精灵中文名”的高亮卡片。
   - 选中精灵后会清空已有技能槽，避免误用上一只精灵的技能。

4. 技能槽优先支持精灵可学习技能池。
   - 前端会尝试调用 `GET /api/v1/elves/{elf_id}/skills`。
   - 当前后端未实现该接口时，自动退回全局技能搜索并显示提示。
   - 后端补齐接口后，技能槽会自动显示该精灵对应技能池。

---

## 2026-05-21 前后端候选反推对齐

1. 对齐后端第三/第四阶段新增的 Observation API。
   - 新增 `ObservationCreate`、`ObservationProcessResult`、`PanelStatsInput` 等类型。
   - 新增 `api.observations.process(battleId, payload)`。
2. 战斗工作台的伤害录入表单现在可同步提交候选反推观察。
   - 默认启用“同步写入候选反推观察”。
   - 默认启用后端规则解析 `resolve_rules=true`。
   - 我方攻击敌方时，按敌方防御候选反推；敌方攻击我方时，按敌方攻击候选反推。
   - 若缺少敌方目标、伤害值或必要面板，则只记录事件并提示不会反推。
3. 候选面板增加 Top 5 候选展示。
   - 展示候选 ID、置信度、匹配分数、HP、速度、物防、魔防和有效/排除状态。
   - 录入观察后会刷新候选摘要、详情和候选列表。
4. 已通过前端 typecheck、生产构建，以及后端 pytest 回归。

---

## 2026-05-21 前端中文显示与编码巡检

1. 巡检 `frontend/src` 下 TS/TSX/CSS 文案，未发现真实 mojibake 字符或 UTF-8 解码错误。
2. 修复少量此前已出现风险的候选面板、伤害录入面板中文文案，确认当前源码显示正常。
3. 在全局样式中显式加入中文字体回退栈，并让表单控件继承全局字体，降低中文缺字、方块字或字体回退不一致的风险。
4. 将 `FRONTEND_SCOPE.md` 从 UTF-8 BOM 改为无 BOM UTF-8，避免部分编辑器/终端显示异常。
