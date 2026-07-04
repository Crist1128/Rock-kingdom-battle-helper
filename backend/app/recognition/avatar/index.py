"""头像模板特征索引。

本模块把模板特征预加载成 NumPy 矩阵，识别时先用向量化粗排筛出少量候选，
再对候选池做较重的像素/前景比较。这样准备阶段 6 格识别和未来局内单头像识别都能复用同一套
高效检索入口。
"""

from __future__ import annotations

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
    _histogram_intersection,
    _masked_color_histogram,
    _masked_pixel_similarity,
    _pixel_similarity,
    load_avatar_templates,
)
from app.recognition.avatar.preprocess import prepare_avatar_features


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
    shape_features: np.ndarray

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
            shape_features=_float_matrix([template.shape_features for template in templates]),
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
                self._refine_template(index, variant_features) for index in pool_indices
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
            scores = (
                spatial_score * 0.32
                + histogram_score * 0.13
                + hash_score * 0.07
                + edge_score * 0.10
                + edge_spatial_score * 0.21
                + silhouette_score * 0.12
                + shape_score * 0.05
            )
            best_scores = np.maximum(best_scores, scores)
        return best_scores

    def _refine_template(
        self,
        template_index: int,
        variant_features: list[PreparedCropFeatures],
    ) -> MatchCandidate | None:
        """对粗排候选做精排。"""
        template = self.templates[template_index]
        best_score = -1.0
        best_parts: tuple[float, float, float, float, float] | None = None
        for features in variant_features:
            spatial_score = float(
                _histogram_intersection_vector(
                    self.spatial_histograms[template_index : template_index + 1],
                    features.spatial_histogram,
                )[0]
                / (SPATIAL_GRID_SIZE**2)
            )
            histogram_score = _histogram_intersection(features.histogram, template.histogram)
            pixel_score = _pixel_similarity(features.image, template.image)
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
            foreground_pixel_score = _masked_pixel_similarity(
                features.image,
                template.image,
                template.foreground_indices,
            )
            foreground_hist_score = _histogram_intersection(
                _masked_color_histogram(features.image, template.foreground_indices),
                template.foreground_histogram,
            )
            score = (
                spatial_score * 0.22
                + histogram_score * 0.07
                + pixel_score * 0.09
                + hash_score * 0.05
                + edge_score * 0.09
                + edge_spatial_score * 0.23
                + silhouette_score * 0.12
                + shape_score * 0.06
                + foreground_pixel_score * 0.05
                + foreground_hist_score * 0.02
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
    templates = load_avatar_templates(
        Path(icons_dir),
        mirror_templates=mirror_templates,
        include_confirmed_templates=include_confirmed_templates,
    )
    return AvatarFeatureIndex.from_templates(templates)
