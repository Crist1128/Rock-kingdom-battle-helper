"""基于本地头像模板的敌方阵容截图识别工具。

当前模块只提供离线验证能力：按固定头像框裁剪截图中的敌方 6 个头像，
与 `data/rocom/recognition/elf_icons_128` 中的 128px 头像模板做相似度匹配，
输出每个位置的 Top N 候选，并可生成带框标注图。

注意：这不是候选硬判定逻辑，不写数据库，也不直接修改战斗阵容。
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

DEFAULT_REFERENCE_SIZE = (1150, 643)
DEFAULT_ENEMY_SLOT_BOXES_XYXY: tuple[tuple[int, int, int, int], ...] = (
    # 固定比例兜底框，优先使用黑色槽位/绿色血条动态定位。
    (1025, 129, 1089, 193),
    (1025, 188, 1089, 252),
    (1025, 246, 1089, 310),
    (1025, 306, 1089, 370),
    (1025, 365, 1089, 429),
    (1025, 425, 1089, 489),
)
FILENAME_PATTERN = re.compile(r"^(?P<dex_no>\d{3})_(?P<name>.+)\.(?:png|jpg|jpeg|webp)$", re.I)
SPATIAL_GRID_SIZE = 4
COLOR_HISTOGRAM_BINS = 4
MATCH_TOP_K_REFINEMENT_POOL_SIZE = 20
FOREGROUND_GRID_SIZE = 4


@dataclass(frozen=True)
class AvatarBox:
    """截图中的头像裁剪框。"""

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def xyxy(self) -> tuple[int, int, int, int]:
        """返回 Pillow crop 可用的 xyxy 坐标。"""
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def width(self) -> int:
        """返回框宽度。"""
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        """返回框高度。"""
        return self.y2 - self.y1

    def scaled(self, image_size: tuple[int, int], reference_size: tuple[int, int]) -> AvatarBox:
        """按截图尺寸相对参考截图尺寸缩放坐标。"""
        image_w, image_h = image_size
        ref_w, ref_h = reference_size
        scale_x = image_w / ref_w
        scale_y = image_h / ref_h
        return AvatarBox(
            x1=round(self.x1 * scale_x),
            y1=round(self.y1 * scale_y),
            x2=round(self.x2 * scale_x),
            y2=round(self.y2 * scale_y),
        )

    def clamped(self, image_size: tuple[int, int]) -> AvatarBox:
        """把坐标限制在截图范围内。"""
        image_w, image_h = image_size
        return AvatarBox(
            x1=max(0, min(image_w, self.x1)),
            y1=max(0, min(image_h, self.y1)),
            x2=max(0, min(image_w, self.x2)),
            y2=max(0, min(image_h, self.y2)),
        )


@dataclass(frozen=True)
class SlotLocalization:
    """敌方槽位定位结果。"""

    avatar_boxes: list[AvatarBox]
    method: str
    confidence: float
    slot_boxes: list[AvatarBox]


@dataclass(frozen=True)
class AvatarTemplate:
    """一个本地头像模板及其预计算特征。"""

    dex_no: str
    elf_name: str
    file_name: str
    path: Path
    is_confirmed: bool
    image: Image.Image
    histogram: tuple[float, ...]
    spatial_histogram: tuple[float, ...]
    hash_bits: tuple[int, ...]
    edge_hash_bits: tuple[int, ...]
    edge_spatial_histogram: tuple[float, ...]
    foreground_mask: tuple[int, ...]
    foreground_indices: tuple[int, ...]
    foreground_histogram: tuple[float, ...]
    shape_features: tuple[float, ...]


@dataclass(frozen=True)
class MatchCandidate:
    """单个截图头像与模板的匹配候选。"""

    dex_no: str
    elf_name: str
    file_name: str
    score: float
    spatial_score: float
    histogram_score: float
    pixel_score: float
    hash_score: float
    edge_score: float


@dataclass(frozen=True)
class PreparedCropFeatures:
    """截图头像裁切变体的预计算匹配特征。"""

    image: Image.Image
    histogram: tuple[float, ...]
    spatial_histogram: tuple[float, ...]
    hash_bits: tuple[int, ...]
    edge_hash_bits: tuple[int, ...]
    edge_spatial_histogram: tuple[float, ...]
    foreground_mask: tuple[int, ...]
    foreground_indices: tuple[int, ...]
    shape_features: tuple[float, ...]


@dataclass(frozen=True)
class SlotRecognition:
    """敌方阵容单个槽位的识别结果。"""

    slot_index: int
    box: AvatarBox
    candidates: list[MatchCandidate]
    location_method: str = "fixed_reference"
    location_confidence: float = 0.55


def default_enemy_slot_boxes(
    image_size: tuple[int, int],
    *,
    reference_size: tuple[int, int] = DEFAULT_REFERENCE_SIZE,
) -> list[AvatarBox]:
    """返回按截图尺寸缩放后的默认敌方 6 个头像框。"""
    boxes = [AvatarBox(*xyxy) for xyxy in DEFAULT_ENEMY_SLOT_BOXES_XYXY]
    if image_size == reference_size:
        return boxes
    return [box.scaled(image_size, reference_size) for box in boxes]


def _merge_ranges(ranges: list[tuple[int, int]], *, max_gap: int) -> list[tuple[int, int]]:
    """合并相邻距离较近的一维区间，模拟轻量闭运算。"""
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start - last_end <= max_gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _ranges_from_flags(flags: list[bool], *, offset: int = 0) -> list[tuple[int, int]]:
    """把布尔序列转换成连续为 True 的半开区间。"""
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, enabled in enumerate(flags):
        if enabled and start is None:
            start = index
        elif not enabled and start is not None:
            ranges.append((start + offset, index + offset))
            start = None
    if start is not None:
        ranges.append((start + offset, len(flags) + offset))
    return ranges


def _avatar_box_from_slot(slot: AvatarBox, image_size: tuple[int, int]) -> AvatarBox:
    """按槽位右端固定比例推算头像正方形裁切框。"""
    slot_h = max(1, slot.height)
    avatar_size = max(24, round(slot_h * 1.45))
    center_x = slot.x2 - slot_h * 0.55
    center_y = slot.y1 + slot_h * 0.50
    half = avatar_size / 2
    return AvatarBox(
        x1=round(center_x - half),
        y1=round(center_y - half),
        x2=round(center_x + half),
        y2=round(center_y + half),
    ).clamped(image_size)


def _localization_confidence(slot_boxes: list[AvatarBox], image_size: tuple[int, int]) -> float:
    """根据数量、间距和尺寸一致性估计定位置信度。"""
    if len(slot_boxes) != 6:
        return 0.0
    _w, image_h = image_size
    centers = [(box.y1 + box.y2) / 2 for box in slot_boxes]
    spacings = [centers[index + 1] - centers[index] for index in range(5)]
    avg_spacing = sum(spacings) / len(spacings)
    spacing_jitter = (
        sum(abs(spacing - avg_spacing) for spacing in spacings)
        / len(spacings)
        / max(avg_spacing, 1)
    )
    heights = [box.height for box in slot_boxes]
    avg_height = sum(heights) / len(heights)
    height_jitter = (
        sum(abs(height - avg_height) for height in heights) / len(heights) / max(avg_height, 1)
    )
    plausible_spacing = 0.05 * image_h <= avg_spacing <= 0.13 * image_h
    score = 0.98 - spacing_jitter * 1.6 - height_jitter * 1.2
    if not plausible_spacing:
        score -= 0.2
    return round(max(0.5, min(0.98, score)), 3)


def _select_six_regular_boxes(boxes: list[AvatarBox]) -> list[AvatarBox] | None:
    """从候选槽位中选择 y 间距最规则的一组六个框。"""
    if len(boxes) < 6:
        return None
    boxes = sorted(boxes, key=lambda item: (item.y1 + item.y2) / 2)
    if len(boxes) == 6:
        return boxes

    best_group: list[AvatarBox] | None = None
    best_score: float | None = None
    for start in range(0, len(boxes) - 5):
        group = boxes[start : start + 6]
        centers = [(box.y1 + box.y2) / 2 for box in group]
        spacings = [centers[index + 1] - centers[index] for index in range(5)]
        avg_spacing = sum(spacings) / len(spacings)
        if avg_spacing <= 0:
            continue
        spacing_jitter = sum(abs(spacing - avg_spacing) for spacing in spacings) / len(spacings)
        height_jitter = sum(abs(box.height - group[0].height) for box in group) / len(group)
        score = spacing_jitter + height_jitter
        if best_score is None or score < best_score:
            best_group = group
            best_score = score
    return best_group


def _regularize_slot_boxes(
    slot_boxes: list[AvatarBox],
    image_size: tuple[int, int],
) -> list[AvatarBox]:
    """利用敌方 6 个槽位等间距排列的 UI 约束，修正被头像亮部切断的槽位。"""
    if len(slot_boxes) != 6:
        return slot_boxes
    width, _height = image_size
    sorted_boxes = sorted(slot_boxes, key=lambda item: (item.y1 + item.y2) / 2)
    centers = [(box.y1 + box.y2) / 2 for box in sorted_boxes]
    regular_spacing = (centers[-1] - centers[0]) / 5
    regular_centers = [centers[0] + regular_spacing * index for index in range(6)]
    regular_height = sorted(box.height for box in sorted_boxes)[len(sorted_boxes) // 2]
    left_edge = min(box.x1 for box in sorted_boxes)
    detected_right_edge = max(box.x2 for box in sorted_boxes)
    # 有些截图里右端头像较亮，黑色检测会把槽位右边界切到头像内部；
    # 敌方头像列右边界在准备页 UI 中接近截图宽度 94.7%。
    right_edge = max(detected_right_edge, round(width * 0.947))

    regularized: list[AvatarBox] = []
    half_height = regular_height / 2
    for center_y in regular_centers:
        regularized.append(
            AvatarBox(
                x1=left_edge,
                y1=round(center_y - half_height),
                x2=right_edge,
                y2=round(center_y + half_height),
            ).clamped(image_size)
        )
    return regularized


def _detect_dark_slot_boxes(image: Image.Image) -> SlotLocalization | None:
    """主定位方案：检测右侧黑色圆角槽位，再按槽位右端裁头像。"""
    gray = image.convert("L")
    width, height = gray.size
    pixels = gray.load()
    x_start = round(width * 0.60)
    y_min = round(height * 0.12)
    y_max = round(height * 0.82)
    # 实际战斗准备页的槽位底色通常不是纯黑；阈值过低会只抓到头像暗部，
    # 阈值过高又可能把相邻槽位间的暗色连接起来，因此取中间值。
    dark_threshold = 70
    row_threshold = max(18, round(width * 0.035))

    row_flags: list[bool] = []
    for y in range(y_min, y_max):
        dark_count = 0
        for x in range(x_start, width):
            if pixels[x, y] < dark_threshold:
                dark_count += 1
        row_flags.append(dark_count >= row_threshold)

    row_ranges = _merge_ranges(
        _ranges_from_flags(row_flags, offset=y_min),
        max_gap=max(2, round(height * 0.008)),
    )
    candidate_slots: list[AvatarBox] = []
    min_slot_h = round(height * 0.035)
    max_slot_h = round(height * 0.12)
    min_slot_w = round(width * 0.08)
    max_slot_w = round(width * 0.28)

    for y1, y2 in row_ranges:
        band_h = y2 - y1
        if not (min_slot_h <= band_h <= max_slot_h):
            continue
        column_flags: list[bool] = []
        column_threshold = max(3, round(band_h * 0.35))
        for x in range(x_start, width):
            dark_count = 0
            for y in range(y1, y2):
                if pixels[x, y] < dark_threshold:
                    dark_count += 1
            column_flags.append(dark_count >= column_threshold)
        column_ranges = _merge_ranges(
            _ranges_from_flags(column_flags, offset=x_start),
            max_gap=max(3, round(width * 0.006)),
        )
        column_ranges = [
            (x1, x2) for x1, x2 in column_ranges if min_slot_w <= x2 - x1 <= max_slot_w
        ]
        if not column_ranges:
            continue
        x1, x2 = max(column_ranges, key=lambda item: (item[1] - item[0], item[1]))
        candidate_slots.append(AvatarBox(x1=x1, y1=y1, x2=x2, y2=y2))

    slot_boxes = _select_six_regular_boxes(candidate_slots)
    if slot_boxes is None:
        return None
    slot_boxes = _regularize_slot_boxes(slot_boxes, image.size)
    avatar_boxes = [_avatar_box_from_slot(slot, image.size) for slot in slot_boxes]
    return SlotLocalization(
        avatar_boxes=avatar_boxes,
        method="black_slot",
        confidence=_localization_confidence(slot_boxes, image.size),
        slot_boxes=slot_boxes,
    )


def _detect_green_bar_boxes(image: Image.Image) -> SlotLocalization | None:
    """备用定位方案：检测右侧绿色血条，根据血条位置反推头像框。"""
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    x_start = round(width * 0.62)
    y_min = round(height * 0.12)
    y_max = round(height * 0.82)
    row_threshold = max(10, round(width * 0.018))
    row_flags: list[bool] = []

    for y in range(y_min, y_max):
        green_count = 0
        for x in range(x_start, width):
            r, g, b = pixels[x, y]
            if g >= 85 and g > r * 1.25 and g > b * 1.15 and r <= 140:
                green_count += 1
        row_flags.append(green_count >= row_threshold)

    bar_ranges = _merge_ranges(
        _ranges_from_flags(row_flags, offset=y_min),
        max_gap=max(1, round(height * 0.004)),
    )
    bar_ranges = [(y1, y2) for y1, y2 in bar_ranges if 2 <= y2 - y1 <= max(10, height * 0.025)]
    if len(bar_ranges) < 6:
        return None
    bar_centers = sorted((y1 + y2) / 2 for y1, y2 in bar_ranges)
    if len(bar_centers) > 6:
        # 取间距最规则的连续六条血条。
        best: list[float] | None = None
        best_score: float | None = None
        for start in range(0, len(bar_centers) - 5):
            group = bar_centers[start : start + 6]
            spacings = [group[index + 1] - group[index] for index in range(5)]
            avg_spacing = sum(spacings) / len(spacings)
            score = sum(abs(spacing - avg_spacing) for spacing in spacings) / len(spacings)
            if best_score is None or score < best_score:
                best = group
                best_score = score
        if best is None:
            return None
        bar_centers = best

    spacings = [bar_centers[index + 1] - bar_centers[index] for index in range(5)]
    avg_spacing = sum(spacings) / len(spacings)
    avatar_size = max(32, round(avg_spacing * 1.05))
    center_x = width * 0.92
    avatar_boxes: list[AvatarBox] = []
    slot_boxes: list[AvatarBox] = []
    for center_y in bar_centers:
        avatar_center_y = center_y - avg_spacing * 0.15
        half = avatar_size / 2
        avatar_boxes.append(
            AvatarBox(
                x1=round(center_x - half),
                y1=round(avatar_center_y - half),
                x2=round(center_x + half),
                y2=round(avatar_center_y + half),
            ).clamped(image.size)
        )
        slot_h = avg_spacing * 0.75
        slot_boxes.append(
            AvatarBox(
                x1=round(width * 0.76),
                y1=round(avatar_center_y - slot_h / 2),
                x2=round(width * 0.97),
                y2=round(avatar_center_y + slot_h / 2),
            ).clamped(image.size)
        )

    return SlotLocalization(
        avatar_boxes=avatar_boxes,
        method="green_hp_bar",
        confidence=0.72,
        slot_boxes=slot_boxes,
    )


def locate_enemy_avatar_boxes(image: Image.Image) -> SlotLocalization:
    """三层定位策略：黑色槽位检测、绿色血条检测、固定比例兜底。"""
    dark_result = _detect_dark_slot_boxes(image)
    if dark_result is not None:
        return dark_result
    green_result = _detect_green_bar_boxes(image)
    if green_result is not None:
        return green_result
    avatar_boxes = default_enemy_slot_boxes(image.size)
    return SlotLocalization(
        avatar_boxes=avatar_boxes,
        method="fixed_reference",
        confidence=0.55,
        slot_boxes=[],
    )


def load_boxes_from_json(path: str | Path) -> list[AvatarBox]:
    """从 JSON 文件读取头像框，支持 xyxy 或 x/y/w/h 两种格式。"""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("box JSON must be a list")
    boxes: list[AvatarBox] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"box row {index} must be an object")
        if {"x1", "y1", "x2", "y2"} <= row.keys():
            boxes.append(
                AvatarBox(
                    x1=int(row["x1"]),
                    y1=int(row["y1"]),
                    x2=int(row["x2"]),
                    y2=int(row["y2"]),
                )
            )
        elif {"x", "y", "w", "h"} <= row.keys():
            x = int(row["x"])
            y = int(row["y"])
            boxes.append(AvatarBox(x1=x, y1=y, x2=x + int(row["w"]), y2=y + int(row["h"])))
        else:
            raise ValueError(f"box row {index} must contain x1/y1/x2/y2 or x/y/w/h")
    return boxes


def _flatten_rgba(
    image: Image.Image,
    background: tuple[int, int, int] = (28, 28, 28),
) -> Image.Image:
    """把透明图层压到固定背景，避免透明区域干扰相似度。"""
    rgba = image.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (*background, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


def _prepare_image(image: Image.Image, size: int = 64) -> Image.Image:
    """统一输入图像尺寸和色彩空间，用于模板匹配。"""
    rgb = _flatten_rgba(image)
    return ImageOps.pad(rgb, (size, size), method=Image.Resampling.LANCZOS, color=(28, 28, 28))


def _prepare_alpha_mask(
    image: Image.Image,
    size: int = 64,
    *,
    detect_opaque_foreground: bool = True,
) -> tuple[int, ...]:
    """把模板透明通道标准化为前景 mask，用于只比较精灵主体。"""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    padded = ImageOps.pad(alpha, (size, size), method=Image.Resampling.LANCZOS, color=0)
    circle = _circle_mask(size)
    alpha_values = list(padded.getdata())
    circle_values = list(circle.getdata())
    mask = tuple(
        1 if alpha > 24 and circle_values[index] > 0 else 0
        for index, alpha in enumerate(alpha_values)
    )
    mask_area = sum(mask)
    if mask_area < size * size * 0.05 or (
        detect_opaque_foreground and mask_area > size * size * 0.65
    ):
        # 旧版本素材大多是米色/灰色实底 PNG，没有有效透明通道。
        # 这时不能退回整圆，否则“形状”特征等价于没有特征；
        # 改为按边缘背景色估计精灵主体轮廓，提升对换色皮肤的鲁棒性。
        return _foreground_mask_by_background(_prepare_image(image, size=size))
    return mask


def _mask_indices(mask: tuple[int, ...]) -> tuple[int, ...]:
    """把 0/1 mask 转换成前景像素索引，加速重复比较。"""
    return tuple(index for index, enabled in enumerate(mask) if enabled)


def _foreground_mask_from_crop(image: Image.Image) -> tuple[int, ...]:
    """从截图头像裁片中估计非黑底头像主体 mask，主要用于颜色变化场景。"""
    background_mask = _foreground_mask_by_background(image)
    rgb = image.convert("RGB")
    circle = _circle_mask(rgb.size[0])
    rgb_array = np.asarray(rgb, dtype=np.int16)
    circle_array = np.asarray(circle, dtype=np.bool_)
    brightness = rgb_array.mean(axis=2)
    chroma = rgb_array.max(axis=2) - rgb_array.min(axis=2)
    # 排除黑色圆底；保留高亮白色、粉色、蓝色、紫色等头像主体。
    old_array = circle_array & ((brightness >= 82) | ((brightness >= 55) & (chroma >= 22)))
    old_mask = tuple(int(value) for value in old_array.reshape(-1).tolist())
    circle_values = tuple(int(value) for value in circle_array.reshape(-1).tolist())
    circle_area = max(1, sum(1 for value in circle_values if value))
    background_area = sum(background_mask)
    old_area = sum(old_mask)
    # 新头像模板为透明高清主体，截图裁片若带有大面积橙色描边/黑底，
    # 旧亮度/色度启发式会把 UI 背景也纳入前景，导致轮廓特征退化成“大圆”。
    # 当亮色启发式明显比背景差分更膨胀时，优先信任背景差分得到的主体轮廓。
    if old_area / circle_area > 0.70 and background_area / circle_area < 0.58:
        return background_mask
    # 其他场景仍合并两种策略，避免白色/浅色主体被背景差分漏掉。
    return tuple(
        1 if left or right else 0
        for left, right in zip(background_mask, old_mask, strict=True)
    )


def _median_color(colors: list[tuple[int, int, int]]) -> tuple[float, float, float]:
    """返回 RGB 三通道中位数，避免边框高亮少量像素污染背景估计。"""
    if not colors:
        return (28.0, 28.0, 28.0)
    channels = list(zip(*colors, strict=True))
    return tuple(float(sorted(channel)[len(channel) // 2]) for channel in channels)  # type: ignore[return-value]


def _background_palette(colors: list[tuple[int, int, int]]) -> list[tuple[float, float, float]]:
    """从边缘像素估计一组背景色，兼容黑底 + 橙色描边这类多背景截图。"""
    if not colors:
        return [(28.0, 28.0, 28.0)]
    buckets: dict[tuple[int, int, int], int] = {}
    for r, g, b in colors:
        key = (r // 16, g // 16, b // 16)
        buckets[key] = buckets.get(key, 0) + 1
    popular = sorted(buckets.items(), key=lambda item: item[1], reverse=True)[:4]
    palette = [_median_color(colors)]
    palette.extend(
        (key[0] * 16 + 8.0, key[1] * 16 + 8.0, key[2] * 16 + 8.0)
        for key, _count in popular
    )
    unique: list[tuple[float, float, float]] = []
    for color in palette:
        if color not in unique:
            unique.append(color)
    return unique


def _foreground_mask_by_background(image: Image.Image) -> tuple[int, ...]:
    """根据边缘背景色估计头像主体轮廓。

    该方法不直接依赖颜色类别，只判断“是否明显不同于头像框背景”，
    因此比 RGB 直方图更适合雪影娃娃这类换色/皮肤变化的头像。
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    rgb_array = np.asarray(rgb, dtype=np.float32)
    border = max(2, round(min(width, height) * 0.08))
    border_mask = np.zeros((height, width), dtype=np.bool_)
    border_mask[:border, :] = True
    border_mask[height - border :, :] = True
    border_mask[:, :border] = True
    border_mask[:, width - border :] = True
    border_colors = [
        tuple(int(channel) for channel in color)
        for color in rgb_array[border_mask].astype(np.uint8).tolist()
    ]
    background_candidates = _background_palette(border_colors)
    circle = _circle_mask(width)
    circle_array = np.asarray(circle, dtype=np.bool_)
    circle_values = tuple(int(value) for value in circle_array.reshape(-1).tolist())
    background_array = np.asarray(background_candidates, dtype=np.float32)
    chroma_array = rgb_array.max(axis=2) - rgb_array.min(axis=2)
    # height x width x 背景色数量
    distances = np.sqrt(
        ((rgb_array[:, :, None, :] - background_array[None, None, :, :]) ** 2).sum(axis=3)
    )
    min_distances = distances.min(axis=2)

    def build_mask(distance_threshold: float) -> list[int]:
        # 背景可能是黑色、米色或深橙 UI 边框；先排除所有常见边缘背景色，
        # 再允许高色度像素以较低阈值进入，避免漏掉发色/皮肤换色后的主体。
        enabled = circle_array & (
            (min_distances >= distance_threshold)
            | ((min_distances >= distance_threshold * 0.72) & (chroma_array >= 46))
        )
        return [int(value) for value in enabled.reshape(-1).tolist()]

    raw = build_mask(42.0)
    circle_area = max(1, sum(1 for value in circle_values if value))
    if sum(raw) / circle_area > 0.82:
        # 若几乎整圆都被判为前景，说明背景估计过松；提高阈值避免退化成“无形状”。
        raw = build_mask(62.0)
    if sum(raw) / circle_area < 0.03:
        # 极端低对比素材保底使用中心圆，避免完全失效。
        raw = [1 if value else 0 for value in circle_values]
    return _clean_foreground_mask(tuple(raw), width, height)


def _clean_foreground_mask(mask: tuple[int, ...], width: int, height: int) -> tuple[int, ...]:
    """对前景 mask 做一次轻量开闭运算，减少 UI 噪点对形状比较的影响。"""
    mask_image = Image.new("L", (width, height), 0)
    mask_image.putdata([255 if value else 0 for value in mask])
    # Pillow 的滤镜在 C 层执行，比 Python 双重循环快很多；MedianFilter 能去掉零散噪点，
    # 同时保留头像主体的大致轮廓。
    cleaned = mask_image.filter(ImageFilter.MedianFilter(3))
    return tuple(1 if value >= 128 else 0 for value in cleaned.getdata())


def _mask_shape_features(
    mask: tuple[int, ...],
    *,
    size: int = 64,
    grid_size: int = FOREGROUND_GRID_SIZE,
) -> tuple[float, ...]:
    """提取与颜色无关的轮廓统计特征：面积、质心、方差、分块占比和投影。"""
    points = [index for index, enabled in enumerate(mask) if enabled]
    total_pixels = size * size
    if not points:
        return (0.0,) * (5 + grid_size * grid_size + grid_size * 2)

    xs = [index % size for index in points]
    ys = [index // size for index in points]
    count = len(points)
    mean_x = sum(xs) / count / size
    mean_y = sum(ys) / count / size
    std_x = math.sqrt(sum((x / size - mean_x) ** 2 for x in xs) / count)
    std_y = math.sqrt(sum((y / size - mean_y) ** 2 for y in ys) / count)

    features: list[float] = [count / total_pixels, mean_x, mean_y, std_x, std_y]
    for grid_y in range(grid_size):
        for grid_x in range(grid_size):
            x_start = size * grid_x // grid_size
            x_end = size * (grid_x + 1) // grid_size
            y_start = size * grid_y // grid_size
            y_end = size * (grid_y + 1) // grid_size
            cell_area = max(1, (x_end - x_start) * (y_end - y_start))
            enabled = 0
            for y in range(y_start, y_end):
                row_offset = y * size
                for x in range(x_start, x_end):
                    enabled += mask[row_offset + x]
            features.append(enabled / cell_area)

    for grid_y in range(grid_size):
        y_start = size * grid_y // grid_size
        y_end = size * (grid_y + 1) // grid_size
        enabled = sum(mask[y * size + x] for y in range(y_start, y_end) for x in range(size))
        features.append(enabled / max(1, (y_end - y_start) * size))
    for grid_x in range(grid_size):
        x_start = size * grid_x // grid_size
        x_end = size * (grid_x + 1) // grid_size
        enabled = sum(mask[y * size + x] for y in range(size) for x in range(x_start, x_end))
        features.append(enabled / max(1, (x_end - x_start) * size))

    return tuple(features)


def _shape_feature_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """把轮廓统计特征的平均绝对差转换为 0-1 相似度。"""
    if not left or not right:
        return 0.0
    distance = sum(abs(a - b) for a, b in zip(left, right, strict=True)) / len(left)
    return max(0.0, 1.0 - distance * 3.0)


def _mask_iou(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    """计算两个二值 mask 的 IoU，相同形状越接近 1。"""
    intersection = 0
    union = 0
    for left_value, right_value in zip(left, right, strict=True):
        if left_value or right_value:
            union += 1
            if left_value and right_value:
                intersection += 1
    if union == 0:
        return 0.0
    return intersection / union


def _circle_mask(size: int = 64, radius_ratio: float = 0.48) -> Image.Image:
    """生成中心圆形 mask，用于弱化方形头像框四角背景。"""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = size * radius_ratio
    center = size / 2
    draw.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=255,
    )
    return mask


def _color_histogram(image: Image.Image, *, bins: int = COLOR_HISTOGRAM_BINS) -> tuple[float, ...]:
    """计算中心圆形区域内的 RGB 量化直方图。"""
    rgb = image.convert("RGB")
    mask = _circle_mask(rgb.size[0])
    pixels = rgb.load()
    mask_pixels = mask.load()
    counts = [0] * (bins**3)
    total = 0
    for y in range(rgb.size[1]):
        for x in range(rgb.size[0]):
            if not mask_pixels[x, y]:
                continue
            r, g, b = pixels[x, y]
            ri = min(bins - 1, r * bins // 256)
            gi = min(bins - 1, g * bins // 256)
            bi = min(bins - 1, b * bins // 256)
            counts[(ri * bins + gi) * bins + bi] += 1
            total += 1
    if total == 0:
        return tuple(0.0 for _ in counts)
    return tuple(count / total for count in counts)


def _masked_color_histogram(
    image: Image.Image,
    mask_indices: tuple[int, ...],
    *,
    bins: int = COLOR_HISTOGRAM_BINS,
) -> tuple[float, ...]:
    """在给定 mask 区域内计算 RGB 量化直方图。"""
    rgb = image.convert("RGB")
    pixels = list(rgb.getdata())
    counts = [0] * (bins**3)
    for index in mask_indices:
        r, g, b = pixels[index]
        ri = min(bins - 1, r * bins // 256)
        gi = min(bins - 1, g * bins // 256)
        bi = min(bins - 1, b * bins // 256)
        counts[(ri * bins + gi) * bins + bi] += 1
    total = len(mask_indices)
    if total == 0:
        return tuple(0.0 for _ in counts)
    return tuple(count / total for count in counts)


def _spatial_color_histogram(
    image: Image.Image,
    *,
    grid_size: int = SPATIAL_GRID_SIZE,
    bins: int = COLOR_HISTOGRAM_BINS,
) -> tuple[float, ...]:
    """计算分块颜色直方图，保留头像局部颜色分布以减少同色误判。"""
    rgb = image.convert("RGB")
    mask = _circle_mask(rgb.size[0])
    pixels = rgb.load()
    mask_pixels = mask.load()
    width, height = rgb.size
    features: list[float] = []

    for grid_y in range(grid_size):
        for grid_x in range(grid_size):
            counts = [0] * (bins**3)
            total = 0
            x_start = width * grid_x // grid_size
            x_end = width * (grid_x + 1) // grid_size
            y_start = height * grid_y // grid_size
            y_end = height * (grid_y + 1) // grid_size

            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    if not mask_pixels[x, y]:
                        continue
                    r, g, b = pixels[x, y]
                    ri = min(bins - 1, r * bins // 256)
                    gi = min(bins - 1, g * bins // 256)
                    bi = min(bins - 1, b * bins // 256)
                    counts[(ri * bins + gi) * bins + bi] += 1
                    total += 1

            if total == 0:
                features.extend(0.0 for _ in counts)
            else:
                features.extend(count / total for count in counts)
    return tuple(features)


def _average_hash(image: Image.Image, *, size: int = 16) -> tuple[int, ...]:
    """计算简单感知哈希，用于辅助区分轮廓。"""
    gray = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    values = list(gray.getdata())
    avg = sum(values) / len(values)
    return tuple(1 if value >= avg else 0 for value in values)


def _edge_hash(image: Image.Image, *, size: int = 16) -> tuple[int, ...]:
    """计算边缘图感知哈希，弱化颜色相近但轮廓不同的误判。"""
    gray = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    values = list(edges.getdata())
    avg = sum(values) / len(values)
    return tuple(1 if value >= avg else 0 for value in values)


def _edge_spatial_histogram(
    image: Image.Image,
    *,
    grid_size: int = SPATIAL_GRID_SIZE,
) -> tuple[float, ...]:
    """计算边缘强度的空间分布，用于颜色变化时的形状匹配。"""
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    mask = _circle_mask(edges.size[0])
    edge_pixels = edges.load()
    mask_pixels = mask.load()
    width, height = edges.size
    features: list[float] = []
    total_strength = 0.0

    for grid_y in range(grid_size):
        for grid_x in range(grid_size):
            strength = 0.0
            x_start = width * grid_x // grid_size
            x_end = width * (grid_x + 1) // grid_size
            y_start = height * grid_y // grid_size
            y_end = height * (grid_y + 1) // grid_size
            for y in range(y_start, y_end):
                for x in range(x_start, x_end):
                    if mask_pixels[x, y]:
                        strength += edge_pixels[x, y]
            features.append(strength)
            total_strength += strength

    if total_strength <= 0:
        return tuple(0.0 for _ in features)
    return tuple(value / total_strength for value in features)


def _histogram_intersection(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """计算两个归一化直方图的交集相似度。"""
    return sum(min(a, b) for a, b in zip(left, right, strict=True))


def _spatial_histogram_intersection(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """计算分块直方图平均交集相似度。"""
    raw_intersection = _histogram_intersection(left, right)
    return raw_intersection / (SPATIAL_GRID_SIZE**2)


def _hash_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    """计算两个二值哈希的相似度。"""
    same = sum(1 for a, b in zip(left, right, strict=True) if a == b)
    return same / len(left)


def _pixel_similarity(left: Image.Image, right: Image.Image) -> float:
    """计算中心圆形区域的像素均方根相似度。"""
    left_rgb = left.convert("RGB")
    right_rgb = right.convert("RGB")
    mask = _circle_mask(left_rgb.size[0])
    left_pixels = left_rgb.load()
    right_pixels = right_rgb.load()
    mask_pixels = mask.load()
    total = 0
    squared_error = 0.0
    for y in range(left_rgb.size[1]):
        for x in range(left_rgb.size[0]):
            if not mask_pixels[x, y]:
                continue
            lp = left_pixels[x, y]
            rp = right_pixels[x, y]
            squared_error += sum((lp[i] - rp[i]) ** 2 for i in range(3)) / 3
            total += 1
    if total == 0:
        return 0.0
    rmse = math.sqrt(squared_error / total)
    return max(0.0, 1.0 - rmse / 255)


def _masked_pixel_similarity(
    left: Image.Image,
    right: Image.Image,
    mask_indices: tuple[int, ...],
) -> float:
    """只在模板前景 mask 区域计算像素相似度。"""
    left_pixels = list(left.convert("RGB").getdata())
    right_pixels = list(right.convert("RGB").getdata())
    squared_error = 0.0
    for pixel_index in mask_indices:
        lp = left_pixels[pixel_index]
        rp = right_pixels[pixel_index]
        squared_error += sum((lp[index] - rp[index]) ** 2 for index in range(3)) / 3
    total = len(mask_indices)
    if total == 0:
        return 0.0
    rmse = math.sqrt(squared_error / total)
    return max(0.0, 1.0 - rmse / 255)


def _crop_ratio(image: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    """按比例裁切图片，比例坐标为 left/top/right/bottom。"""
    width, height = image.size
    left, top, right, bottom = box
    return image.crop(
        (
            round(width * left),
            round(height * top),
            round(width * right),
            round(height * bottom),
        )
    )


def _foreground_bbox_from_mask(
    mask: tuple[int, ...],
    *,
    size: int = 64,
) -> tuple[int, int, int, int] | None:
    """根据前景 mask 返回最小外接框，坐标为 Pillow crop 的左上右下。"""
    points = [index for index, enabled in enumerate(mask) if enabled]
    if not points:
        return None
    xs = [index % size for index in points]
    ys = [index // size for index in points]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _foreground_focused_variant(image: Image.Image) -> Image.Image | None:
    """把裁片中的疑似头像主体重新居中放大，减少黑底/橙边占比。"""
    prepared = _prepare_image(image)
    mask = _foreground_mask_by_background(prepared)
    bbox = _foreground_bbox_from_mask(mask, size=prepared.size[0])
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    area_ratio = sum(mask) / max(1, prepared.size[0] * prepared.size[1])
    # 前景过大说明本来就贴近模板；过小则多半是噪点，均不额外生成聚焦变体。
    if area_ratio < 0.06 or area_ratio > 0.55:
        return None
    if max(width, height) > prepared.size[0] * 0.86:
        return None

    padding = round(max(width, height) * 0.18)
    side = max(width, height) + padding * 2
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    crop_left = round(center_x - side / 2)
    crop_top = round(center_y - side / 2)
    crop_right = round(center_x + side / 2)
    crop_bottom = round(center_y + side / 2)
    crop_left = max(0, crop_left)
    crop_top = max(0, crop_top)
    crop_right = min(prepared.size[0], crop_right)
    crop_bottom = min(prepared.size[1], crop_bottom)
    if crop_right - crop_left < 12 or crop_bottom - crop_top < 12:
        return None
    focused = prepared.crop((crop_left, crop_top, crop_right, crop_bottom))
    return ImageOps.pad(
        focused,
        prepared.size,
        method=Image.Resampling.LANCZOS,
        color=(28, 28, 28),
    )


def _prepare_crop_variants(crop: Image.Image) -> list[Image.Image]:
    """生成多种轻微缩放/偏移的头像裁切变体，提高对定位误差的容忍度。"""
    # 敌方头像框有时会多带左侧黑底或右侧边缘，轻微中心裁切和横向偏移可提升鲁棒性。
    ratio_boxes = (
        (0.00, 0.00, 1.00, 1.00),
        (0.04, 0.04, 0.96, 0.96),
        (0.08, 0.04, 1.00, 0.96),
    )
    variants = [_prepare_image(_crop_ratio(crop, box)) for box in ratio_boxes]
    focused = _foreground_focused_variant(crop)
    if focused is not None:
        variants.append(focused)
    return variants



def _parse_template_file(path: Path) -> tuple[str, str] | None:
    """从模板文件名解析图鉴编号和精灵名。"""
    match = FILENAME_PATTERN.match(path.name)
    if match is None:
        return None
    return match.group("dex_no"), match.group("name")


def _iter_template_files(
    icons_dir: Path,
    *,
    mirror_templates: bool,
    include_confirmed_templates: bool,
) -> list[tuple[Path, bool, bool]]:
    """返回模板文件及其是否需要镜像。

    原始图鉴头像需要按敌方朝向做水平镜像；人工确认/标注截图裁出的模板已经是敌方朝向，
    因此从 `*_confirmed` 目录加载时不再镜像，避免双重翻转。
    """
    template_roots: list[tuple[Path, bool, bool]] = [(icons_dir, mirror_templates, False)]
    confirmed_dir = icons_dir.parent / f"{icons_dir.name}_confirmed"
    if include_confirmed_templates and confirmed_dir.is_dir():
        template_roots.append((confirmed_dir, False, True))

    files: list[tuple[Path, bool, bool]] = []
    for root, should_mirror, is_confirmed in template_roots:
        for path in sorted(root.iterdir()):
            if path.is_file() and _parse_template_file(path) is not None:
                files.append((path, should_mirror, is_confirmed))
    return files


@lru_cache(maxsize=4)
def load_avatar_templates(
    icons_dir: str | Path,
    *,
    mirror_templates: bool = True,
    include_confirmed_templates: bool = False,
) -> list[AvatarTemplate]:
    """加载头像模板目录。

    敌方头像在战斗准备页中相对图鉴头像是水平镜像显示，因此默认在内存中镜像模板；
    不直接覆盖素材文件，便于后续仍保留原始图鉴头像。

    注意：`*_confirmed` 人工确认裁图默认不参与线上识别，避免少量样例污染全局匹配。
    若后续要做样本增强，必须显式开启并使用足够多、按精灵归档的样本集。
    """
    root = Path(icons_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"avatar icons dir not found: {root}")

    templates: list[AvatarTemplate] = []
    for path, should_mirror, is_confirmed in _iter_template_files(
        root,
        mirror_templates=mirror_templates,
        include_confirmed_templates=include_confirmed_templates,
    ):
        parsed = _parse_template_file(path)
        if parsed is None:  # pragma: no cover - 由 _iter_template_files 过滤，保留防御式判断。
            continue
        dex_no, elf_name = parsed
        source_image = Image.open(path)
        if should_mirror:
            source_image = ImageOps.mirror(source_image)
        prepared = _prepare_image(source_image)
        foreground_mask = _prepare_alpha_mask(
            source_image,
            detect_opaque_foreground=is_confirmed,
        )
        foreground_indices = _mask_indices(foreground_mask)
        shape_features = _mask_shape_features(foreground_mask)
        templates.append(
            AvatarTemplate(
                dex_no=dex_no,
                elf_name=elf_name,
                file_name=path.name,
                path=path,
                is_confirmed=is_confirmed,
                image=prepared,
                histogram=_color_histogram(prepared),
                spatial_histogram=_spatial_color_histogram(prepared),
                hash_bits=_average_hash(prepared),
                edge_hash_bits=_edge_hash(prepared),
                edge_spatial_histogram=_edge_spatial_histogram(prepared),
                foreground_mask=foreground_mask,
                foreground_indices=foreground_indices,
                foreground_histogram=_masked_color_histogram(prepared, foreground_indices),
                shape_features=shape_features,
            )
        )
    if not templates:
        raise ValueError(f"no avatar templates loaded from {root}")
    return templates


def match_avatar_crop(
    crop: Image.Image,
    templates: list[AvatarTemplate],
    *,
    top_k: int = 5,
) -> list[MatchCandidate]:
    """把单个头像裁剪图与模板库匹配，返回 Top N 候选。"""
    prepared_variants = _prepare_crop_variants(crop)
    variant_features = [
        PreparedCropFeatures(
            image=prepared,
            histogram=_color_histogram(prepared),
            spatial_histogram=_spatial_color_histogram(prepared),
            hash_bits=_average_hash(prepared),
            edge_hash_bits=_edge_hash(prepared),
            edge_spatial_histogram=_edge_spatial_histogram(prepared),
            foreground_mask=foreground_mask,
            foreground_indices=_mask_indices(foreground_mask),
            shape_features=_mask_shape_features(foreground_mask),
        )
        for prepared in prepared_variants
        for foreground_mask in [_foreground_mask_from_crop(prepared)]
    ]
    coarse_rows: list[tuple[float, AvatarTemplate]] = []
    for template in templates:
        best_coarse_score = -1.0
        for features in variant_features:
            spatial_score = _spatial_histogram_intersection(
                features.spatial_histogram,
                template.spatial_histogram,
            )
            histogram_score = _histogram_intersection(features.histogram, template.histogram)
            hash_score = _hash_similarity(features.hash_bits, template.hash_bits)
            edge_score = _hash_similarity(features.edge_hash_bits, template.edge_hash_bits)
            edge_spatial_score = _histogram_intersection(
                features.edge_spatial_histogram,
                template.edge_spatial_histogram,
            )
            silhouette_score = _mask_iou(features.foreground_mask, template.foreground_mask)
            shape_score = _shape_feature_similarity(
                features.shape_features,
                template.shape_features,
            )
            # 识别模板已切换为更清晰、透明背景更干净的头像素材；
            # 粗排阶段更重视前景轮廓/形状与边缘分布，降低整圆颜色直方图对 UI 背景的敏感度。
            coarse_score = (
                spatial_score * 0.22
                + histogram_score * 0.08
                + hash_score * 0.05
                + edge_score * 0.12
                + edge_spatial_score * 0.20
                + silhouette_score * 0.20
                + shape_score * 0.13
            )
            best_coarse_score = max(best_coarse_score, coarse_score)
        coarse_rows.append((best_coarse_score, template))

    candidates: list[MatchCandidate] = []
    refinement_pool_size = min(
        len(coarse_rows),
        max(top_k, MATCH_TOP_K_REFINEMENT_POOL_SIZE),
    )
    refinement_templates = [
        template
        for _score, template in sorted(
            coarse_rows,
            key=lambda item: item[0],
            reverse=True,
        )[:refinement_pool_size]
    ]

    for template in refinement_templates:
        best_score = -1.0
        best_parts: tuple[float, float, float, float, float] | None = None
        for features in variant_features:
            spatial_score = _spatial_histogram_intersection(
                features.spatial_histogram,
                template.spatial_histogram,
            )
            histogram_score = _histogram_intersection(
                features.histogram,
                template.histogram,
            )
            pixel_score = _pixel_similarity(features.image, template.image)
            hash_score = _hash_similarity(
                features.hash_bits,
                template.hash_bits,
            )
            edge_score = _hash_similarity(
                features.edge_hash_bits,
                template.edge_hash_bits,
            )
            edge_spatial_score = _histogram_intersection(
                features.edge_spatial_histogram,
                template.edge_spatial_histogram,
            )
            silhouette_score = _mask_iou(features.foreground_mask, template.foreground_mask)
            shape_score = _shape_feature_similarity(
                features.shape_features,
                template.shape_features,
            )
            foreground_pixel_score = _masked_pixel_similarity(
                features.image,
                template.image,
                template.foreground_indices,
            )
            foreground_hist_score = _histogram_intersection(
                _masked_color_histogram(features.image, template.foreground_indices),
                template.foreground_histogram,
            )
            # 精排阶段继续偏向模板透明前景区域，避免准备页黑底/描边/血条纹理压过头像主体。
            score = (
                spatial_score * 0.16
                + histogram_score * 0.04
                + pixel_score * 0.06
                + hash_score * 0.04
                + edge_score * 0.10
                + edge_spatial_score * 0.18
                + silhouette_score * 0.18
                + shape_score * 0.12
                + foreground_pixel_score * 0.08
                + foreground_hist_score * 0.04
            )
            if score > best_score:
                best_score = score
                best_parts = (
                    spatial_score,
                    histogram_score,
                    pixel_score,
                    hash_score,
                    edge_score,
                )
        if best_parts is None:
            continue
        spatial_score, histogram_score, pixel_score, hash_score, edge_score = best_parts
        candidates.append(
            MatchCandidate(
                dex_no=template.dex_no,
                elf_name=template.elf_name,
                file_name=template.file_name,
                score=round(best_score, 6),
                spatial_score=round(spatial_score, 6),
                histogram_score=round(histogram_score, 6),
                pixel_score=round(pixel_score, 6),
                hash_score=round(hash_score, 6),
                edge_score=round(edge_score, 6),
            )
        )
    deduplicated: list[MatchCandidate] = []
    seen_keys: set[tuple[str, str]] = set()
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        key = (candidate.dex_no, candidate.elf_name)
        if key in seen_keys:
            continue
        deduplicated.append(candidate)
        seen_keys.add(key)
        if len(deduplicated) >= top_k:
            break
    return deduplicated


def recognize_enemy_lineup(
    screenshot_path: str | Path,
    icons_dir: str | Path,
    *,
    boxes: list[AvatarBox] | None = None,
    top_k: int = 5,
) -> list[SlotRecognition]:
    """识别准备页截图右侧敌方阵容头像，并返回每个槽位的候选结果。"""
    from app.recognition.avatar.service import AvatarRecognitionService

    screenshot = Image.open(screenshot_path)
    avatar_service = AvatarRecognitionService(icons_dir)
    localization = (
        SlotLocalization(
            avatar_boxes=boxes,
            method="custom_boxes",
            confidence=1.0,
            slot_boxes=[],
        )
        if boxes is not None
        else locate_enemy_avatar_boxes(screenshot)
    )
    results: list[SlotRecognition] = []
    for index, box in enumerate(localization.avatar_boxes, start=1):
        crop = screenshot.crop(box.xyxy)
        crop_recognition = avatar_service.recognize_crop(crop, top_k=top_k)
        results.append(
            SlotRecognition(
                slot_index=index,
                box=box,
                candidates=crop_recognition.candidates,
                location_method=localization.method,
                location_confidence=localization.confidence,
            )
        )
    return results


def recognize_enemy_lineup_image(
    screenshot: Image.Image,
    icons_dir: str | Path,
    *,
    boxes: list[AvatarBox] | None = None,
    top_k: int = 5,
) -> list[SlotRecognition]:
    """识别内存中的准备页截图，供 API 上传文件入口复用。"""
    from app.recognition.avatar.service import AvatarRecognitionService

    avatar_service = AvatarRecognitionService(icons_dir)
    localization = (
        SlotLocalization(
            avatar_boxes=boxes,
            method="custom_boxes",
            confidence=1.0,
            slot_boxes=[],
        )
        if boxes is not None
        else locate_enemy_avatar_boxes(screenshot)
    )
    results: list[SlotRecognition] = []
    for index, box in enumerate(localization.avatar_boxes, start=1):
        crop = screenshot.crop(box.xyxy)
        crop_recognition = avatar_service.recognize_crop(crop, top_k=top_k)
        results.append(
            SlotRecognition(
                slot_index=index,
                box=box,
                candidates=crop_recognition.candidates,
                location_method=localization.method,
                location_confidence=localization.confidence,
            )
        )
    return results


def recognition_to_dict(results: list[SlotRecognition]) -> dict[str, Any]:
    """把识别结果转换为可 JSON 序列化的结构。"""
    return {
        "slots": [
            {
                "slot_index": result.slot_index,
                "box": {
                    "x1": result.box.x1,
                    "y1": result.box.y1,
                    "x2": result.box.x2,
                    "y2": result.box.y2,
                },
                "location_method": result.location_method,
                "location_confidence": result.location_confidence,
                "candidates": [
                    {
                        "dex_no": candidate.dex_no,
                        "elf_name": candidate.elf_name,
                        "file_name": candidate.file_name,
                        "score": candidate.score,
                        "spatial_score": candidate.spatial_score,
                        "histogram_score": candidate.histogram_score,
                        "pixel_score": candidate.pixel_score,
                        "hash_score": candidate.hash_score,
                        "edge_score": candidate.edge_score,
                    }
                    for candidate in result.candidates
                ],
            }
            for result in results
        ]
    }


def save_annotated_image(
    screenshot_path: str | Path,
    results: list[SlotRecognition],
    output_path: str | Path,
) -> None:
    """保存带头像框和 Top1 候选编号/分数的调试图。"""
    image = Image.open(screenshot_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()

    for result in results:
        box = result.box
        top = result.candidates[0] if result.candidates else None
        for offset in range(3):
            draw.rectangle(
                (
                    box.x1 - offset,
                    box.y1 - offset,
                    box.x2 + offset,
                    box.y2 + offset,
                ),
                outline=(255, 0, 0, 255),
            )
        label = f"E{result.slot_index}"
        if top is not None:
            label = f"{label} {top.dex_no} {top.score:.2f}"
        label_box = (box.x1 - 92, box.y1 + 8, box.x1 - 4, box.y1 + 32)
        draw.rectangle(label_box, fill=(255, 0, 0, 220))
        draw.text((label_box[0] + 4, label_box[1] + 3), label, fill=(255, 255, 255, 255), font=font)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)


def save_debug_crops(
    screenshot_path: str | Path,
    results: list[SlotRecognition],
    output_dir: str | Path,
) -> None:
    """保存每个槽位的裁剪图，便于人工确认框选范围。"""
    image = Image.open(screenshot_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        crop = image.crop(result.box.xyxy)
        crop.save(target_dir / f"enemy_slot_{result.slot_index:02d}.png")


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数。"""
    parser = argparse.ArgumentParser(description="识别准备页截图中的敌方阵容头像")
    parser.add_argument("--image", required=True, help="输入截图路径")
    parser.add_argument(
        "--icons-dir",
        default="../data/rocom/recognition/elf_icons_128",
        help="平铺头像模板目录",
    )
    parser.add_argument("--boxes-json", help="自定义头像框 JSON 文件")
    parser.add_argument("--top-k", type=int, default=5, help="每个槽位输出的候选数量")
    parser.add_argument("--output-json", help="识别结果 JSON 输出路径")
    parser.add_argument("--annotated-output", help="带框调试图输出路径")
    parser.add_argument("--debug-crop-dir", help="头像裁剪调试图输出目录")
    return parser


def main() -> None:
    """CLI 入口。"""
    args = build_parser().parse_args()
    boxes = load_boxes_from_json(args.boxes_json) if args.boxes_json else None
    results = recognize_enemy_lineup(
        screenshot_path=args.image,
        icons_dir=args.icons_dir,
        boxes=boxes,
        top_k=args.top_k,
    )
    payload = recognition_to_dict(results)
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.annotated_output:
        save_annotated_image(args.image, results, args.annotated_output)
    if args.debug_crop_dir:
        save_debug_crops(args.image, results, args.debug_crop_dir)


if __name__ == "__main__":
    main()
