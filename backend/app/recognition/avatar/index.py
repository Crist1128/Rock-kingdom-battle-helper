"""头像模板特征索引。

本模块把模板特征预加载成 NumPy 矩阵，识别时先用向量化粗排筛出少量候选，
再对候选池做较重的像素/前景比较。这样准备阶段 6 格识别和未来局内单头像识别都能复用同一套
高效检索入口。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from app.data_pipeline.rocom.avatar_recognizer import (
    MATCH_TOP_K_REFINEMENT_POOL_SIZE,
    SPATIAL_GRID_SIZE,
    AvatarTemplate,
    MatchCandidate,
    PreparedCropFeatures,
    _circle_mask,
    _histogram_intersection,
    _iter_template_files,
    _masked_color_histogram,
    load_avatar_templates,
)
from app.recognition.avatar.preprocess import prepare_avatar_features

AVATAR_FEATURE_INDEX_CACHE_VERSION = "avatar_feature_index_v4_foreground_focus_uncompressed"
AVATAR_FEATURE_SIZE = 64
CIRCLE_PIXEL_INDICES = np.asarray(
    [
        index
        for index, enabled in enumerate(_circle_mask(AVATAR_FEATURE_SIZE).getdata())
        if enabled
    ],
    dtype=np.int64,
)


def _float_matrix(rows: list[tuple[float, ...]]) -> np.ndarray:
    """把特征列表转换为 float32 矩阵。"""
    return np.asarray(rows, dtype=np.float32)


def _bool_matrix(rows: list[tuple[int, ...]]) -> np.ndarray:
    """把 0/1 特征列表转换为布尔矩阵。"""
    return np.asarray(rows, dtype=np.bool_)


def _histogram_intersection_vector(matrix: np.ndarray, vector: tuple[float, ...]) -> np.ndarray:
    """批量计算直方图交集。"""
    return np.minimum(matrix, np.asarray(vector, dtype=np.float32)).sum(axis=1)


def _hash_similarity_vector(matrix: np.ndarray, vector: tuple[int, ...]) -> np.ndarray:
    """批量计算二值哈希相似度。"""
    return (matrix == np.asarray(vector, dtype=np.bool_)).mean(axis=1)


def _mask_iou_vector(matrix: np.ndarray, vector: tuple[int, ...]) -> np.ndarray:
    """批量计算前景 mask IoU。"""
    vector_array = np.asarray(vector, dtype=np.bool_)
    intersection = np.logical_and(matrix, vector_array).sum(axis=1)
    union = np.logical_or(matrix, vector_array).sum(axis=1)
    return np.divide(
        intersection,
        union,
        out=np.zeros_like(intersection, dtype=np.float32),
        where=union > 0,
    )


def _shape_similarity_vector(matrix: np.ndarray, vector: tuple[float, ...]) -> np.ndarray:
    """批量计算形状统计特征相似度。"""
    distance = np.abs(matrix - np.asarray(vector, dtype=np.float32)).mean(axis=1)
    return np.maximum(0.0, 1.0 - distance * 3.0)


def _image_pixels(image: Image.Image) -> np.ndarray:
    """把 64x64 RGB 图像转换为展平像素矩阵。"""
    return np.asarray(image.convert("RGB"), dtype=np.float32).reshape(-1, 3)


def _pixel_similarity_array(
    left_pixels: np.ndarray,
    right_pixels: np.ndarray,
    indices: np.ndarray,
) -> float:
    """在指定像素索引上向量化计算 RGB RMSE 相似度。"""
    if indices.size == 0:
        return 0.0
    diff = left_pixels[indices] - right_pixels[indices]
    rmse = float(np.sqrt(np.mean(np.mean(diff * diff, axis=1))))
    return max(0.0, 1.0 - rmse / 255.0)


def _cache_path(
    icons_dir: Path,
    *,
    mirror_templates: bool,
    include_confirmed_templates: bool,
) -> Path:
    """返回头像模板预处理磁盘缓存路径。"""
    flags = f"m{int(mirror_templates)}_c{int(include_confirmed_templates)}"
    return icons_dir.parent / f".{icons_dir.name}_{flags}_feature_index_v4.npz"


def _template_signature(
    icons_dir: Path,
    *,
    mirror_templates: bool,
    include_confirmed_templates: bool,
) -> str:
    """生成模板目录签名，用于判断预处理缓存是否仍然有效。"""
    files = []
    for path, should_mirror, is_confirmed in _iter_template_files(
        icons_dir,
        mirror_templates=mirror_templates,
        include_confirmed_templates=include_confirmed_templates,
    ):
        stat = path.stat()
        files.append(
            {
                "path": str(path.relative_to(icons_dir.parent)).replace("\\", "/"),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "mirror": should_mirror,
                "confirmed": is_confirmed,
            }
        )
    return json.dumps(
        {
            "version": AVATAR_FEATURE_INDEX_CACHE_VERSION,
            "mirror_templates": mirror_templates,
            "include_confirmed_templates": include_confirmed_templates,
            "files": files,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _load_index_cache(cache_path: Path, signature: str) -> AvatarFeatureIndex | None:
    """从磁盘缓存加载预处理头像索引；缓存缺失或失效时返回 None。"""
    if not cache_path.is_file():
        return None
    try:
        with np.load(cache_path, allow_pickle=False) as payload:
            cached_signature = str(payload["signature"][0])
            if cached_signature != signature:
                return None
            images = payload["images"]
            foreground_masks = payload["foreground_masks"]
            templates: list[AvatarTemplate] = []
            dex_numbers = payload["dex_no"].astype(str).tolist()
            elf_names = payload["elf_name"].astype(str).tolist()
            file_names = payload["file_name"].astype(str).tolist()
            paths = payload["path"].astype(str).tolist()
            is_confirmed_rows = payload["is_confirmed"].astype(bool).tolist()
            histograms = payload["histograms"]
            spatial_histograms = payload["spatial_histograms"]
            hash_bits = payload["hash_bits"]
            edge_hash_bits = payload["edge_hash_bits"]
            edge_spatial_histograms = payload["edge_spatial_histograms"]
            foreground_histograms = payload["foreground_histograms"]
            shape_features = payload["shape_features"]
            image_pixels = (
                payload["image_pixels"].astype(np.float32)
                if "image_pixels" in payload.files
                else images.astype(np.float32).reshape(images.shape[0], -1, 3)
            )

            for index, file_name in enumerate(file_names):
                mask = tuple(int(value) for value in foreground_masks[index].tolist())
                foreground_indices = tuple(
                    int(value) for value in np.flatnonzero(foreground_masks[index]).tolist()
                )
                templates.append(
                    AvatarTemplate(
                        dex_no=dex_numbers[index],
                        elf_name=elf_names[index],
                        file_name=file_name,
                        path=Path(paths[index]),
                        is_confirmed=bool(is_confirmed_rows[index]),
                        image=Image.fromarray(images[index].astype(np.uint8), mode="RGB"),
                        histogram=tuple(float(value) for value in histograms[index].tolist()),
                        spatial_histogram=tuple(
                            float(value) for value in spatial_histograms[index].tolist()
                        ),
                        hash_bits=tuple(int(value) for value in hash_bits[index].tolist()),
                        edge_hash_bits=tuple(
                            int(value) for value in edge_hash_bits[index].tolist()
                        ),
                        edge_spatial_histogram=tuple(
                            float(value) for value in edge_spatial_histograms[index].tolist()
                        ),
                        foreground_mask=mask,
                        foreground_indices=foreground_indices,
                        foreground_histogram=tuple(
                            float(value) for value in foreground_histograms[index].tolist()
                        ),
                        shape_features=tuple(
                            float(value) for value in shape_features[index].tolist()
                        ),
                    )
                )
            return AvatarFeatureIndex(
                templates=templates,
                histograms=histograms.astype(np.float32),
                spatial_histograms=spatial_histograms.astype(np.float32),
                hash_bits=hash_bits.astype(np.bool_),
                edge_hash_bits=edge_hash_bits.astype(np.bool_),
                edge_spatial_histograms=edge_spatial_histograms.astype(np.float32),
                foreground_masks=foreground_masks.astype(np.bool_),
                foreground_histograms=foreground_histograms.astype(np.float32),
                shape_features=shape_features.astype(np.float32),
                image_pixels=image_pixels,
            )
    except (OSError, ValueError, KeyError):
        return None


def _write_index_cache(cache_path: Path, signature: str, index: AvatarFeatureIndex) -> None:
    """把头像模板预处理索引写入磁盘缓存。"""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # 头像索引体积不大（数百个 64px 模板），未压缩 npz 可明显减少服务冷启动解压耗时。
        np.savez(
            cache_path,
            signature=np.asarray([signature]),
            dex_no=np.asarray([template.dex_no for template in index.templates]),
            elf_name=np.asarray([template.elf_name for template in index.templates]),
            file_name=np.asarray([template.file_name for template in index.templates]),
            path=np.asarray([str(template.path) for template in index.templates]),
            is_confirmed=np.asarray([template.is_confirmed for template in index.templates]),
            images=np.asarray(
                [
                    np.asarray(template.image.convert("RGB"), dtype=np.uint8)
                    for template in index.templates
                ],
                dtype=np.uint8,
            ),
            histograms=index.histograms,
            spatial_histograms=index.spatial_histograms,
            hash_bits=index.hash_bits,
            edge_hash_bits=index.edge_hash_bits,
            edge_spatial_histograms=index.edge_spatial_histograms,
            foreground_masks=index.foreground_masks,
            foreground_histograms=np.asarray(
                [template.foreground_histogram for template in index.templates],
                dtype=np.float32,
            ),
            shape_features=index.shape_features,
            image_pixels=index.image_pixels,
        )
    except OSError:
        # 缓存只是性能优化；写入失败不能影响识别主流程。
        return


@dataclass(frozen=True)
class AvatarFeatureIndex:
    """头像模板向量索引。"""

    templates: list[AvatarTemplate]
    histograms: np.ndarray
    spatial_histograms: np.ndarray
    hash_bits: np.ndarray
    edge_hash_bits: np.ndarray
    edge_spatial_histograms: np.ndarray
    foreground_masks: np.ndarray
    foreground_histograms: np.ndarray
    shape_features: np.ndarray
    image_pixels: np.ndarray

    @classmethod
    def from_templates(cls, templates: list[AvatarTemplate]) -> AvatarFeatureIndex:
        """从模板列表构建向量索引。"""
        return cls(
            templates=templates,
            histograms=_float_matrix([template.histogram for template in templates]),
            spatial_histograms=_float_matrix(
                [template.spatial_histogram for template in templates]
            ),
            hash_bits=_bool_matrix([template.hash_bits for template in templates]),
            edge_hash_bits=_bool_matrix([template.edge_hash_bits for template in templates]),
            edge_spatial_histograms=_float_matrix(
                [template.edge_spatial_histogram for template in templates]
            ),
            foreground_masks=_bool_matrix([template.foreground_mask for template in templates]),
            foreground_histograms=_float_matrix(
                [template.foreground_histogram for template in templates]
            ),
            shape_features=_float_matrix([template.shape_features for template in templates]),
            image_pixels=np.asarray(
                [_image_pixels(template.image) for template in templates],
                dtype=np.float32,
            ),
        )

    @property
    def template_count(self) -> int:
        """索引中的模板数量。"""
        return len(self.templates)

    def recognize_crop(self, crop: Image.Image, *, top_k: int = 5) -> list[MatchCandidate]:
        """识别单张已裁头像。"""
        variant_features = prepare_avatar_features(crop)
        if not variant_features:
            return []
        variant_pixels = [_image_pixels(features.image) for features in variant_features]
        coarse_scores = self._coarse_scores(variant_features)
        refinement_pool_size = min(
            self.template_count,
            max(top_k, MATCH_TOP_K_REFINEMENT_POOL_SIZE),
        )
        if refinement_pool_size <= 0:
            return []
        # argpartition 避免对全量模板完整排序；候选池内部再按分数排序，保证稳定。
        pool_indices = np.argpartition(-coarse_scores, refinement_pool_size - 1)[
            :refinement_pool_size
        ]
        pool_indices = sorted(
            pool_indices.tolist(),
            key=lambda index: coarse_scores[index],
            reverse=True,
        )
        candidates = [
            candidate
            for candidate in (
                self._refine_template(index, variant_features, variant_pixels)
                for index in pool_indices
            )
            if candidate is not None
        ]
        return _deduplicate_candidates(candidates, top_k=top_k)

    def _coarse_scores(self, variant_features: list[PreparedCropFeatures]) -> np.ndarray:
        """对所有模板进行向量化粗排。"""
        best_scores = np.full(self.template_count, -1.0, dtype=np.float32)
        for features in variant_features:
            spatial_score = (
                _histogram_intersection_vector(
                    self.spatial_histograms,
                    features.spatial_histogram,
                )
                / (SPATIAL_GRID_SIZE**2)
            )
            histogram_score = _histogram_intersection_vector(
                self.histograms,
                features.histogram,
            )
            hash_score = _hash_similarity_vector(self.hash_bits, features.hash_bits)
            edge_score = _hash_similarity_vector(self.edge_hash_bits, features.edge_hash_bits)
            edge_spatial_score = _histogram_intersection_vector(
                self.edge_spatial_histograms,
                features.edge_spatial_histogram,
            )
            silhouette_score = _mask_iou_vector(self.foreground_masks, features.foreground_mask)
            shape_score = _shape_similarity_vector(self.shape_features, features.shape_features)
            # 新识别模板来自透明背景高清头像，背景噪声显著少于旧图鉴裁片；
            # 粗排阶段应更信任前景轮廓/形状和边缘分布，降低整圆颜色直方图的权重，
            # 避免准备页黑底、橙色描边或血条暗纹把候选拉偏。
            scores = (
                spatial_score * 0.22
                + histogram_score * 0.08
                + hash_score * 0.05
                + edge_score * 0.12
                + edge_spatial_score * 0.20
                + silhouette_score * 0.20
                + shape_score * 0.13
            )
            best_scores = np.maximum(best_scores, scores)
        return best_scores

    def _refine_template(
        self,
        template_index: int,
        variant_features: list[PreparedCropFeatures],
        variant_pixels: list[np.ndarray],
    ) -> MatchCandidate | None:
        """对粗排候选做精排。"""
        template = self.templates[template_index]
        template_pixels = self.image_pixels[template_index]
        foreground_indices = np.flatnonzero(self.foreground_masks[template_index])
        best_score = -1.0
        best_parts: tuple[float, float, float, float, float] | None = None
        for features, feature_pixels in zip(variant_features, variant_pixels, strict=True):
            spatial_score = float(
                _histogram_intersection_vector(
                    self.spatial_histograms[template_index : template_index + 1],
                    features.spatial_histogram,
                )[0]
                / (SPATIAL_GRID_SIZE**2)
            )
            histogram_score = _histogram_intersection(features.histogram, template.histogram)
            pixel_score = _pixel_similarity_array(
                feature_pixels,
                template_pixels,
                CIRCLE_PIXEL_INDICES,
            )
            hash_score = float(
                _hash_similarity_vector(
                    self.hash_bits[template_index : template_index + 1],
                    features.hash_bits,
                )[0]
            )
            edge_score = float(
                _hash_similarity_vector(
                    self.edge_hash_bits[template_index : template_index + 1],
                    features.edge_hash_bits,
                )[0]
            )
            edge_spatial_score = _histogram_intersection(
                features.edge_spatial_histogram,
                template.edge_spatial_histogram,
            )
            silhouette_score = float(
                _mask_iou_vector(
                    self.foreground_masks[template_index : template_index + 1],
                    features.foreground_mask,
                )[0]
            )
            shape_score = float(
                _shape_similarity_vector(
                    self.shape_features[template_index : template_index + 1],
                    features.shape_features,
                )[0]
            )
            foreground_pixel_score = _pixel_similarity_array(
                feature_pixels,
                template_pixels,
                foreground_indices,
            )
            foreground_hist_score = _histogram_intersection(
                _masked_color_histogram(features.image, template.foreground_indices),
                template.foreground_histogram,
            )
            # 精排阶段继续降低全图像素/颜色影响，增加模板透明前景区域和形状权重。
            # 这样新高清透明头像能作为“主体模板”发挥作用，而不是被截图背景颜色主导。
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
            return None
        spatial_score, histogram_score, pixel_score, hash_score, edge_score = best_parts
        return MatchCandidate(
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


def _deduplicate_candidates(
    candidates: list[MatchCandidate],
    *,
    top_k: int,
) -> list[MatchCandidate]:
    """按精灵编号和名称去重并截取 Top-K。"""
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


@lru_cache(maxsize=4)
def load_avatar_feature_index(
    icons_dir: str | Path,
    *,
    mirror_templates: bool = True,
    include_confirmed_templates: bool = False,
) -> AvatarFeatureIndex:
    """加载模板并构建可复用的头像特征索引。"""
    icons_path = Path(icons_dir)
    signature = _template_signature(
        icons_path,
        mirror_templates=mirror_templates,
        include_confirmed_templates=include_confirmed_templates,
    )
    cache_path = _cache_path(
        icons_path,
        mirror_templates=mirror_templates,
        include_confirmed_templates=include_confirmed_templates,
    )
    cached_index = _load_index_cache(cache_path, signature)
    if cached_index is not None:
        return cached_index

    templates = load_avatar_templates(
        icons_path,
        mirror_templates=mirror_templates,
        include_confirmed_templates=include_confirmed_templates,
    )
    index = AvatarFeatureIndex.from_templates(templates)
    _write_index_cache(cache_path, signature, index)
    return index
