"""基于透明模板库的敌方精灵头像识别原型。

本模块按《Codex_敌方精灵头像视觉识别复现说明.md》实现：

1. 只做像素级视觉匹配，不读取截图文字；
2. 默认对模板做水平镜像，支持 none / enemy / both 三种模式；
3. 依照固定准备页布局裁剪敌方 6 个头像 ROI；
4. 使用 Alpha 遮罩做模板相关性粗排，再用 Lab 颜色距离复排；
5. 输出 JSON、CSV、裁图、标注图和对照图，方便人工确认。

这是一个独立试验线，不影响现有准备页识别接口。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

SLOT_COUNT = 6
BASE_W = 1147
BASE_H = 643
BASE_ICON_X = 1026
BASE_ICON_Y = 133
BASE_ICON_CANVAS = 53
BASE_ROW_GAP = 59
BASE_MARGIN = 7
DEFAULT_MIRROR_MODE: Literal["enemy", "none", "both"] = "enemy"
SEARCH_SIZE_OFFSETS = (-2, -1, 0, 1, 2)
TOP_K = 2
ALPHA_THRESHOLD_COARSE = 170
ALPHA_THRESHOLD_FINE = 220
COLOR_DISTANCE_SCALE = 40.0
IDENTITY_STRUCTURE_WEIGHT = 0.82
IDENTITY_COLOR_WEIGHT = 0.18
EDGE_MATCH_WEIGHT = 0.7
GRAY_MATCH_WEIGHT = 0.3
CHECKERBOARD_TILE_SIZE = 12
VARIANT_DISK_CACHE_VERSION = "avatar_full_library_variant_cache_v1"


@dataclass(frozen=True)
class AvatarAsset:
    """透明头像模板及其元数据。"""

    visual_id: int
    label: str
    file_name: str
    path: Path
    rgba: np.ndarray
    sha256: str


@dataclass(frozen=True)
class TemplateVariant:
    """某个头像模板的单个方向和尺寸变体。"""

    visual_id: int
    label: str
    file_name: str
    path: Path
    sha256: str
    size: int
    mirrored: bool
    template_bgr: np.ndarray
    template_gray: np.ndarray
    template_edge: np.ndarray
    template_lab: np.ndarray
    template_alpha: np.ndarray
    alpha_mask: np.ndarray
    alpha_indices: np.ndarray


@dataclass(frozen=True)
class TemplateVisualScore:
    """Structure-first visual match score for a template variant."""

    identity_score: float
    gray_score: float
    edge_score: float
    loc: tuple[int, int] | None


@dataclass(frozen=True)
class SlotBox:
    """准备页敌方头像槽位裁剪框。"""

    slot: int
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


@dataclass(frozen=True)
class SlotRoiFeatures:
    """Preprocessed screenshot crop for one lineup slot."""

    box: SlotBox
    bgr: np.ndarray
    gray: np.ndarray
    edge: np.ndarray
    lab: np.ndarray


@dataclass(frozen=True)
class AvatarMatchCandidate:
    """单个槽位的视觉候选。"""

    slot: int
    visual_id: int
    label: str
    file_name: str
    path: str
    sha256: str
    coarse_score: float
    gray_score: float
    edge_score: float
    color_delta_e: float
    final_score: float
    size: int
    mirrored: bool
    local_x: int
    local_y: int
    screen_x: int
    screen_y: int
    confidence_level: str = ""

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 友好的字典。"""
        return {
            "slot": self.slot,
            "visual_id": self.visual_id,
            "label": self.label,
            "file_name": self.file_name,
            "path": self.path,
            "sha256": self.sha256,
            "coarse_score": round(self.coarse_score, 6),
            "gray_score": round(self.gray_score, 6),
            "edge_score": round(self.edge_score, 6),
            "color_delta_e": round(self.color_delta_e, 6),
            "final_score": round(self.final_score, 6),
            "size": self.size,
            "mirrored": self.mirrored,
            "local_x": self.local_x,
            "local_y": self.local_y,
            "screen_x": self.screen_x,
            "screen_y": self.screen_y,
            "confidence_level": self.confidence_level,
        }


@dataclass(frozen=True)
class SlotRecognitionResult:
    """单个敌方槽位识别结果。"""

    slot: int
    box: SlotBox
    top1: AvatarMatchCandidate | None
    top5: list[AvatarMatchCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 友好的字典。"""
        return {
            "slot": self.slot,
            "box": {
                "x1": self.box.x1,
                "y1": self.box.y1,
                "x2": self.box.x2,
                "y2": self.box.y2,
            },
            "top1": self.top1.to_dict() if self.top1 is not None else None,
            "top5": [candidate.to_dict() for candidate in self.top5],
        }


@dataclass(frozen=True)
class SlotRecognitionWorkResult:
    """单个槽位并行识别任务的内部结果。"""

    result: SlotRecognitionResult
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecognitionRunResult:
    """整张截图的识别结果。"""

    source_image_size: tuple[int, int]
    asset_count: int
    mirror_mode: str
    slots: list[SlotRecognitionResult]
    warnings: list[str]
    source_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 友好的字典。"""
        return {
            "method": (
                "pixel-only alpha-masked template matching; no OCR; filenames excluded from score"
            ),
            "source_image_size": list(self.source_image_size),
            "asset_count": self.asset_count,
            "mirror_mode": self.mirror_mode,
            "source_path": self.source_path,
            "warnings": self.warnings,
            "results": [slot.to_dict() for slot in self.slots],
        }


def decode_zip_name(name: str) -> str:
    """尽量把 Windows/中文环境 ZIP 文件名恢复为可读文本。"""
    for encoding in ("gbk", "utf-8"):
        try:
            return name.encode("cp437").decode(encoding)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return name


def _safe_extract_zip(zip_path: Path, output_dir: Path) -> None:
    """安全解压 ZIP，防路径穿越。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            decoded = decode_zip_name(member.filename)
            if not decoded or decoded.endswith("/"):
                continue
            relative = PurePosixPath(decoded)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            target = (output_dir / Path(*relative.parts)).resolve()
            if not str(target).startswith(str(output_dir.resolve())):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)


def _iter_image_files(root: Path) -> Iterator[Path]:
    """递归遍历可作为头像模板的图片文件。"""
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            yield path


def _find_best_avatar_root(root: Path) -> Path:
    """在目录树中选择 PNG 数量最多的目录作为头像根目录。"""
    candidates: list[tuple[int, int, Path]] = []
    directories = [root, *[path for path in root.rglob("*") if path.is_dir()]]
    for directory in directories:
        image_count = sum(1 for _ in _iter_image_files(directory))
        if image_count > 0:
            candidates.append((image_count, -len(directory.parts), directory))
    if not candidates:
        return root
    candidates.sort(reverse=True)
    return candidates[0][2]


@contextmanager
def open_avatar_source(source: str | Path) -> Iterator[Path]:
    """打开头像素材源，支持目录或 ZIP。"""
    path = Path(source)
    if path.is_dir():
        yield _find_best_avatar_root(path)
        return
    if path.suffix.lower() != ".zip":
        raise FileNotFoundError(f"头像素材源不存在或不支持：{path}")
    with tempfile.TemporaryDirectory(prefix="avatar_source_") as temp_dir:
        temp_root = Path(temp_dir)
        _safe_extract_zip(path, temp_root)
        yield _find_best_avatar_root(temp_root)


def _asset_sha256(path: Path) -> str:
    """计算文件 SHA256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_avatar_rgba(path: Path) -> np.ndarray | None:
    """读取透明头像素材，拒绝非四通道素材。"""
    try:
        image = Image.open(path)
        image.load()
    except (OSError, UnidentifiedImageError):
        return None
    rgba = ImageOps.exif_transpose(image).convert("RGBA")
    rgba = np.asarray(rgba, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        return None
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)


def _load_avatar_assets_from_root(root: Path) -> list[AvatarAsset]:
    """从已展开的目录加载透明头像素材。"""
    assets: list[AvatarAsset] = []
    for visual_id, path in enumerate(_iter_image_files(root), start=1):
        rgba = _load_avatar_rgba(path)
        if rgba is None:
            continue
        assets.append(
            AvatarAsset(
                visual_id=visual_id,
                label=path.stem,
                file_name=path.name,
                path=path,
                rgba=rgba,
                sha256=_asset_sha256(path),
            )
        )
    if not assets:
        raise ValueError(f"没有加载到有效的透明头像素材：{root}")
    return assets


@contextmanager
def open_avatar_assets(source: str | Path) -> Iterator[list[AvatarAsset]]:
    """打开头像素材并在上下文结束后清理 ZIP 临时目录。"""
    with open_avatar_source(source) as root:
        yield _load_avatar_assets_from_root(root)


def load_avatar_assets(source: str | Path) -> list[AvatarAsset]:
    """加载透明头像素材。"""
    with open_avatar_assets(source) as assets:
        return list(assets)


def _variant_disk_cache_path(
    icons_dir: Path,
    *,
    mirror_mode: Literal["enemy", "none", "both"],
) -> Path:
    """Return the local feature-cache path for preprocessed avatar variants."""
    safe_mode = mirror_mode.replace("/", "_")
    return icons_dir.parent / f".{icons_dir.name}_{safe_mode}_full_library_variants_v1.npz"


def _variant_disk_cache_signature(
    assets: list[AvatarAsset],
    *,
    mirror_mode: Literal["enemy", "none", "both"],
) -> str:
    """Build a signature that invalidates cache when avatar material changes."""
    rows = []
    for asset in assets:
        try:
            stat = asset.path.stat()
            mtime_ns = stat.st_mtime_ns
            size = stat.st_size
        except OSError:
            mtime_ns = 0
            size = 0
        rows.append(
            {
                "visual_id": asset.visual_id,
                "label": asset.label,
                "file_name": asset.file_name,
                "path": str(asset.path),
                "sha256": asset.sha256,
                "mtime_ns": mtime_ns,
                "size": size,
            }
        )
    return json.dumps(
        {
            "version": VARIANT_DISK_CACHE_VERSION,
            "mirror_mode": mirror_mode,
            "size_offsets": list(SEARCH_SIZE_OFFSETS),
            "assets": rows,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


@lru_cache(maxsize=8)
def get_avatar_recognizer(
    icons_dir: str | Path,
    *,
    mirror_mode: Literal["enemy", "none", "both"] = DEFAULT_MIRROR_MODE,
) -> AlphaTemplateRecognizer:
    """加载并缓存透明模板库识别器。"""
    icons_path = Path(icons_dir).resolve()
    assets = load_avatar_assets(icons_path)
    recognizer = AlphaTemplateRecognizer(assets, mirror_mode=mirror_mode)
    cache_path = _variant_disk_cache_path(icons_path, mirror_mode=mirror_mode)
    cache_signature = _variant_disk_cache_signature(assets, mirror_mode=mirror_mode)
    recognizer.load_variant_disk_cache(cache_path, cache_signature)
    recognizer.warm_up()
    recognizer.write_variant_disk_cache(cache_path, cache_signature)
    return recognizer


def warm_avatar_variant_cache(
    icons_dir: str | Path,
    *,
    mirror_mode: Literal["enemy", "none", "both"] = DEFAULT_MIRROR_MODE,
) -> Path:
    """显式预热本地头像素材的模板变体磁盘缓存。"""
    icons_path = Path(icons_dir).resolve()
    if not icons_path.is_dir():
        raise ValueError("头像预处理缓存预热只支持本地文件夹素材")
    recognizer = get_avatar_recognizer(icons_path, mirror_mode=mirror_mode)
    cache_path = _variant_disk_cache_path(icons_path, mirror_mode=mirror_mode)
    if not cache_path.is_file():
        cache_signature = _variant_disk_cache_signature(recognizer.assets, mirror_mode=mirror_mode)
        recognizer.write_variant_disk_cache(cache_path, cache_signature)
    return cache_path


def _scale_value(value: int, scale: float) -> int:
    """按比例缩放并四舍五入。"""
    return round(value * scale)


def build_slot_boxes(image_size: tuple[int, int]) -> list[SlotBox]:
    """按复现说明中的固定布局计算六个槽位裁剪框。"""
    width, height = image_size
    sx = width / BASE_W
    sy = height / BASE_H
    icon_scale = min(sx, sy)
    icon = max(1, _scale_value(BASE_ICON_CANVAS, icon_scale))
    gap = max(1, _scale_value(BASE_ROW_GAP, sy))
    margin = max(1, _scale_value(BASE_MARGIN, icon_scale))
    x = _scale_value(BASE_ICON_X, sx)
    y0 = _scale_value(BASE_ICON_Y, sy)
    boxes: list[SlotBox] = []
    for slot in range(1, SLOT_COUNT + 1):
        expected_y = y0 + (slot - 1) * gap
        boxes.append(
            SlotBox(
                slot=slot,
                x1=max(0, x - margin),
                y1=max(0, expected_y - margin),
                x2=min(width, x + icon + margin),
                y2=min(height, expected_y + icon + margin),
            )
        )
    return boxes


def _resize_rgba(image: np.ndarray, size: int) -> np.ndarray:
    """把 BGRA 图像缩放到正方形尺寸。"""
    interpolation = cv2.INTER_AREA if size <= image.shape[0] else cv2.INTER_CUBIC
    return cv2.resize(image, (size, size), interpolation=interpolation)


def _alpha_mask(alpha: np.ndarray, *, threshold: int, erode: int) -> np.ndarray:
    """根据 Alpha 通道生成模板遮罩。"""
    mask = (alpha >= threshold).astype(np.uint8) * 255
    if erode > 0:
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8), iterations=erode)
    return mask


def _alpha_indices(mask: np.ndarray) -> np.ndarray:
    """返回遮罩中有效像素索引。"""
    return np.flatnonzero(mask.reshape(-1) > 0)


def _template_gray(template_bgr: np.ndarray) -> np.ndarray:
    """Build a grayscale structure image for color-tolerant matching."""
    return cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)


def _template_edge(gray: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Build an edge image dominated by shape instead of hue."""
    edges = cv2.Canny(gray, 40, 120)
    alpha_edges = cv2.Canny(alpha, 40, 120)
    merged = cv2.max(edges, alpha_edges)
    return cv2.dilate(merged, np.ones((2, 2), np.uint8), iterations=1)


def _masked_match_response(
    roi_image: np.ndarray,
    template_image: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray | None:
    """Run masked normalized matching and sanitize OpenCV edge cases."""
    template_h, template_w = template_image.shape[:2]
    roi_h, roi_w = roi_image.shape[:2]
    if template_h > roi_h or template_w > roi_w:
        return None
    response = cv2.matchTemplate(
        roi_image,
        template_image,
        cv2.TM_CCORR_NORMED,
        mask=mask,
    )
    return np.nan_to_num(response, nan=0.0, posinf=0.0, neginf=0.0)


def _variant_key(asset: AvatarAsset, size: int, mirrored: bool) -> tuple[int, int, bool]:
    """变体缓存键。"""
    return (asset.visual_id, size, mirrored)


def _build_variant(asset: AvatarAsset, *, size: int, mirrored: bool) -> TemplateVariant:
    """构建单个模板变体。"""
    rgba = asset.rgba
    if mirrored:
        rgba = cv2.flip(rgba, 1)
    resized = _resize_rgba(rgba, size)
    template_bgr = resized[:, :, :3]
    alpha = resized[:, :, 3]
    template_gray = _template_gray(template_bgr)
    template_edge = _template_edge(template_gray, alpha)
    mask = _alpha_mask(alpha, threshold=ALPHA_THRESHOLD_COARSE, erode=1)
    indices = _alpha_indices(mask)
    if indices.size == 0:
        raise ValueError("透明模板有效遮罩像素过少")
    template_lab = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return TemplateVariant(
        visual_id=asset.visual_id,
        label=asset.label,
        file_name=asset.file_name,
        path=asset.path,
        sha256=asset.sha256,
        size=size,
        mirrored=mirrored,
        template_bgr=template_bgr,
        template_gray=template_gray,
        template_edge=template_edge,
        template_lab=template_lab,
        template_alpha=alpha,
        alpha_mask=mask,
        alpha_indices=indices,
    )


def _prepare_slot_roi_features(screenshot_bgr: np.ndarray, box: SlotBox) -> SlotRoiFeatures:
    """Preprocess one slot ROI once instead of once per template."""
    roi_bgr = screenshot_bgr[box.y1 : box.y2, box.x1 : box.x2]
    roi_gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    roi_edge = _template_edge(roi_gray, np.full_like(roi_gray, 255, dtype=np.uint8))
    roi_lab = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return SlotRoiFeatures(
        box=box,
        bgr=roi_bgr,
        gray=roi_gray,
        edge=roi_edge,
        lab=roi_lab,
    )


def _template_score_on_roi(
    roi: SlotRoiFeatures,
    variant: TemplateVariant,
) -> TemplateVisualScore:
    """Match one variant against a preprocessed slot ROI."""
    template_h, template_w = variant.template_bgr.shape[:2]
    roi_h, roi_w = roi.bgr.shape[:2]
    if template_h > roi_h or template_w > roi_w:
        return TemplateVisualScore(0.0, 0.0, 0.0, None)

    gray_response = _masked_match_response(roi.gray, variant.template_gray, variant.alpha_mask)
    edge_response = _masked_match_response(roi.edge, variant.template_edge, variant.alpha_mask)
    if gray_response is None and edge_response is None:
        return TemplateVisualScore(0.0, 0.0, 0.0, None)

    if gray_response is None:
        gray_response = np.zeros_like(edge_response)
    if edge_response is None:
        edge_response = np.zeros_like(gray_response)

    combined = GRAY_MATCH_WEIGHT * gray_response + EDGE_MATCH_WEIGHT * edge_response
    _, identity_score, _, loc = cv2.minMaxLoc(combined)
    local_x, local_y = int(loc[0]), int(loc[1])
    gray_score = float(gray_response[local_y, local_x])
    edge_score = float(edge_response[local_y, local_x])
    if not math.isfinite(identity_score):
        return TemplateVisualScore(0.0, 0.0, 0.0, None)
    return TemplateVisualScore(
        identity_score=float(identity_score),
        gray_score=gray_score if math.isfinite(gray_score) else 0.0,
        edge_score=edge_score if math.isfinite(edge_score) else 0.0,
        loc=(local_x, local_y),
    )


def _candidate_color_delta_e(
    template: TemplateVariant,
    patch_lab: np.ndarray,
) -> float:
    """Calculate mean Lab color distance inside the alpha-covered area."""
    if patch_lab.shape[:2] != template.template_bgr.shape[:2]:
        return float("inf")
    delta = np.linalg.norm(template.template_lab - patch_lab, axis=2)
    template_alpha = template.template_alpha >= ALPHA_THRESHOLD_FINE
    if template_alpha.sum() < 20:
        template_alpha = template.template_alpha >= ALPHA_THRESHOLD_COARSE
    if template_alpha.sum() < 20:
        return float("inf")
    return float(delta[template_alpha].mean())


def _checkerboard_background(
    size: tuple[int, int],
    *,
    tile_size: int = CHECKERBOARD_TILE_SIZE,
    left: tuple[int, int, int] = (66, 66, 66),
    right: tuple[int, int, int] = (42, 42, 42),
) -> Image.Image:
    """生成透明抄像对比常用的棋盘背景。"""
    width, height = size
    image = Image.new("RGBA", (width, height), (*left, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, height, tile_size):
        for x in range(0, width, tile_size):
            if (x // tile_size + y // tile_size) % 2 == 0:
                draw.rectangle(
                    (x, y, min(x + tile_size, width), min(y + tile_size, height)),
                    fill=(*right, 255),
                )
    return image


def _confidence_level(final_score: float, score_gap: float) -> str:
    """根据最终分和第一第二名差距给出粗略置信等级。"""
    if final_score >= 0.85 and score_gap >= 0.03:
        return "high"
    if final_score >= 0.72 and score_gap >= 0.015:
        return "medium"
    return "low"


def _normalize_slot_candidates(
    raw_candidates: list[AvatarMatchCandidate],
) -> list[AvatarMatchCandidate]:
    """Sort by final score, deduplicate variants, and fill confidence levels."""
    deduplicated: list[AvatarMatchCandidate] = []
    seen_visual_ids: set[int] = set()
    for candidate in sorted(raw_candidates, key=lambda item: item.final_score, reverse=True):
        if candidate.visual_id in seen_visual_ids:
            continue
        deduplicated.append(candidate)
        seen_visual_ids.add(candidate.visual_id)
    if not deduplicated:
        return []

    top1 = deduplicated[0]
    top2_score = deduplicated[1].final_score if len(deduplicated) > 1 else 0.0
    score_gap = top1.final_score - top2_score
    updated: list[AvatarMatchCandidate] = []
    for index, candidate in enumerate(deduplicated):
        candidate_gap = score_gap if index == 0 else max(score_gap / 2, 0.0)
        updated.append(
            AvatarMatchCandidate(
                **{
                    **candidate.__dict__,
                    "confidence_level": _confidence_level(candidate.final_score, candidate_gap),
                }
            )
        )
    return updated


class AlphaTemplateRecognizer:
    """透明模板库头像识别器。"""

    def __init__(
        self,
        assets: list[AvatarAsset],
        *,
        mirror_mode: Literal["enemy", "none", "both"] = DEFAULT_MIRROR_MODE,
    ) -> None:
        self.assets = assets
        self.mirror_mode = mirror_mode
        self._variant_cache: dict[tuple[int, int, bool], TemplateVariant] = {}
        self._variants_by_size: dict[int, list[TemplateVariant]] = {}

    def load_variant_disk_cache(self, cache_path: Path, signature: str) -> None:
        """Load preprocessed template variants from a local npz cache if valid."""
        if not cache_path.is_file():
            return
        asset_map = {asset.visual_id: asset for asset in self.assets}
        try:
            with np.load(cache_path, allow_pickle=False) as payload:
                cached_signature = str(payload["signature"][0])
                if cached_signature != signature:
                    return
                metadata = json.loads(str(payload["metadata"][0]))
                variant_cache: dict[tuple[int, int, bool], TemplateVariant] = {}
                variants_by_size: dict[int, list[TemplateVariant]] = {}
                for index, row in enumerate(metadata):
                    visual_id = int(row["visual_id"])
                    size = int(row["size"])
                    mirrored = bool(row["mirrored"])
                    asset = asset_map.get(visual_id)
                    if asset is None:
                        return
                    variant = TemplateVariant(
                        visual_id=visual_id,
                        label=asset.label,
                        file_name=asset.file_name,
                        path=asset.path,
                        sha256=asset.sha256,
                        size=size,
                        mirrored=mirrored,
                        template_bgr=payload[f"template_bgr_{index}"].astype(np.uint8),
                        template_gray=payload[f"template_gray_{index}"].astype(np.uint8),
                        template_edge=payload[f"template_edge_{index}"].astype(np.uint8),
                        template_lab=payload[f"template_lab_{index}"].astype(np.float32),
                        template_alpha=payload[f"template_alpha_{index}"].astype(np.uint8),
                        alpha_mask=payload[f"alpha_mask_{index}"].astype(np.uint8),
                        alpha_indices=payload[f"alpha_indices_{index}"].astype(np.int64),
                    )
                    key = _variant_key(asset, size, mirrored)
                    variant_cache[key] = variant
                    variants_by_size.setdefault(size, []).append(variant)
                self._variant_cache = variant_cache
                self._variants_by_size = variants_by_size
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return

    def write_variant_disk_cache(self, cache_path: Path, signature: str) -> None:
        """Persist preprocessed template variants to local npz cache for faster cold starts."""
        if not self._variant_cache:
            return
        temp_path: Path | None = None
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            variants = sorted(
                self._variant_cache.values(),
                key=lambda item: (item.size, item.visual_id, item.mirrored),
            )
            metadata = [
                {
                    "visual_id": variant.visual_id,
                    "size": variant.size,
                    "mirrored": variant.mirrored,
                }
                for variant in variants
            ]
            arrays: dict[str, np.ndarray] = {
                "signature": np.asarray([signature]),
                "metadata": np.asarray([json.dumps(metadata, ensure_ascii=False)]),
            }
            for index, variant in enumerate(variants):
                arrays[f"template_bgr_{index}"] = variant.template_bgr
                arrays[f"template_gray_{index}"] = variant.template_gray
                arrays[f"template_edge_{index}"] = variant.template_edge
                arrays[f"template_lab_{index}"] = variant.template_lab
                arrays[f"template_alpha_{index}"] = variant.template_alpha
                arrays[f"alpha_mask_{index}"] = variant.alpha_mask
                arrays[f"alpha_indices_{index}"] = variant.alpha_indices
            with tempfile.NamedTemporaryFile(
                dir=cache_path.parent,
                prefix=f"{cache_path.name}.",
                suffix=".tmp.npz",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                np.savez(handle, **arrays)
            temp_path.replace(cache_path)
        except OSError:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return

    def _variants_for_asset(self, asset: AvatarAsset, size: int) -> list[TemplateVariant]:
        """获取某个模板在指定尺寸下的方向变体。"""
        mirror_flags: list[bool]
        if self.mirror_mode == "none":
            mirror_flags = [False]
        elif self.mirror_mode == "both":
            mirror_flags = [False, True]
        else:
            mirror_flags = [True]
        variants: list[TemplateVariant] = []
        for mirrored in mirror_flags:
            key = _variant_key(asset, size, mirrored)
            if key not in self._variant_cache:
                self._variant_cache[key] = _build_variant(asset, size=size, mirrored=mirrored)
            variants.append(self._variant_cache[key])
        return variants

    def _variants_for_size(self, size: int) -> list[TemplateVariant]:
        """获取指定尺寸下的全部模板变体。"""
        cached = self._variants_by_size.get(size)
        if cached is not None:
            return cached
        variants: list[TemplateVariant] = []
        for asset in self.assets:
            variants.extend(self._variants_for_asset(asset, size))
        self._variants_by_size[size] = variants
        return variants

    def _variants_for_sizes(self, sizes: tuple[int, ...]) -> list[TemplateVariant]:
        """Return variants for multiple sizes while reusing preprocessed features."""
        return [variant for size in sizes for variant in self._variants_for_size(size)]

    def warm_up(self, sizes: tuple[int, ...] | None = None) -> None:
        """Warm up common template variants and their grayscale/edge/Lab/alpha features."""
        warm_sizes = sizes or tuple(BASE_ICON_CANVAS + offset for offset in SEARCH_SIZE_OFFSETS)
        for size in warm_sizes:
            if size > 0:
                self._variants_for_size(int(size))

    @staticmethod
    def _candidate_sizes(image_size: tuple[int, int]) -> tuple[int, ...]:
        """根据截图尺寸估算本次识别需要搜索的模板尺寸。"""
        width, height = image_size
        scale = min(width / BASE_W, height / BASE_H)
        expected = max(1, _scale_value(BASE_ICON_CANVAS, scale))
        sizes = sorted({max(1, expected + offset) for offset in SEARCH_SIZE_OFFSETS})
        return tuple(sizes)

    def _recognize_slot(
        self,
        slot_index: int,
        slot_roi: SlotRoiFeatures,
        candidate_variants: list[TemplateVariant],
        asset_map: dict[int, AvatarAsset],
    ) -> SlotRecognitionWorkResult:
        """识别单个敌方槽位，供串行或并行调度复用。"""
        box = slot_roi.box
        ranked_coarse: list[AvatarMatchCandidate] = []
        # Accuracy first: do not use low-resolution signature prefiltering here.
        # Match every transparent template variant with Alpha mask, then run
        # color refinement for all coarse candidates to avoid recall loss.
        for candidate_variant in candidate_variants:
            template_h, template_w = candidate_variant.template_bgr.shape[:2]
            if template_h > slot_roi.bgr.shape[0] or template_w > slot_roi.bgr.shape[1]:
                continue
            visual_score = _template_score_on_roi(slot_roi, candidate_variant)
            if visual_score.loc is None:
                continue
            local_x, local_y = visual_score.loc
            patch = slot_roi.bgr[
                local_y : local_y + template_h,
                local_x : local_x + template_w,
            ]
            if patch.shape[:2] != (template_h, template_w):
                continue
            ranked_coarse.append(
                AvatarMatchCandidate(
                    slot=box.slot,
                    visual_id=candidate_variant.visual_id,
                    label=candidate_variant.label,
                    file_name=candidate_variant.file_name,
                    path=str(candidate_variant.path),
                    sha256=candidate_variant.sha256,
                    coarse_score=float(visual_score.identity_score),
                    gray_score=float(visual_score.gray_score),
                    edge_score=float(visual_score.edge_score),
                    color_delta_e=0.0,
                    final_score=float(visual_score.identity_score),
                    size=candidate_variant.size,
                    mirrored=candidate_variant.mirrored,
                    local_x=local_x,
                    local_y=local_y,
                    screen_x=box.x1 + local_x,
                    screen_y=box.y1 + local_y,
                )
            )

        refined: list[AvatarMatchCandidate] = []
        for candidate in sorted(
            ranked_coarse,
            key=lambda item: item.coarse_score,
            reverse=True,
        ):
            variant = self._variant_cache[
                _variant_key(
                    asset_map[candidate.visual_id],
                    candidate.size,
                    candidate.mirrored,
                )
            ]
            template_h, template_w = variant.template_bgr.shape[:2]
            patch_lab = slot_roi.lab[
                candidate.local_y : candidate.local_y + template_h,
                candidate.local_x : candidate.local_x + template_w,
            ]
            if patch_lab.shape[:2] != (template_h, template_w):
                continue
            color_delta_e = _candidate_color_delta_e(variant, patch_lab)
            color_similarity = math.exp(-color_delta_e / COLOR_DISTANCE_SCALE)
            final_score = (
                IDENTITY_STRUCTURE_WEIGHT * candidate.coarse_score
                + IDENTITY_COLOR_WEIGHT * color_similarity
            )
            refined.append(
                AvatarMatchCandidate(
                    **{
                        **candidate.__dict__,
                        "color_delta_e": float(color_delta_e),
                        "final_score": float(final_score),
                    }
                )
            )

        ranked = _normalize_slot_candidates(refined)
        warnings: list[str] = []
        if ranked:
            top1 = ranked[0]
        else:
            warnings.append(f"slot {slot_index + 1} 未找到可用候选")
            top1 = None
        return SlotRecognitionWorkResult(
            result=SlotRecognitionResult(
                slot=box.slot,
                box=box,
                top1=top1,
                top5=ranked[:TOP_K],
            ),
            warnings=warnings,
        )

    def recognize_screenshot(self, screenshot_bgr: np.ndarray) -> RecognitionRunResult:
        """识别整张准备页截图。"""
        if screenshot_bgr.ndim != 3 or screenshot_bgr.shape[2] != 3:
            raise ValueError("截图必须是 BGR 三通道图像")
        asset_map = {asset.visual_id: asset for asset in self.assets}
        screenshot_h, screenshot_w = screenshot_bgr.shape[:2]
        slot_boxes = build_slot_boxes((screenshot_w, screenshot_h))
        slot_rois = [
            _prepare_slot_roi_features(screenshot_bgr, box)
            for box in slot_boxes
        ]
        candidate_sizes = self._candidate_sizes((screenshot_w, screenshot_h))
        candidate_variants = self._variants_for_sizes(candidate_sizes)

        warnings: list[str] = []
        if len(slot_rois) > 1:
            with ThreadPoolExecutor(max_workers=min(SLOT_COUNT, len(slot_rois))) as executor:
                work_results = list(
                    executor.map(
                        lambda item: self._recognize_slot(
                            item[0],
                            item[1],
                            candidate_variants,
                            asset_map,
                        ),
                        enumerate(slot_rois),
                    )
                )
        else:
            work_results = [
                self._recognize_slot(0, slot_rois[0], candidate_variants, asset_map)
            ]
        slot_results = [work.result for work in work_results]
        for work in work_results:
            warnings.extend(work.warnings)
        return RecognitionRunResult(
            source_image_size=(screenshot_w, screenshot_h),
            asset_count=len(self.assets),
            mirror_mode=self.mirror_mode,
            slots=slot_results,
            warnings=warnings,
        )


def _load_screenshot(source: str | Path) -> tuple[np.ndarray, tuple[int, int]]:
    """读取截图。"""
    path = Path(source)
    try:
        image = Image.open(path)
        image.load()
    except (OSError, UnidentifiedImageError):
        raise FileNotFoundError(f"无法读取截图：{path}") from None
    rgb = ImageOps.exif_transpose(image).convert("RGB")
    screenshot = cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    height, width = screenshot.shape[:2]
    return screenshot, (width, height)


def _save_slot_crops(
    screenshot_bgr: np.ndarray,
    result: RecognitionRunResult,
    output_dir: Path,
) -> None:
    """保存 6 个槽位裁图。"""
    crops_dir = output_dir / "slot_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    for slot in result.slots:
        crop = screenshot_bgr[slot.box.y1 : slot.box.y2, slot.box.x1 : slot.box.x2]
        cv2.imwrite(str(crops_dir / f"slot_{slot.slot}.png"), crop)


def _save_matched_assets(
    result: RecognitionRunResult,
    assets: list[AvatarAsset],
    output_dir: Path,
) -> None:
    """保存每个槽位的获胜模板副本。"""
    matched_dir = output_dir / "matched_assets"
    matched_dir.mkdir(parents=True, exist_ok=True)
    asset_map = {asset.visual_id: asset for asset in assets}
    for slot in result.slots:
        if slot.top1 is None:
            continue
        asset = asset_map.get(slot.top1.visual_id)
        if asset is None:
            continue
        target = matched_dir / f"slot_{slot.slot}_{asset.file_name}"
        shutil.copy2(asset.path, target)


def _annotate_image(
    screenshot_bgr: np.ndarray,
    result: RecognitionRunResult,
    output_dir: Path,
) -> None:
    """输出标注图。"""
    image = Image.fromarray(cv2.cvtColor(screenshot_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    for slot in result.slots:
        draw.rectangle((slot.box.x1, slot.box.y1, slot.box.x2, slot.box.y2), outline="red", width=3)
        label = slot.top1.label if slot.top1 else "unknown"
        score = slot.top1.final_score if slot.top1 else 0.0
        draw.text(
            (slot.box.x1 + 2, max(0, slot.box.y1 - 14)),
            f"{slot.slot}:{label} {score:.3f}",
            fill="yellow",
        )
    image.save(output_dir / "annotated_recognition.png")


def _contact_sheet(
    screenshot_bgr: np.ndarray,
    result: RecognitionRunResult,
    assets: list[AvatarAsset],
    output_dir: Path,
) -> None:
    """输出对照图，便于人工查看每槽 Top2。"""
    asset_map = {asset.visual_id: asset for asset in assets}
    columns = 1 + TOP_K
    cell_w = 128
    cell_h = 160
    sheet = Image.new("RGBA", (columns * cell_w, SLOT_COUNT * cell_h), (24, 24, 24, 255))
    screenshot = Image.fromarray(cv2.cvtColor(screenshot_bgr, cv2.COLOR_BGR2RGB))
    for row, slot in enumerate(result.slots):
        crop = screenshot.crop(
            (slot.box.x1, slot.box.y1, slot.box.x2, slot.box.y2)
        ).resize((cell_w, 96))
        sheet.paste(crop, (0, row * cell_h))
        draw = ImageDraw.Draw(sheet)
        draw.text((2, row * cell_h + 98), f"slot {slot.slot}", fill="white")
        for col, candidate in enumerate(slot.top5[:TOP_K], start=1):
            asset = asset_map.get(candidate.visual_id)
            if asset is None:
                continue
            template = Image.fromarray(cv2.cvtColor(asset.rgba[:, :, :3], cv2.COLOR_BGR2RGB))
            template = template.resize((96, 96))
            sheet.paste(template, (col * cell_w + 16, row * cell_h))
            draw.text(
                (col * cell_w + 2, row * cell_h + 98),
                f"{candidate.label}\n{candidate.final_score:.3f}",
                fill="white",
            )
    sheet.save(output_dir / "recognition_contact_sheet.png")


def _variant_rgba_image(variant: TemplateVariant) -> Image.Image:
    """把模板变体转成 RGBA 图片。"""
    rgb = cv2.cvtColor(variant.template_bgr, cv2.COLOR_BGR2RGB)
    rgba = np.dstack([rgb, variant.template_alpha])
    return Image.fromarray(rgba, mode="RGBA")


def _candidate_panel_preview(
    variant: TemplateVariant,
    *,
    background: tuple[int, int, int] = (32, 32, 32),
) -> Image.Image:
    """输出透明模板本体，方便直接检查抄像质量。"""
    template = _variant_rgba_image(variant)
    panel = _checkerboard_background(
        template.size,
        left=background,
        right=tuple(min(value + 22, 255) for value in background),
    )
    panel.alpha_composite(template, (0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, panel.width - 1, panel.height - 1), outline=(255, 255, 255, 220))
    return panel


def _variant_for_candidate(
    recognizer: AlphaTemplateRecognizer,
    assets: list[AvatarAsset],
    candidate: AvatarMatchCandidate,
) -> TemplateVariant:
    """根据候选找到对应模板变体。"""
    asset_map = {asset.visual_id: asset for asset in assets}
    asset = asset_map[candidate.visual_id]
    key = _variant_key(asset, candidate.size, candidate.mirrored)
    variant = recognizer._variant_cache.get(key)
    if variant is None:
        variant = _build_variant(asset, size=candidate.size, mirrored=candidate.mirrored)
        recognizer._variant_cache[key] = variant
    return variant


def _candidate_panel_crop(
    screenshot_bgr: np.ndarray,
    slot: SlotRecognitionResult,
) -> Image.Image:
    """输出单槽位裁图面板。"""
    crop = screenshot_bgr[slot.box.y1 : slot.box.y2, slot.box.x1 : slot.box.x2]
    return Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))


def _candidate_panel_cutout(
    screenshot_bgr: np.ndarray,
    slot: SlotRecognitionResult,
    variant: TemplateVariant,
    candidate: AvatarMatchCandidate,
    *,
    background: tuple[int, int, int] = (32, 32, 32),
) -> Image.Image:
    """输出透明模板抠像对比面板。"""
    crop = screenshot_bgr[slot.box.y1 : slot.box.y2, slot.box.x1 : slot.box.x2]
    crop_rgb = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    panel = Image.new("RGBA", crop_rgb.size, (*background, 255))
    panel.paste(crop_rgb.convert("RGBA"), (0, 0))
    template = _variant_rgba_image(variant)
    panel.alpha_composite(template, (candidate.local_x, candidate.local_y))
    return panel


def _candidate_panel_diff(
    screenshot_bgr: np.ndarray,
    slot: SlotRecognitionResult,
    variant: TemplateVariant,
    candidate: AvatarMatchCandidate,
    *,
    background: tuple[int, int, int] = (24, 24, 24),
) -> Image.Image:
    """输出模板与截图局部的差异热力图面板。"""
    crop = screenshot_bgr[slot.box.y1 : slot.box.y2, slot.box.x1 : slot.box.x2]
    panel = Image.new("RGBA", (crop.shape[1], crop.shape[0]), (*background, 255))
    template_h, template_w = variant.template_bgr.shape[:2]
    patch = crop[
        candidate.local_y : candidate.local_y + template_h,
        candidate.local_x : candidate.local_x + template_w,
    ]
    if patch.shape[:2] == (template_h, template_w):
        diff = np.abs(patch.astype(np.int16) - variant.template_bgr.astype(np.int16)).mean(axis=2)
        diff = np.clip(diff * 3.2, 0, 255).astype(np.uint8)
        heatmap = cv2.applyColorMap(diff, cv2.COLORMAP_TURBO)
        heatmap_rgb = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
        heatmap_image = Image.fromarray(heatmap_rgb).convert("RGBA")
        alpha_mask = np.where(
            variant.template_alpha >= ALPHA_THRESHOLD_FINE,
            220,
            np.where(variant.template_alpha >= ALPHA_THRESHOLD_COARSE, 120, 0),
        ).astype(np.uint8)
        heatmap_image.putalpha(Image.fromarray(alpha_mask, mode="L"))
        panel.paste(heatmap_image, (candidate.local_x, candidate.local_y))
    draw = ImageDraw.Draw(panel)
    draw.rectangle(
        (
            candidate.local_x,
            candidate.local_y,
            candidate.local_x + template_w,
            candidate.local_y + template_h,
        ),
        outline=(255, 255, 255, 255),
        width=2,
    )
    return panel


def _panel_with_title(image: Image.Image, title: str) -> Image.Image:
    """给面板加标题栏。"""
    title_h = 22
    canvas = Image.new("RGBA", (image.width, image.height + title_h), (18, 18, 18, 255))
    canvas.paste(image, (0, title_h))
    draw = ImageDraw.Draw(canvas)
    draw.text((6, 4), title, fill="white")
    return canvas


def _compose_panel_grid(
    panels: list[Image.Image],
    *,
    columns: int,
    background: tuple[int, int, int] = (16, 16, 16),
) -> Image.Image:
    """把若干面板拼成固定网格，便于人工对照。"""
    if not panels:
        return Image.new("RGBA", (1, 1), (*background, 255))
    rows = math.ceil(len(panels) / columns)
    cell_w = max(panel.width for panel in panels)
    cell_h = max(panel.height for panel in panels)
    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), (*background, 255))
    for index, panel in enumerate(panels):
        row, col = divmod(index, columns)
        x = col * cell_w + (cell_w - panel.width) // 2
        y = row * cell_h + (cell_h - panel.height) // 2
        sheet.paste(panel, (x, y))
    return sheet


def _save_detailed_comparisons(
    screenshot_bgr: np.ndarray,
    result: RecognitionRunResult,
    assets: list[AvatarAsset],
    recognizer: AlphaTemplateRecognizer,
    output_dir: Path,
) -> None:
    """保存详细的抄像与 Top2 对比图。"""
    compare_dir = output_dir / "comparison"
    compare_dir.mkdir(parents=True, exist_ok=True)
    for slot in result.slots:
        if slot.top1 is None:
            continue
        top1 = slot.top1
        variant = _variant_for_candidate(recognizer, assets, top1)
        crop = _candidate_panel_crop(screenshot_bgr, slot).convert("RGBA")
        preview = _candidate_panel_preview(variant)
        overlay = _candidate_panel_cutout(screenshot_bgr, slot, variant, top1)
        diff = _candidate_panel_diff(screenshot_bgr, slot, variant, top1)

        panels = [
            _panel_with_title(crop, f"slot {slot.slot} 原图裁剪"),
            _panel_with_title(preview, f"Top1 抄像 {top1.label}"),
            _panel_with_title(overlay, f"Top1 对齐 {top1.label}"),
            _panel_with_title(diff, f"Top1 差异 {top1.final_score:.3f}"),
        ]
        sheet = _compose_panel_grid(panels, columns=2)
        sheet.save(compare_dir / f"slot_{slot.slot}_detail.png")

        top5_panels: list[Image.Image] = []
        for candidate in slot.top5[:TOP_K]:
            variant = _variant_for_candidate(recognizer, assets, candidate)
            panel = _candidate_panel_preview(variant)
            title = f"{candidate.label} {candidate.final_score:.3f}"
            top5_panels.append(_panel_with_title(panel, title))
        if top5_panels:
            sheet = _compose_panel_grid(top5_panels, columns=TOP_K)
            sheet.save(compare_dir / f"slot_{slot.slot}_top2.png")


def save_debug_artifacts(
    screenshot_bgr: np.ndarray,
    result: RecognitionRunResult,
    recognizer: AlphaTemplateRecognizer,
    output_dir: str | Path,
) -> None:
    """保存截图框选、槽位裁剪、Top2 和详细抠像对比图。"""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = recognizer.assets
    _save_slot_crops(screenshot_bgr, result, out_dir)
    _save_matched_assets(result, assets, out_dir)
    _annotate_image(screenshot_bgr, result, out_dir)
    _contact_sheet(screenshot_bgr, result, assets, out_dir)
    _save_detailed_comparisons(screenshot_bgr, result, assets, recognizer, out_dir)


def write_outputs(
    screenshot_path: str | Path,
    avatars_source: str | Path,
    output_dir: str | Path,
    *,
    mirror_mode: Literal["enemy", "none", "both"] = DEFAULT_MIRROR_MODE,
) -> RecognitionRunResult:
    """执行识别并写出调试产物。"""
    screenshot_bgr, _image_size = _load_screenshot(screenshot_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    avatars_path = Path(avatars_source)
    if avatars_path.is_dir():
        recognizer = get_avatar_recognizer(avatars_path, mirror_mode=mirror_mode)
        assets = recognizer.assets
        raw_result = recognizer.recognize_screenshot(screenshot_bgr)
    else:
        with open_avatar_assets(avatars_source) as loaded_assets:
            assets = list(loaded_assets)
            recognizer = AlphaTemplateRecognizer(assets, mirror_mode=mirror_mode)
            raw_result = recognizer.recognize_screenshot(screenshot_bgr)

    result = RecognitionRunResult(
        source_image_size=raw_result.source_image_size,
        asset_count=raw_result.asset_count,
        mirror_mode=raw_result.mirror_mode,
        slots=raw_result.slots,
        warnings=raw_result.warnings,
        source_path=str(Path(screenshot_path)),
    )

    (out_dir / "results.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "slot",
                "visual_id",
                "label",
                "file_name",
                "coarse_score",
                "color_delta_e",
                "final_score",
                "size",
                "mirrored",
                "local_x",
                "local_y",
                "screen_x",
                "screen_y",
                "confidence_level",
            ],
        )
        writer.writeheader()
        for slot in result.slots:
            if slot.top1 is None:
                continue
            writer.writerow(
                {
                    "slot": slot.top1.slot,
                    "visual_id": slot.top1.visual_id,
                    "label": slot.top1.label,
                    "file_name": slot.top1.file_name,
                    "coarse_score": round(slot.top1.coarse_score, 6),
                    "color_delta_e": round(slot.top1.color_delta_e, 6),
                    "final_score": round(slot.top1.final_score, 6),
                    "size": slot.top1.size,
                    "mirrored": slot.top1.mirrored,
                    "local_x": slot.top1.local_x,
                    "local_y": slot.top1.local_y,
                    "screen_x": slot.top1.screen_x,
                    "screen_y": slot.top1.screen_y,
                    "confidence_level": slot.top1.confidence_level,
                }
            )
    save_debug_artifacts(screenshot_bgr, result, recognizer, out_dir)
    return result


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="敌方六只精灵头像透明模板库识别")
    parser.add_argument("--screenshot", help="游戏准备界面截图")
    parser.add_argument("--avatars", required=True, help="透明头像文件夹或 ZIP")
    parser.add_argument("--output", help="输出目录")
    parser.add_argument(
        "--warm-cache",
        action="store_true",
        help="只预热本地头像素材预处理缓存；同时给出截图和输出目录时会继续执行识别",
    )
    parser.add_argument(
        "--mirror-mode",
        choices=["enemy", "none", "both"],
        default=DEFAULT_MIRROR_MODE,
        help="模板镜像模式",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.warm_cache:
        try:
            cache_path = warm_avatar_variant_cache(args.avatars, mirror_mode=args.mirror_mode)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"头像预处理缓存已就绪: {cache_path}")
        if args.screenshot is None and args.output is None:
            return 0
    if args.screenshot is None or args.output is None:
        parser.error("--screenshot 和 --output 在执行识别时必填")
    result = write_outputs(
        args.screenshot,
        args.avatars,
        args.output,
        mirror_mode=args.mirror_mode,
    )
    for slot in result.slots:
        if slot.top1 is None:
            print(f"{slot.slot}: unknown")
            continue
        top1 = slot.top1
        print(
            f"{slot.slot}: {top1.label} | final={top1.final_score:.4f} "
            f"corr={top1.coarse_score:.4f} dE={top1.color_delta_e:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
