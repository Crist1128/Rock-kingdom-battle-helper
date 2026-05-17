"""
洛克王国 BWIKI 精灵数据爬虫（后端数据管线版）

目标: https://wiki.biligame.com/rocom/精灵图鉴
输出:
  - data/rocom/raw/sprites_raw.json      原始爬取数据（精灵基础数据 + 技能 + 克制关系）
  - data/rocom/raw/image_urls.json       图片 URL 元数据；MVP 默认仅记录 URL，不下载图片
  - data/rocom/cleaned/*.json            后端数据库可导入的清洗数据
  - data/rocom/raw/images/               可选下载图片目录，默认不下载

注意：本版本不再生成 sprites.csv / skills.csv / urls.csv。CSV 只作为历史兼容格式保留在 cleaner 中。

推荐使用方法（在 backend 目录执行）:
    pip install -e '.[crawler]'
    python -m app.data_pipeline.rocom.scraper --output ../data/rocom/raw/sprites_raw.json

MVP 阶段默认不下载图片，仅记录图片 URL。如确需下载图片，显式传入 --with-images。

可选参数:
    --limit N             只爬前 N 只精灵（调试用）
    --delay 1.5           每次请求间隔下限秒数，实际为 delay~delay+1.5 随机值
    --output xxx          原始 JSON 输出路径，默认 data/raw/sprites_raw.json
    --clean-output-dir    清洗后 JSON 输出目录，默认 data/cleaned
    --skip-clean          只输出原始爬虫数据，不执行清洗
    --data-version        写入清洗数据的版本号，如 rocom_bwiki_20260516
    --with-images         下载图片；默认不下载，只记录 URL
    --force               强制重爬所有精灵；若开启 --with-images 也会强制图片重下
    --debug-images        打印图片 URL、保存路径、缓存命中、下载失败等调试信息
    --repair-images       只在 --with-images 模式下补下载缺失图片
"""

# ==================== 标准库导入 ====================
import re
import csv
import json
import time
import random
import argparse
import os
import shutil
import hashlib
from pathlib import Path
from urllib.parse import urljoin, unquote

# ==================== 第三方库导入 ====================
import requests
from bs4 import BeautifulSoup

# ==================== 全局配置 ====================

# 基础URL配置
BASE_URL = "https://wiki.biligame.com"
LIST_URL = "https://wiki.biligame.com/rocom/%E7%B2%BE%E7%81%B5%E5%9B%BE%E9%89%B4"

# HTTP请求头，模拟浏览器访问
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://wiki.biligame.com/rocom/",
}

# 请求间隔配置：随机 1.5~3 秒（可通过 --delay 参数覆盖下限）
_DELAY_MIN = 1.5
_DELAY_MAX = 3.0

# 创建全局 Session 对象，复用连接和 Cookie
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ==================== 图片下载相关全局变量 ====================

# 图片类型到子目录的映射
IMAGE_DIRS = {
    "sprite":    "images/sprites",    # 精灵立绘
    "attribute": "images/attributes", # 属性图标
    "skill":     "images/skills",     # 技能图标
    "ability":   "images/abilities",  # 特性图标
    "matchup":   "images/matchup",    # 克制表属性图标
}

# URL 缓存，用于图片去重和断点续传
_urls_cache: dict[str, dict] = {}   # url -> row
_urls_path: Path | None = None
_IMAGE_DEBUG = False
DOWNLOAD_IMAGES = False

# urls.csv 的列定义
URL_COLUMNS = ["name", "type", "url", "local_path", "status", "bytes", "content_type", "error"]


# ==================== 图片下载工具函数 ====================

def _debug_image(msg: str) -> None:
    """
    图片下载调试日志。

    使用 --debug-images 参数开启调试输出。

    Args:
        msg: 调试消息
    """
    if _IMAGE_DEBUG:
        print(f"\n  [IMG-DEBUG] {msg}", flush=True)


def _normalize_img_url(url: str) -> str:
    """
    规范化图片URL。

    把图片地址统一转成绝对 URL，避免 requests 直接请求相对路径失败。

    Args:
        url: 原始图片URL（可能是相对路径）

    Returns:
        str: 绝对 URL
    """
    return urljoin(BASE_URL, url.strip()) if url else ""


def _ensure_image_dirs(data_dir: Path) -> None:
    """
    确保图片目录存在。

    启动时创建所有图片子目录，让用户即使还没下载图片也能看到目录位置。

    Args:
        data_dir: 数据根目录
    """
    for sub in IMAGE_DIRS.values():
        (data_dir / sub).mkdir(parents=True, exist_ok=True)


def _best_img_src(img) -> str:
    """
    从 img 标签提取最佳图片来源。

    优先取 srcset/data-srcset 中分辨率最高的地址，否则退回 data-src/src。

    Args:
        img: BeautifulSoup img 标签对象

    Returns:
        str: 最佳图片URL
    """
    if not img:
        return ""

    # 尝试从 srcset 获取最高分辨率图片
    srcset = img.get("srcset") or img.get("data-srcset") or ""
    candidates: list[tuple[float, str]] = []
    if srcset:
        for part in srcset.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            candidate = bits[0]
            score = 1.0
            if len(bits) > 1:
                marker = bits[1].lower()
                try:
                    if marker.endswith("w"):
                        score = float(marker[:-1])
                    elif marker.endswith("x"):
                        score = float(marker[:-1]) * 1000
                except ValueError:
                    pass
            candidates.append((score, candidate))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    # 回退到普通 src 属性
    return img.get("data-src") or img.get("src") or ""


def _guess_image_extension(url: str, content_type: str = "") -> str:
    """
    推断图片扩展名。

    从 Content-Type 或 URL 中推断图片扩展名。

    Args:
        url: 图片URL
        content_type: HTTP Content-Type 头

    Returns:
        str: 扩展名（不含点）
    """
    # 首先尝试从 Content-Type 推断
    ctype = (content_type or "").split(";")[0].strip().lower()
    content_type_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/svg+xml": "svg",
    }
    if ctype in content_type_map:
        return content_type_map[ctype]

    # 从 URL 推断
    cleaned = url.split("?")[0].split("#")[0]
    filename = cleaned.rsplit("/", 1)[-1]
    m = re.search(r"\.([A-Za-z0-9]{2,5})$", filename)
    if m:
        ext = m.group(1).lower()
        if ext in {"png", "jpg", "jpeg", "webp", "gif", "svg"}:
            return "jpg" if ext == "jpeg" else ext
    return "png"


def _make_image_local_path(name: str, img_type: str, url: str, ext: str) -> str:
    """
    生成图片本地保存路径。

    生成稳定且不容易重名的本地图片相对路径。

    Args:
        name: 图片名称（用于文件名）
        img_type: 图片类型
        url: 原始URL（用于生成唯一hash）
        ext: 扩展名

    Returns:
        str: 相对路径
    """
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "unnamed"
    safe_name = safe_name[:80]  # 避免文件名过长
    url_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{IMAGE_DIRS[img_type]}/{safe_name}_{url_hash}.{ext}"


def _init_urls(out_path: Path) -> None:
    """
    初始化 URL 缓存。

    加载已有的 urls.csv 到内存缓存，支持断点续传和去重。

    Args:
        out_path: 输出文件路径
    """
    global _urls_path, _urls_cache
    _urls_path = out_path.parent / "image_urls.json"
    _urls_cache = {}
    _debug_image(f"image_urls.json 路径: {_urls_path.resolve()}")
    if _urls_path.exists():
        try:
            loaded = json.loads(_urls_path.read_text(encoding="utf-8"))
            rows = loaded.values() if isinstance(loaded, dict) else loaded
            for row in rows:
                normalized_url = _normalize_img_url(row.get("url", ""))
                if normalized_url:
                    row["url"] = normalized_url
                    _urls_cache[normalized_url] = row
        except Exception as e:
            _debug_image(f"image_urls.json 读取失败，将重新生成: {e}")

    # 历史兼容：如果旧 urls.csv 存在，则可读入但不再继续写 CSV。
    legacy_csv = out_path.parent / "urls.csv"
    if legacy_csv.exists() and not _urls_cache:
        with open(legacy_csv, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                normalized_url = _normalize_img_url(row.get("url", ""))
                if normalized_url:
                    row["url"] = normalized_url
                    _urls_cache[normalized_url] = row
    _debug_image(f"已加载图片URL缓存: {len(_urls_cache)} 条")


def _add_url(name: str, img_type: str, url: str, data_dir: Path, force: bool = False, download: bool | None = None) -> str:
    """
    添加并下载图片。

    记录一条图片 URL；本地文件不存在时下载，返回 data_dir 下的相对路径。

    Args:
        name: 图片名称
        img_type: 图片类型
        url: 图片URL
        data_dir: 数据目录
        force: 是否强制重新下载

    Returns:
        str: 本地相对路径
    """
    if not url:
        _debug_image(f"跳过空图片URL: name={name!r}, type={img_type!r}")
        return ""

    if download is None:
        download = DOWNLOAD_IMAGES

    if img_type not in IMAGE_DIRS:
        _debug_image(f"未知图片类型，跳过: name={name!r}, type={img_type!r}, url={url!r}")
        return ""

    original_url = url
    url = _normalize_img_url(url)
    if original_url != url:
        _debug_image(f"图片URL已转绝对路径: {original_url} -> {url}")

    if not download:
        row = {
            "name": name,
            "type": img_type,
            "url": url,
            "local_path": "",
            "status": "skipped",
            "bytes": "",
            "content_type": "",
            "error": "image_download_disabled",
        }
        _urls_cache[url] = row
        _flush_urls()
        _debug_image(f"MVP 默认不下载图片，仅记录 URL: {url}")
        return ""

    subdir = data_dir / IMAGE_DIRS[img_type]
    subdir.mkdir(parents=True, exist_ok=True)

    # 检查缓存
    cached = _urls_cache.get(url)
    if cached and not force:
        cached_local = cached.get("local_path", "")
        cached_abs = data_dir / cached_local if cached_local else None
        if cached_local and cached_abs and cached_abs.exists() and cached_abs.stat().st_size > 0:
            _debug_image(f"缓存命中，文件存在，跳过下载: {url} -> {cached_abs.resolve()} ({cached_abs.stat().st_size} bytes)")
            return cached_local
        _debug_image(f"缓存存在但本地文件缺失/为空，重新下载: {url}, cached_local={cached_local!r}")

    # 准备下载
    guessed_ext = _guess_image_extension(url)
    local_path = cached.get("local_path") if cached and cached.get("local_path") else _make_image_local_path(name, img_type, url, guessed_ext)
    abs_path = data_dir / local_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    _debug_image(f"准备下载: name={name!r}, type={img_type!r}")
    _debug_image(f"URL: {url}")
    _debug_image(f"保存目录: {abs_path.parent.resolve()}")
    _debug_image(f"保存文件: {abs_path.resolve()}")

    status = ""
    size = ""
    content_type = ""
    error = ""

    # 下载图片
    if abs_path.exists() and abs_path.stat().st_size > 0 and not force:
        size = str(abs_path.stat().st_size)
        _debug_image(f"目标文件已存在，跳过下载: {abs_path.resolve()} ({size} bytes)")
    else:
        try:
            r = SESSION.get(url, timeout=20)
            status = str(r.status_code)
            content_type = r.headers.get("Content-Type", "")
            size = str(len(r.content))
            _debug_image(
                "响应: "
                f"status={status}, "
                f"content-type={content_type!r}, "
                f"bytes={size}"
            )
            r.raise_for_status()
            if not r.content:
                raise RuntimeError("响应内容为空")

            # 验证响应类型
            ctype_simple = content_type.split(";")[0].strip().lower()
            if ctype_simple and not ctype_simple.startswith("image/"):
                raise RuntimeError(f"响应不是图片，Content-Type={content_type!r}")

            # 如果 Content-Type 显示的扩展名和 URL 猜测不同，修正文件后缀
            real_ext = _guess_image_extension(url, content_type)
            if real_ext != guessed_ext and not (cached and cached.get("local_path")):
                local_path = _make_image_local_path(name, img_type, url, real_ext)
                abs_path = data_dir / local_path
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                _debug_image(f"根据 Content-Type 修正保存文件: {abs_path.resolve()}")

            abs_path.write_bytes(r.content)
            size = str(abs_path.stat().st_size)
            _debug_image(f"下载成功: {abs_path.resolve()} ({size} bytes)")
        except Exception as e:
            error = str(e)
            print(f"\n  [!] 图片下载失败 {url}: {e}")
            _debug_image(f"失败保存路径本应为: {abs_path.resolve()}")
            local_path = ""

    # 更新缓存
    row = {
        "name": name,
        "type": img_type,
        "url": url,
        "local_path": local_path,
        "status": status,
        "bytes": size,
        "content_type": content_type,
        "error": error,
    }
    _urls_cache[url] = row
    _flush_urls()
    return local_path


def _flush_urls() -> None:
    """刷新 URL 缓存到 JSON 文件，不再生成 urls.csv。"""
    if _urls_path is None:
        return
    rows = sorted(_urls_cache.values(), key=lambda row: (row.get("type", ""), row.get("name", ""), row.get("url", "")))
    _urls_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


# ==================== 工具函数 ====================

def print_progress(current: int, total: int, label: str = "", width: int = 28) -> None:
    """
    打印进度条。

    使用 \r 在同一行覆写，显示当前进度。

    Args:
        current: 当前进度
        total: 总数量
        label: 进度标签
        width: 进度条宽度
    """
    filled = int(width * current / total) if total > 0 else 0
    bar = "#" * filled + "-" * (width - filled)
    pct = current / total * 100 if total > 0 else 0
    label = (label[:32] + "…") if len(label) > 33 else label
    print(f"\r[{current:>4}/{total}] {bar} {pct:5.1f}%  {label}    ", end="", flush=True)
    if current >= total:
        print()


def fetch(url: str, retries: int = 3) -> BeautifulSoup:
    """
    抓取页面并解析。

    失败时采用递增等待：第1次10s，第2次20s，第3次30s。
    567（反爬限制）单独提示。

    Args:
        url: 要抓取的 URL
        retries: 重试次数

    Returns:
        BeautifulSoup: 解析后的页面

    Raises:
        RuntimeError: 重试次数用尽后仍失败
    """
    retry_waits = [10, 20, 30]

    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=15)
            if resp.status_code == 567:
                wait = retry_waits[min(attempt, len(retry_waits) - 1)]
                print(f"\n  [!] 触发反爬限制 (567)，等待 {wait}s 后重试 "
                      f"({attempt+1}/{retries})...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.HTTPError as e:
            wait = retry_waits[min(attempt, len(retry_waits) - 1)]
            print(f"\n  [!] HTTP 错误 ({attempt+1}/{retries}): {e}，等待 {wait}s...")
            time.sleep(wait)
        except requests.RequestException as e:
            wait = retry_waits[min(attempt, len(retry_waits) - 1)]
            print(f"\n  [!] 请求失败 ({attempt+1}/{retries}): {e}，等待 {wait}s...")
            time.sleep(wait)

    raise RuntimeError(f"无法抓取（已重试 {retries} 次）: {url}")


def img_alt_to_attr(alt: str) -> str:
    """
    从图片 alt 文本提取属性名。

    例如 '图标 宠物 属性 光.png' -> '光'

    Args:
        alt: 图片 alt 文本

    Returns:
        str: 提取的属性名
    """
    m = re.search(r'属性\s+(\S+?)(?:\.png)?$', alt)
    return m.group(1) if m else alt.strip()


# ==================== 列表页解析 ====================

def parse_list_page() -> list[dict]:
    """
    解析精灵图鉴列表页。

    返回精灵基本信息列表，包含编号、名称、形态、URL等。

    Returns:
        list[dict]: 精灵信息列表
    """
    print(f"[*] 抓取列表页: {LIST_URL}")
    soup = fetch(LIST_URL)

    entries = []
    content = soup.find("div", id="mw-content-text") or soup
    # 每个精灵是 <a href="/rocom/NAME"><span>NO.xxx</span>...</a>
    for a in content.find_all("a", href=re.compile(r'^/rocom/')):
        span = a.find("span", string=re.compile(r'^NO\.\d+'))
        if not span:
            continue
        no_m = re.search(r'NO\.(\d+)', span.get_text())
        if not no_m:
            continue
        no = int(no_m.group(1))

        href = a["href"]
        url = urljoin(BASE_URL, href)
        name_raw = unquote(href.split("/rocom/")[-1])

        # 解析形态（如 "精灵名（形态名）"）
        form_m = re.match(r'^(.+?)（(.+)）$', name_raw)
        if form_m:
            name = form_m.group(1)
            form = form_m.group(2)
        else:
            name = name_raw
            form = None

        has_shiny = "异色" in a.get_text()

        entries.append({
            "no": no,
            "name": name,
            "form": form,
            "url": url,
            "has_shiny": has_shiny,
        })

    print(f"[*] 共找到 {len(entries)} 条精灵记录")
    return entries


# ==================== 详情页解析 ====================

def parse_stat_block(soup: BeautifulSoup) -> dict:
    """
    解析种族值。

    从详情页提取精灵的六维种族资质。

    Args:
        soup: 解析后的页面

    Returns:
        dict: 六维种族资质
    """
    stats = {}
    stat_map = {
        "生命": "hp", "物攻": "atk", "魔攻": "sp_atk",
        "物防": "def", "魔防": "sp_def", "速度": "spd",
    }
    seen = set()
    for li in soup.find_all("li"):
        name_p = li.find("p", attrs={"class": "rocom_sprite_info_qualification_name"})
        if not name_p:
            continue
        stat_name = name_p.get_text(strip=True)
        if stat_name in stat_map and stat_name not in seen:
            nums = re.findall(r'\d+', li.get_text())
            if nums:
                stats[stat_map[stat_name]] = int(nums[-1])
                seen.add(stat_name)
    if len(stats) == 6:
        stats["total"] = sum(stats.values())
    return stats


def parse_ability(soup: BeautifulSoup) -> dict | None:
    """
    解析特性。

    从详情页提取精灵的特性名称和描述。

    Args:
        soup: 解析后的页面

    Returns:
        dict | None: 特性信息，不存在则返回 None
    """
    ability_header = soup.find(string=re.compile(r'^特性$'))
    if not ability_header:
        return None
    container = ability_header.find_parent()
    if not container:
        return None
    texts = [t.strip() for t in container.find_next_siblings(string=True) if t.strip()][:2]
    imgs = container.find_next_sibling()
    if not imgs:
        return None
    ability_name = imgs.get_text(strip=True) if imgs else ""
    ability_desc_node = imgs.find_next_sibling() if imgs else None
    ability_desc = ability_desc_node.get_text(strip=True) if ability_desc_node else ""
    img = container.find_next("img", alt=re.compile(r'^(?!图标|界面|页面)'))
    if img:
        ability_name = img.get("alt", ability_name).replace(".png", "")
    return {"name": ability_name, "description": ability_desc} if ability_name else None


def parse_type_matchup(soup: BeautifulSoup) -> dict:
    """
    解析克制关系。

    从详情页提取精灵的属性克制关系（克制、被克制、抵抗、被抵抗）。

    Args:
        soup: 解析后的页面

    Returns:
        dict: 克制关系
    """
    matchup = {
        "strong_against": [],   # 克制
        "weak_to": [],          # 被克制
        "resists": [],          # 抵抗
        "resisted_by": [],      # 被抵抗
    }
    label_map = {
        "克制": "strong_against",
        "被克制": "weak_to",
        "抵抗": "resists",
        "被抵抗": "resisted_by",
    }
    for label_cn, key in label_map.items():
        node = soup.find(string=re.compile(f'^{label_cn}$'))
        if not node:
            continue
        p = node.find_parent()
        if not p:
            continue
        container = p.find_parent()
        if not container:
            continue
        for img in container.find_all("img"):
            alt = img.get("alt", "")
            if "属性" in alt:
                matchup[key].append(img_alt_to_attr(alt))
    return matchup


def parse_skills(soup: BeautifulSoup, data_dir: Path | None = None, force: bool = False) -> list[dict]:
    """
    解析技能列表。

    从详情页提取精灵的技能信息，包括等级要求、威力、能耗等。

    Args:
        soup: 解析后的页面
        data_dir: 数据目录（用于下载图标）
        force: 是否强制重新下载

    Returns:
        list[dict]: 技能列表
    """
    skills = []
    skill_cost_imgs = soup.find_all("img", alt=re.compile(r'图标 技能 星星背景'))

    for cost_img in skill_cost_imgs:
        try:
            # 向上找技能容器块
            container = cost_img.find_parent()
            for _ in range(6):
                if container and container.get("class") and "rocom_sprite_skill_box" in container.get("class", []):
                    break
                if container and container.find("img", alt=re.compile(r'图标 宠物 属性')):
                    break
                container = container.find_parent() if container else None
            if not container:
                continue

            # 等级要求
            level = 0
            level_div = container.find(class_="rocom_sprite_skill_level")
            if level_div:
                lv_m = re.search(r'LV\s*(\d+)', level_div.get_text())
                if lv_m:
                    level = int(lv_m.group(1))

            # 属性图标
            attr_img = container.find("img", class_="rocom_sprite_skill_attr")
            if not attr_img:
                attr_img = container.find("img", alt=re.compile(r'图标 宠物 属性'))
            skill_attr = img_alt_to_attr(attr_img.get("alt", "")) if attr_img else "未知"

            # 技能图标 & 名称
            skill_icon = container.find("img", alt=re.compile(r'^技能图标'))
            if skill_icon:
                skill_name = skill_icon.get("alt", "").replace("技能图标 ", "").replace(".png", "")
                skill_icon_url = _best_img_src(skill_icon)
            else:
                skill_name = ""
                skill_icon_url = ""

            # 属性图标URL
            attr_icon_url = _best_img_src(attr_img) if attr_img else ""

            # 能量消耗
            cost_text = cost_img.find_next_sibling(string=True)
            cost = int(cost_text.strip()) if cost_text and cost_text.strip().isdigit() else 0

            # 类别
            category_img = container.find("img", alt=re.compile(r'图标 技能 类别'))
            if category_img:
                cat_m = re.search(r'类别\s+(\S+?)(?:\.png)?$', category_img.get("alt", ""))
                category = cat_m.group(1) if cat_m else ""
            else:
                category = ""

            # 威力
            power = 0
            power_div = container.find(class_="rocom_sprite_skill_power")
            if power_div:
                pt = power_div.get_text(strip=True)
                if pt.lstrip('-').isdigit():
                    power = int(pt)

            # 描述
            full_text = container.get_text(" ", strip=True)
            desc_m = re.search(r'✦(.+?)(?:$)', full_text)
            description = desc_m.group(1).strip() if desc_m else ""

            if not skill_name:
                continue

            # 下载图标
            skill_icon_path = ""
            attr_icon_path = ""
            if data_dir and skill_icon_url:
                skill_icon_path = _add_url(skill_name, "skill", skill_icon_url, data_dir, force)
            if data_dir and attr_icon_url:
                attr_icon_path = _add_url(skill_attr, "attribute", attr_icon_url, data_dir, force)

            skills.append({
                "name": skill_name,
                "attribute": skill_attr,
                "category": category,
                "cost": cost,
                "power": power,
                "level": level,
                "description": description,
                "skill_icon": skill_icon_path,
                "attribute_icon": attr_icon_path,
            })
        except Exception:
            continue

    # 去重
    seen = set()
    deduped = []
    for sk in skills:
        if sk["name"] not in seen:
            seen.add(sk["name"])
            deduped.append(sk)
    return deduped


def parse_attributes_from_detail(soup: BeautifulSoup) -> list[str]:
    """
    从详情页解析精灵属性。

    提取精灵的系别属性（可能有双属性）。

    Args:
        soup: 解析后的页面

    Returns:
        list[str]: 属性列表
    """
    header_area = soup.find("div", id="mw-content-text") or soup
    attrs = []
    stat_node = soup.find(string=re.compile(r'种族值'))
    if stat_node:
        before_stats = stat_node.find_parent()
        for img in soup.find_all("img", alt=re.compile(r'^图标 宠物 属性')):
            if before_stats and img in before_stats.find_all_previous("img"):
                continue
            attr = img_alt_to_attr(img.get("alt", ""))
            if attr and attr not in attrs:
                attrs.append(attr)
            if len(attrs) >= 2:
                break
    return attrs


def parse_evolution_chain(soup: BeautifulSoup) -> list[dict] | None:
    """
    解析进化链。

    提取精灵的进化链信息。

    Args:
        soup: 解析后的页面

    Returns:
        list[dict] | None: 进化链信息
    """
    box = soup.find("div", class_="rocom_spirit_evolution_box")
    if not box:
        return None

    stages = []
    for i in range(1, 4):
        div = box.find("div", class_=f"rocom_spirit_evolution_{i}")
        if not div:
            break
        a = div.find("a")
        if not a:
            break
        name = a.get("title", "")
        href = a.get("href", "")
        sprite_id = unquote(href.split("/rocom/")[-1]) if "/rocom/" in href else name
        stages.append({"name": name, "id": sprite_id})

    if len(stages) <= 1:
        return None

    level_divs = box.find_all("div", class_="rocom_spirit_evolution_level")
    levels = []
    for ld in level_divs:
        p = ld.find("p", class_="rocom_spirit_evolution_level_num")
        levels.append(p.get_text(strip=True) if p else None)

    rightbox = soup.find("div", class_="rocom_sprite_temp_evolve_rightBox")
    condition = None
    if rightbox:
        cond_p = rightbox.find("p", class_="rocom_evolution_data")
        if cond_p:
            condition = cond_p.get_text(strip=True)

    result = [{"name": stages[0]["name"], "no": None, "evolves_from": None, "level": None, "condition": None}]
    for i, stage in enumerate(stages[1:]):
        level = levels[i] if i < len(levels) else None
        cond = condition if i == len(stages) - 2 else None
        result.append({"name": stage["name"], "no": None, "evolves_from": stages[i]["name"], "level": level, "condition": cond})

    return result


def parse_sprite_detail(entry: dict, data_dir: Path | None = None, force: bool = False) -> dict:
    """
    爬取并解析单个精灵的详情页。

    提取精灵的完整信息，包括种族值、技能、特性、克制关系等。

    Args:
        entry: 精灵基本信息
        data_dir: 数据目录
        force: 是否强制重新下载

    Returns:
        dict: 精灵完整信息
    """
    soup = fetch(entry["url"])
    content = soup.find("div", id="mw-content-text") or soup

    stats = parse_stat_block(content)
    sprite_image_path = ""

    # 属性图标
    attrs = []
    h1 = soup.find("h1")
    if h1:
        for img in h1.find_all_next("img", limit=10):
            alt = img.get("alt", "")
            if "图标 宠物 属性" in alt:
                a = img_alt_to_attr(alt)
                if a and a not in attrs:
                    attrs.append(a)
            if len(attrs) >= 2:
                break

    # 特性
    ability = None
    ability_section = content.find(string=re.compile(r'^特性$'))
    if ability_section:
        p = ability_section.find_parent()
        if p:
            nxt = p.find_next("img", alt=re.compile(r'^(?!图标|界面|页面)'))
            if nxt:
                ability_name = nxt.get("alt", "").replace(".png", "")
                desc_node = nxt.find_next(string=re.compile(r'.{5,}'))
                ability_desc = desc_node.strip() if desc_node else ""
                ability_icon_url = _best_img_src(nxt)
                ability_icon_path = ""
                if data_dir and ability_icon_url and ability_name:
                    ability_icon_path = _add_url(ability_name, "ability", ability_icon_url, data_dir, force)
                ability = {"name": ability_name, "description": ability_desc, "icon": ability_icon_path}

    # 精灵立绘
    if data_dir:
        grament_div = content.find("div", class_="rocom_sprite_grament_img")
        if grament_div:
            sprite_img = grament_div.find("img")
            if sprite_img:
                sprite_url = _best_img_src(sprite_img)
                sprite_label = f"{entry['name']}{'_'+entry['form'] if entry.get('form') else ''}"
                if sprite_url:
                    sprite_image_path = _add_url(sprite_label, "sprite", sprite_url, data_dir, force)

        # 克制表属性图标
        matchup_section = content.find(string=re.compile(r'^克制$'))
        if matchup_section:
            matchup_container = matchup_section.find_parent()
            if matchup_container:
                outer = matchup_container.find_parent()
                if outer:
                    for img in outer.find_all("img"):
                        alt = img.get("alt", "")
                        if "属性" in alt:
                            attr_name = img_alt_to_attr(alt)
                            src = _best_img_src(img)
                            if src and attr_name:
                                _add_url(attr_name, "matchup", src, data_dir, force)

    # 进化链
    evolution_chain = parse_evolution_chain(content)

    matchup = parse_type_matchup(content)
    skills = parse_skills(content, data_dir, force)

    return {
        **entry,
        "sprite_image": sprite_image_path,
        "attributes": attrs,
        "stats": stats,
        "ability": ability,
        "type_matchup": matchup,
        "evolution_chain": evolution_chain,
        "skills": skills,
    }


# ==================== 主流程 ====================

def scrape_rocom_sprites(
    *,
    output: str | Path = "data/rocom/raw/sprites_raw.json",
    limit: int = 0,
    delay: float = 1.5,
    with_images: bool = False,
    force: bool = False,
    debug_images: bool = False,
    repair_images: bool = False,
) -> dict:
    """
    执行爬取并返回原始 JSON 数据。

    本函数供 CLI、后端接口和被动更新任务复用。它只产出 JSON，不再生成 CSV。
    """
    global _IMAGE_DEBUG, DOWNLOAD_IMAGES
    _IMAGE_DEBUG = debug_images
    DOWNLOAD_IMAGES = with_images

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir = out_path.parent
    if with_images:
        _ensure_image_dirs(data_dir)

    _init_urls(out_path)

    if repair_images and not with_images:
        print("[!] --repair-images 需要同时使用 --with-images；当前将忽略补图模式。")
        repair_images = False

    if force:
        for p in [data_dir / "image_urls.json", data_dir / "failed_urls.txt"]:
            if p.exists():
                _debug_image(f"--force 删除旧文件: {p.resolve()}")
                p.unlink()
        _urls_cache.clear()

    existing: dict[tuple, dict] = {}
    if out_path.exists() and not force:
        with open(out_path, encoding="utf-8") as f:
            for d in json.load(f):
                existing[(d["no"], d["name"], d.get("form"))] = d

    try:
        entries = parse_list_page()
    except RuntimeError as e:
        print(f"\n[!] 无法连接 wiki: {e}")
        print("[!] 可能是网络问题或服务器限速，请稍后重试")
        raise

    if limit > 0:
        entries = entries[:limit]
        print(f"[*] 限制模式: 只处理前 {limit} 只")

    results = []
    failed = []
    skipped = 0
    repaired_images = 0

    for i, entry in enumerate(entries, 1):
        key = (entry["no"], entry["name"], entry.get("form"))
        name_display = f"{entry['name']}{'（'+entry['form']+'）' if entry['form'] else ''}"
        print_progress(i, len(entries), f"NO.{entry['no']:03d} {name_display}")

        if key in existing and not repair_images:
            _debug_image(f"跳过已有精灵: NO.{entry['no']:03d} {name_display}")
            results.append(existing[key])
            skipped += 1
            continue

        if key in existing and repair_images:
            _debug_image(f"补下载已有精灵图片: NO.{entry['no']:03d} {name_display}")
            try:
                repaired_data = parse_sprite_detail(entry, data_dir, False)
                merged = dict(existing[key])
                merged["sprite_image"] = repaired_data.get("sprite_image", merged.get("sprite_image", ""))
                if repaired_data.get("ability"):
                    merged["ability"] = repaired_data["ability"]
                if repaired_data.get("skills"):
                    merged["skills"] = repaired_data["skills"]
                results.append(merged)
                skipped += 1
                repaired_images += 1
            except Exception as e:
                print(f"\n  [!] 补下载图片失败: {e}")
                results.append(existing[key])
                failed.append(entry["url"])
            time.sleep(random.uniform(delay, delay + 1.5))
            continue

        try:
            data = parse_sprite_detail(entry, data_dir, force)
            results.append(data)
            if i % 10 == 0:
                _save(results, out_path)
        except Exception as e:
            print(f"\n  [!] 失败: {e}")
            failed.append(entry["url"])

        time.sleep(random.uniform(delay, delay + 1.5))

    _backfill_evolution_ids(results)
    _save(results, out_path)
    image_rows = sorted(_urls_cache.values(), key=lambda row: (row.get("type", ""), row.get("name", ""), row.get("url", "")))
    _flush_urls()

    if failed:
        fail_path = out_path.with_name("failed_urls.txt")
        fail_path.write_text("\n".join(failed), encoding="utf-8")

    return {
        "sprites": results,
        "image_urls": image_rows,
        "output_path": str(out_path.resolve()),
        "image_urls_path": str((out_path.parent / "image_urls.json").resolve()),
        "failed_urls": failed,
        "stats": {
            "entries": len(entries),
            "sprites": len(results),
            "skipped": skipped,
            "repaired_images": repaired_images,
            "failed": len(failed),
            "with_images": with_images,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="洛克王国精灵数据爬虫（JSON/后端接口版）")
    parser.add_argument("--limit", type=int, default=0, help="只爬前N只 (0=全部)")
    parser.add_argument("--delay", type=float, default=1.5, help="请求间隔下限秒数，实际为 delay~delay+1.5 随机值")
    parser.add_argument("--output", default="data/rocom/raw/sprites_raw.json", help="原始 JSON 输出路径")
    parser.add_argument("--clean-output-dir", default="data/rocom/cleaned", help="清洗后 JSON 输出目录")
    parser.add_argument("--skip-clean", action="store_true", help="只输出原始 JSON，不执行清洗")
    parser.add_argument("--data-version", default=None, help="清洗数据版本号，如 rocom_bwiki_20260516")
    parser.add_argument("--with-images", action="store_true", help="下载图片；默认不下载，仅记录图片 URL")
    parser.add_argument("--force", action="store_true", help="强制重爬所有精灵；若开启 --with-images 也会强制图片重下")
    parser.add_argument("--debug-images", action="store_true", help="打印图片下载调试信息")
    parser.add_argument("--repair-images", action="store_true", help="只在 --with-images 模式下补下载缺失图片")
    return parser


def main() -> None:
    """CLI 入口：爬取 raw JSON，并可同步生成 cleaned JSON。"""
    args = build_parser().parse_args()
    result = scrape_rocom_sprites(
        output=args.output,
        limit=args.limit,
        delay=args.delay,
        with_images=args.with_images,
        force=args.force,
        debug_images=args.debug_images,
        repair_images=args.repair_images,
    )
    print(f"\n[完成] JSON 已保存至: {result['output_path']}")
    print(f"[完成] 图片 URL 元数据已保存至: {result['image_urls_path']}")

    if not args.skip_clean:
        try:
            from app.data_pipeline.rocom.cleaner import clean_from_raw_sprites, write_cleaned_dataset

            dataset = clean_from_raw_sprites(
                result["sprites"],
                image_url_rows=result["image_urls"],
                data_version=args.data_version,
                image_mode="local" if args.with_images else "remote",
            )
            write_cleaned_dataset(dataset, args.clean_output_dir)
            print(f"[完成] 清洗数据已保存至: {Path(args.clean_output_dir).resolve()}")
            if dataset.warnings:
                print(f"[提示] 清洗警告 {len(dataset.warnings)} 条，详见 import_summary.json")
        except Exception as e:
            print(f"[!] 清洗步骤失败，原始爬虫数据已保存，可单独运行 cleaner/importer: {e}")


def _backfill_evolution_ids(results: list) -> None:
    """
    回填进化链中的编号。

    用名字到编号的映射回填进化链中的 no 字段。

    Args:
        results: 精灵数据列表
    """
    name_to_no = {}
    for s in results:
        if not s.get("name"):
            continue
        name_to_no[s["name"]] = s["no"]
        if s.get("form"):
            name_to_no[f"{s['name']}（{s['form']}）"] = s["no"]
    for s in results:
        for stage in (s.get("evolution_chain") or []):
            stage["no"] = name_to_no.get(stage["name"])


def _save(data: list, path: Path) -> None:
    """
    保存数据到 JSON 文件。

    Args:
        data: 数据列表
        path: 输出路径
    """
    if path.exists():
        shutil.copy2(path, path.with_suffix(".backup.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
