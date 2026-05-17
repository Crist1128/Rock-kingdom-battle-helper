# 洛克王国 BWIKI 数据更新模块

本模块用于把 BWIKI 精灵数据接入后端数据库。当前版本已调整为 **raw JSON → cleaned JSON → 数据库导入**，不再生成或依赖 `sprites.csv`、`skills.csv`、`urls.csv` 作为正式流程。默认数据目录使用项目根目录下与 `backend/` 同级的 `data/`。

## 推荐架构

MVP 阶段建议采用：

1. **主动更新接口**：由管理员手动触发，适合版本更新、数据修正后执行。
2. **可选被动更新**：通过环境变量开启服务启动时自动触发一次更新，但默认关闭。
3. **不把爬虫暴露为普通业务接口**：爬虫会访问外部站点、耗时较长、失败概率比普通查询接口高，应归类为管理/运维能力。

## 数据落盘位置

默认使用你项目里已经存在的、与 `backend/` 同级的 `data/` 目录：

```text
project-root/
├── backend/
└── data/
    ├── app.db
    └── rocom/
        ├── raw/
        │   ├── sprites_raw.json
        │   └── image_urls.json
        └── cleaned/
            ├── elves.json
            ├── skills.json
            ├── elf_learnable_skills.json
            └── type_effectiveness_rules.json
```

实现上通过 `app/core/config.py` 按代码位置解析路径，不再依赖当前命令从哪个目录启动。`DATABASE_URL=sqlite:///../data/app.db` 和 `ROCOM_DATA_DIR=../data/rocom` 这类相对路径会按 `backend/` 目录解析。

如需换目录，可在 `backend/.env` 里覆盖：

```env
DATABASE_URL=sqlite:///../data/app.db
ROCOM_DATA_DIR=../data/rocom
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `scraper.py` | 爬取 BWIKI，输出 `sprites_raw.json` 和 `image_urls.json`。默认不下载图片。 |
| `cleaner.py` | 从 raw JSON 清洗出 `elves.json`、`skills.json`、`elf_learnable_skills.json`、`type_effectiveness_rules.json`。 |
| `importer.py` | 把 cleaned JSON 或 raw JSON 导入数据库；默认 dry-run。 |

历史 CSV 入口在 `cleaner.py` / `importer.py` 中保留，仅用于兼容旧数据，不作为新流程使用。

## 主动接口

接口位置：

```text
POST /api/v1/admin/data-updates/rocom/sync
GET  /api/v1/admin/data-updates/rocom/jobs/{job_id}
GET  /api/v1/admin/data-updates/rocom/jobs
```

默认请求不会提交数据库事务，属于 dry-run：

```json
{
  "commit": false,
  "force": false,
  "limit": 0,
  "delay": 1.5,
  "with_images": false,
  "data_version": null,
  "write_artifacts": true
}
```

确认要写库时：

```json
{
  "commit": true,
  "force": true,
  "limit": 0,
  "delay": 1.5,
  "with_images": false,
  "data_version": "rocom_bwiki_20260516",
  "write_artifacts": true
}
```

如果配置了 `ADMIN_UPDATE_TOKEN`，请求需要带：

```text
X-Admin-Token: <你的 token>
```

## 被动更新

默认关闭。需要时在 `.env` 中开启：

```env
ROCOM_AUTO_UPDATE_ON_STARTUP=false
ROCOM_AUTO_UPDATE_COMMIT=false
ROCOM_AUTO_UPDATE_FORCE=false
ROCOM_AUTO_UPDATE_LIMIT=0
ROCOM_AUTO_UPDATE_WITH_IMAGES=false
ROCOM_UPDATE_DELAY=1.5
```

建议 MVP 阶段保持 `ROCOM_AUTO_UPDATE_ON_STARTUP=false`，避免每次启动都访问外部站点和改动数据库。上线后可以用 GitHub Actions、crontab、后台 worker 或调度服务定期调用主动接口。

## CLI 用法

爬取并清洗：

```bash
cd backend
python -m app.data_pipeline.rocom.scraper \
  --output ../data/rocom/raw/sprites_raw.json \
  --clean-output-dir ../data/rocom/cleaned
```

只清洗 raw JSON：

```bash
python -m app.data_pipeline.rocom.cleaner \
  --raw-json ../data/rocom/raw/sprites_raw.json \
  --image-urls-json ../data/rocom/raw/image_urls.json \
  --output-dir ../data/rocom/cleaned
```

导入数据库，先 dry-run：

```bash
python -m app.data_pipeline.rocom.importer \
  --cleaned-dir ../data/rocom/cleaned
```

确认后提交：

```bash
python -m app.data_pipeline.rocom.importer \
  --cleaned-dir ../data/rocom/cleaned \
  --commit
```

## 图片策略

MVP 阶段默认不下载图片，只记录远程 URL 到 `image_urls.json`。如需要下载：

```bash
python -m app.data_pipeline.rocom.scraper --with-images
```

下载目录位于 `data/rocom/raw/images/`，已通过 `.gitignore` 排除。

## Git 注意事项

数据库、爬虫 raw/cleaned 产物、图片和 `.env` 不应提交。已在 `.gitignore` 中加入：

```text
data/
*.db
*.sqlite*
*.db-wal
*.db-shm
**/data/rocom/raw/
**/data/rocom/cleaned/
**/data/rocom/images/
.env
.env.*
```
