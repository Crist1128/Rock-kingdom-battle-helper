"""统一的头像裁图识别服务。

本模块只处理“已经裁好的头像图”，不关心头像来自准备阶段六格、局内当前对位，
还是用户手动框选。准备阶段阵容识别、后续局内切换识别都应先由各自 locator 产出头像框，
再复用这里的 `AvatarRecognitionService.recognize_crop()`。

当前底层使用 `AvatarFeatureIndex` 做模板特征索引；后续可继续替换为 HOG、深度 embedding
或其它检索实现，而不影响 API/前端调用方式。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.data_pipeline.rocom.avatar_recognizer import MatchCandidate
from app.recognition.avatar.index import AvatarFeatureIndex, load_avatar_feature_index

AVATAR_RECOGNITION_ENGINE = "avatar_feature_index_v1"


@dataclass(frozen=True)
class AvatarCropRecognition:
    """单张已裁头像的识别结果。"""

    candidates: list[MatchCandidate]
    engine: str
    template_count: int


class AvatarRecognitionService:
    """统一头像识别服务。

    参数里的 `include_confirmed_templates` 默认关闭，避免少量截图样本污染全局识别。
    后续若要使用人工确认样本，应先建立均衡评估集，再显式开启或改为训练/构建索引流程。
    """

    def __init__(
        self,
        icons_dir: str | Path,
        *,
        mirror_templates: bool = True,
        include_confirmed_templates: bool = False,
        engine: str = AVATAR_RECOGNITION_ENGINE,
    ) -> None:
        self.icons_dir = Path(icons_dir)
        self.mirror_templates = mirror_templates
        self.include_confirmed_templates = include_confirmed_templates
        self.engine = engine
        self._index: AvatarFeatureIndex | None = None

    @property
    def index(self) -> AvatarFeatureIndex:
        """懒加载并复用头像模板特征索引。"""
        if self._index is None:
            self._index = load_avatar_feature_index(
                self.icons_dir,
                mirror_templates=self.mirror_templates,
                include_confirmed_templates=self.include_confirmed_templates,
            )
        return self._index

    @property
    def template_count(self) -> int:
        """当前模板数量。"""
        return self.index.template_count

    def recognize_crop(self, crop: Image.Image, *, top_k: int = 2) -> AvatarCropRecognition:
        """识别单张已裁头像，返回 Top-K 候选。"""
        candidates = self.index.recognize_crop(crop, top_k=top_k)
        return AvatarCropRecognition(
            candidates=candidates,
            engine=self.engine,
            template_count=self.template_count,
        )

    def recognize_crops(
        self,
        crops: list[Image.Image],
        *,
        top_k: int = 2,
    ) -> list[AvatarCropRecognition]:
        """批量识别多张已裁头像，共用同一份模板特征。"""
        return [self.recognize_crop(crop, top_k=top_k) for crop in crops]
