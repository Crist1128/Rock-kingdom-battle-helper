"""头像识别特征提取适配层。

当前阶段为了降低重构风险，先复用旧 `avatar_recognizer` 中已经验证过的手写特征函数；
后续可以在本模块内替换为 HOG、深度 embedding 或其它更稳定的特征，而不影响 service/API。
"""

from __future__ import annotations

from PIL import Image

from app.data_pipeline.rocom.avatar_recognizer import (
    PreparedCropFeatures,
    _average_hash,
    _color_histogram,
    _edge_hash,
    _edge_spatial_histogram,
    _foreground_mask_from_crop,
    _mask_shape_features,
    _spatial_color_histogram,
)


def extract_crop_features(prepared_avatar: Image.Image) -> PreparedCropFeatures:
    """为单个标准化头像裁图提取匹配特征。"""
    foreground_mask = _foreground_mask_from_crop(prepared_avatar)
    foreground_indices = tuple(index for index, enabled in enumerate(foreground_mask) if enabled)
    return PreparedCropFeatures(
        image=prepared_avatar,
        histogram=_color_histogram(prepared_avatar),
        spatial_histogram=_spatial_color_histogram(prepared_avatar),
        hash_bits=_average_hash(prepared_avatar),
        edge_hash_bits=_edge_hash(prepared_avatar),
        edge_spatial_histogram=_edge_spatial_histogram(prepared_avatar),
        foreground_mask=foreground_mask,
        foreground_indices=foreground_indices,
        shape_features=_mask_shape_features(foreground_mask),
    )
