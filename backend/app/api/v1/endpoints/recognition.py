"""截图识别 API。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.data_pipeline.rocom.avatar_recognizer import (
    SlotRecognition,
    locate_enemy_avatar_boxes,
)
from app.db.session import get_db
from app.models.static import ElfDefinition
from app.recognition.avatar.service import AvatarRecognitionService
from app.schemas.recognition import (
    EnemyAvatarCandidateOut,
    EnemyAvatarMatchedElfOut,
    EnemyAvatarSlotRecognitionOut,
    EnemyLineupRecognitionOut,
    RecognitionBoxOut,
)

router = APIRouter()

MAX_SCREENSHOT_BYTES = 12 * 1024 * 1024
DEFAULT_ICONS_RELATIVE_DIR = Path("recognition") / "elf_icons_128"


def _icons_dir() -> Path:
    """返回本地头像模板目录。"""
    return Path(settings.rocom_data_dir) / DEFAULT_ICONS_RELATIVE_DIR


def _icon_url(file_name: str) -> str:
    """把模板文件名转换成前端可访问的本地资源 URL。"""
    encoded = quote(file_name)
    return f"/api/v1/assets/rocom/recognition/elf_icons_128/{encoded}"


def _confidence_level(score: float) -> str:
    """把连续相似度转换成仅用于展示的粗略置信等级。"""
    if score >= 0.9:
        return "high"
    if score >= 0.78:
        return "medium"
    return "low"


def _load_uploaded_image(file_bytes: bytes) -> Image.Image:
    """校验上传内容并解析为 Pillow 图片。"""
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded screenshot is empty")
    if len(file_bytes) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=413, detail="Screenshot file is too large")
    try:
        image = Image.open(BytesIO(file_bytes))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image") from exc
    return ImageOps.exif_transpose(image).convert("RGBA")


def _find_matched_elves(
    db: Session,
    *,
    dex_no: str,
    template_elf_name: str,
) -> list[EnemyAvatarMatchedElfOut]:
    """按图鉴编号优先、名称兜底，把头像模板候选映射到数据库精灵。"""
    dex_no_4 = dex_no.zfill(4)
    stmt = (
        select(ElfDefinition)
        .where(
            ElfDefinition.deleted_at.is_(None),
            or_(
                ElfDefinition.elf_id.like(f"rocom_elf_{dex_no_4}_%"),
                ElfDefinition.elf_name == template_elf_name,
            ),
        )
        .order_by(ElfDefinition.elf_name, ElfDefinition.elf_id)
    )
    elves = list(db.scalars(stmt).all())
    return [
        EnemyAvatarMatchedElfOut(
            elf_id=elf.elf_id,
            elf_name=elf.elf_name,
            avatar=elf.avatar,
            element_types_json=elf.element_types_json,
            data_version=elf.data_version,
        )
        for elf in elves
    ]


def _recognize_slots(
    image: Image.Image,
    icons_dir: Path,
    top_k: int,
) -> tuple[list[SlotRecognition], int]:
    """定位 6 个敌方头像槽位，并复用统一头像裁图识别服务做匹配。"""
    try:
        avatar_service = AvatarRecognitionService(icons_dir)
        template_count = avatar_service.template_count
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Avatar template directory not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="No avatar templates available") from exc

    results: list[SlotRecognition] = []
    localization = locate_enemy_avatar_boxes(image)
    crops = [image.crop(box.xyxy) for box in localization.avatar_boxes]
    crop_recognitions = avatar_service.recognize_crops(crops, top_k=top_k)
    for index, (box, crop_recognition) in enumerate(
        zip(localization.avatar_boxes, crop_recognitions, strict=True),
        start=1,
    ):
        results.append(
            SlotRecognition(
                slot_index=index,
                box=box,
                candidates=crop_recognition.candidates,
                location_method=localization.method,
                location_confidence=localization.confidence,
            )
        )
    return results, template_count


@router.post("/enemy-lineup", response_model=EnemyLineupRecognitionOut)
async def recognize_enemy_lineup_from_screenshot(
    file: UploadFile = File(..., description="战斗准备页截图"),
    top_k: int = Query(default=5, ge=1, le=10, description="每个槽位返回的候选数量"),
    db: Session = Depends(get_db),
) -> EnemyLineupRecognitionOut:
    """识别战斗准备页右侧敌方阵容头像，返回候选供用户确认。"""
    file_bytes = await file.read(MAX_SCREENSHOT_BYTES + 1)
    image = _load_uploaded_image(file_bytes)
    slot_results, template_count = _recognize_slots(image, _icons_dir(), top_k)

    warnings: list[str] = [
        "截图识别结果仅作为候选推荐，不会自动写入阵容；请在前端逐个确认。"
    ]
    slots: list[EnemyAvatarSlotRecognitionOut] = []
    for slot in slot_results:
        candidates: list[EnemyAvatarCandidateOut] = []
        for candidate in slot.candidates:
            matched_elves = _find_matched_elves(
                db,
                dex_no=candidate.dex_no,
                template_elf_name=candidate.elf_name,
            )
            if not matched_elves:
                warnings.append(
                    f"槽位 {slot.slot_index} 候选 {candidate.dex_no}_{candidate.elf_name} "
                    "未能映射到数据库精灵。"
                )
            candidates.append(
                EnemyAvatarCandidateOut(
                    dex_no=candidate.dex_no,
                    elf_name=candidate.elf_name,
                    file_name=candidate.file_name,
                    icon_url=_icon_url(candidate.file_name),
                    score=candidate.score,
                    spatial_score=candidate.spatial_score,
                    histogram_score=candidate.histogram_score,
                    pixel_score=candidate.pixel_score,
                    hash_score=candidate.hash_score,
                    edge_score=candidate.edge_score,
                    confidence_level=_confidence_level(candidate.score),
                    matched_elves=matched_elves,
                )
            )
        slots.append(
            EnemyAvatarSlotRecognitionOut(
                slot_index=slot.slot_index,
                box=RecognitionBoxOut(
                    x1=slot.box.x1,
                    y1=slot.box.y1,
                    x2=slot.box.x2,
                    y2=slot.box.y2,
                ),
                location_method=slot.location_method,
                location_confidence=slot.location_confidence,
                candidates=candidates,
            )
        )
    location_methods = {slot.location_method for slot in slot_results}
    if "black_slot" not in location_methods:
        warnings.append(
            "本次未使用黑色槽位主定位，已启用备用/兜底定位；请重点检查头像框是否裁准。"
        )

    return EnemyLineupRecognitionOut(
        source_image_size=image.size,
        icon_template_count=template_count,
        slots=slots,
        warnings=list(dict.fromkeys(warnings)),
    )
