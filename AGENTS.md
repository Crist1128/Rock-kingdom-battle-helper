# AGENTS.md

> 本文件用于规范后续 AI/Codex 代理在本仓库中的开发行为。  
> 作用范围：仓库根目录及其所有子目录。若子目录未来出现更近的 `AGENTS.md`，以更近文件为准。

---

## 1. 项目定位

本项目是 **洛克王国世界 PVP 战斗信息获取与敌方配置推算系统**。

当前阶段：前后端可联调的纯手动输入 MVP 已基本成型，正在补齐：

1. 正式状态定义数据；
2. 真实伤害公式；
3. 候选过滤与证据链；
4. 速度判断；
5. 事件重放重算。

开发时必须优先保证：

- 事件流稳定；
- 状态快照可追溯；
- 候选推算不被错误公式污染；
- 本地静态规则数据导入流程可 dry-run、可解释、可回滚。

---

## 2. 开发前必须阅读的文件

接手任务前，至少先看：

1. `README.md`：项目现状、启动方式、目录结构。
2. `PROJECT_STATUS.md`：当前完成度和未完成项。
3. 与任务相关的设计文档：
   - 接口：`docs/03_系统设计/前后端接口文档.md`
   - 数据库：`docs/03_系统设计/SQLite数据库设计.md`
   - 主设计：`docs/03_系统设计/洛克王国世界 PVP 战斗信息获取与敌方配置推算系统设计文档 v0.4.1.md`
   - 伤害/状态：`docs/03_系统设计/伤害计算与状态结算集成设计_v0.1.md`
4. 任务涉及的现有代码模块，避免重复造轮子。

不要只凭文件名猜测实现；修改前应查看实际代码。

---

## 3. 技术栈与目录职责

### 3.1 后端

- 技术栈：FastAPI、SQLAlchemy 2.x、Pydantic v2、SQLite、Alembic。
- 目录：`backend/app/`
  - `api/`：路由聚合和 HTTP 层。
  - `schemas/`：Pydantic 输入输出结构。
  - `models/`：SQLAlchemy ORM。
  - `services/`：业务流程、事务协调。
  - `calculation/`：面板、速度、伤害等纯计算或计算入口。
  - `inference/`：候选推算与过滤。
  - `data_pipeline/`：BWIKI 数据爬取、清洗、导入。
  - `db/`：数据库会话和初始化。
  - `tests/`：后端测试。

### 3.2 前端

- 技术栈：React、TypeScript、Vite、TanStack Query、Zustand、Tailwind CSS。
- 目录：`frontend/src/`
  - `pages/`：页面级组件。
  - `components/`：通用组件。
  - `lib/`：API 客户端、工具函数。
  - `store/`：客户端状态。
  - `types/`：前端类型定义。

### 3.3 文档与数据

- `docs/`：需求、规格、系统设计、附件。
- `data/`：本地数据库和爬虫数据。不要随意删除、重建或提交大体积/敏感数据。
- `scripts/`：开发脚本。

---

## 4. 总体开发原则

1. **小步提交式修改**：每次只改与任务相关的最小范围。
2. **先复用后新增**：优先复用已有 service、schema、model、工具函数。
3. **业务语义优先**：战斗、状态、候选、公式相关命名要清晰表达领域含义。
4. **不要引入伪公式**：伤害、速度、候选排除等未确认规则必须显式标记为占位或低置信度。
5. **可解释优先**：推算结果要能给出证据链、上下文和未确定因素。
6. **接口稳定优先**：前后端已联调接口不要随意破坏；确需变更时同步 schema、前端类型、接口文档。
7. **状态快照优先**：历史事件解释必须基于事件发生时的 `BattleEffectSnapshot`，不能读取已变化的当前状态冒充历史状态。
8. **dry-run 优先**：涉及数据导入、清理、批量更新时，必须保留或优先使用 dry-run。

---

## 5. 后端编码规范

### 5.1 风格

- Python 目标版本：3.12+。
- 使用类型标注，优先 `str | None`、`list[str]` 这类现代写法。
- 遵循 Ruff 配置：行宽 100，规则 `E/F/I/UP/B`。
- 模块、类、复杂函数应保留中文 docstring，与现有项目风格一致。
- API 层只做参数校验、错误码转换和 service 调用；不要把复杂业务写进 endpoint。
- Service 层负责事务、跨表协调和业务流程。
- Calculation 层尽量保持纯函数化，不直接依赖数据库会话。

### 5.2 数据库与事务

- ORM 模型改动通常需要 Alembic 迁移。
- 不要手工直接修改 `data/app.db` 作为正式方案。
- 大批量导入应支持 dry-run，并输出新增、更新、跳过、错误统计。
- 软删除字段存在时，优先遵守现有软删除语义。
- 归档战斗默认保留历史数据；物理清理必须显式 dry-run/confirm。

### 5.3 Schema 与 JSON 字段

- Pydantic schema 字段要带必要的 `Field(description=...)`。
- JSON 字段变更时，要同步：
  1. 后端 schema；
  2. 前端 `frontend/src/types/api.ts`；
  3. 接口文档；
  4. 必要的兼容读取逻辑。
- 对于 `damage_rule_json`、`hit_rule_json`、`formula_hooks_json` 等规则 JSON，不要只写自由文本；应尽量形成结构化字段。

---

## 6. 前端编码规范

- 使用 TypeScript，避免 `any`；确实未知时优先 `unknown` 或明确的 `Record<string, unknown>`。
- API 调用统一放在 `frontend/src/lib/api.ts` 或其拆分模块中。
- 后端响应类型统一维护在 `frontend/src/types/api.ts`。
- 页面组件放 `pages/`，可复用 UI 放 `components/`。
- 样式优先使用 Tailwind；已有 `Button`、布局组件等要优先复用。
- 不要在页面里硬编码复杂 API URL；使用封装好的 `api` 客户端。
- 修改接口后必须跑类型检查或说明未跑原因。

---

## 7. 伤害公式、状态与候选推算专项规则

这是当前项目最容易出错的区域，必须特别谨慎。

### 7.1 伤害公式

- 实现前先对齐 `docs/03_系统设计/伤害计算与状态结算集成设计_v0.1.md`。
- 真实公式未验证前，不要开启候选硬排除。
- 计算结果应包含解释链，例如：攻击/防御属性、显示威力、克制倍率、本系倍率、天气倍率、减伤乘积、未知因素、取整策略。
- 不稳定加成未知时，应返回范围或 `unknown_factors`，不要强行按 1.0 排除候选。
- 连击优先比较单段伤害；总伤害用于生命扣减和击杀判断。

### 7.2 状态系统

- 异常、印记、天气、属性变化都统一走 `BattleEffectInstance` / `EffectDefinition`，不要新增平行的状态表或天气表。
- 历史计算使用 `BattleEffectSnapshot.full_snapshot_json`。
- 切换、清除、叠层、转换、驱散都应记录 `EffectChangeEvent`。
- 状态结算顺序、回合阶段、层数变化必须显式写入规则或代码注释。

### 7.3 候选推算

- 初期只做软评分：更新 `match_score`、`confidence`、证据链，不轻易 `is_excluded = true`。
- 硬排除必须满足：技能确认、双方确认、状态快照完整、公式已验证、无未知关键因素。
- 候选证据应能解释“为什么保留/为什么排除”。

---

## 8. 数据管线规则

- BWIKI/rocom 数据管线位于 `backend/app/data_pipeline/rocom/`。
- 爬取、清洗、导入要保持分层：raw -> cleaned -> dry-run -> commit。
- 普通后端启动不应自动大规模爬取或写入静态规则，除非配置显式开启。
- 新增导入器时必须提供：
  1. 输入格式说明；
  2. dry-run；
  3. 错误列表；
  4. 导入摘要；
  5. 幂等策略。

---

## 9. 测试与验证命令

### 9.1 后端

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m pytest -q
python -m ruff check app
```

### 9.2 前端

PowerShell 下优先使用 `npm.cmd`：

```powershell
cd frontend
npm.cmd install --no-audit --no-fund
npm.cmd run typecheck
npm.cmd run build
```

### 9.3 运行服务

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

```powershell
cd frontend
npm.cmd run dev
```

如果因为本地依赖缺失、网络或环境问题无法运行测试，必须在最终回复中说明：

- 尝试了什么命令；
- 失败原因；
- 哪些验证尚未完成。

---

## 10. 文档同步规则

以下改动必须同步文档：

1. API 入参/响应变化：更新 `docs/03_系统设计/前后端接口文档.md`。
2. 数据库结构变化：更新 `docs/03_系统设计/SQLite数据库设计.md`，并新增 Alembic 迁移。
3. 伤害、状态、候选推算规则变化：更新相关系统设计文档。
4. 项目阶段性完成/未完成状态变化：更新 `PROJECT_STATUS.md`。
5. 启动方式、依赖、环境变量变化：更新 `README.md` 或启动文档。

文档语言以中文为主，术语应与现有文档保持一致。

---

## 11. 安全与数据保护

- 不要提交 `.env`、密钥、令牌、Cookie、个人账号信息。
- 不要随意删除 `data/app.db`、`data/rocom/` 或用户本地数据。
- 批量删除、清理、重建数据库前必须明确说明影响范围，并优先提供 dry-run。
- 不要用破坏性命令绕过正常迁移或导入流程。
- 不要把大型生成文件、缓存、`node_modules`、`__pycache__` 作为开发成果提交。

---

## 12. 任务完成后的回复要求

完成任务后，回复应包含：

1. 改了哪些文件；
2. 实现了什么能力或修复了什么问题；
3. 跑了哪些验证命令；
4. 如果没跑测试，说明原因；
5. 后续建议或风险点。

回复保持简洁，但不要省略关键风险。
