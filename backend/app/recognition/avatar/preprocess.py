"""头像裁图预处理。

这里的输入是任意来源的头像裁图：准备阶段 6 格、局内当前敌方头像、或用户手动框选区域。
输出是统一尺寸和特征结构，供索引检索层复用。
"""

from __future__ import annotations

from PIL import Image

from app.data_pipeline.rocom.avatar_recognizer import PreparedCropFeatures, _prepare_crop_variants
from app.recognition.avatar.features import extract_crop_features


def prepare_avatar_variants(crop: Image.Image) -> list[Image.Image]:
    """生成标准化头像裁图变体，用于容忍轻微框选偏差。"""
    return _prepare_crop_variants(crop)


def prepare_avatar_features(crop: Image.Image) -> list[PreparedCropFeatures]:
    """生成头像裁图变体并提取识别特征。"""
    return [extract_crop_features(prepared) for prepared in prepare_avatar_variants(crop)]
