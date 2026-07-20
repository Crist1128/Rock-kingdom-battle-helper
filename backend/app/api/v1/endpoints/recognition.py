"""截图识别 API。"""

from __future__ import annotations

import math
import re
import shutil
import time
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.static import ElfDefinition
from app.recognition.avatar.full_library import (
    AlphaTemplateRecognizer,
    AvatarMatchCandidate,
    RecognitionRunResult,
    get_avatar_recognizer,
    save_debug_artifacts,
)
from app.schemas.recognition import (
    EnemyAvatarCandidateOut,
    EnemyAvatarMatchedElfOut,
    EnemyAvatarSlotDebugOut,
    EnemyAvatarSlotRecognitionOut,
    EnemyLineupRecognitionDebugOut,
    EnemyLineupRecognitionOut,
    RecognitionBoxOut,
)

router = APIRouter()

MAX_SCREENSHOT_BYTES = 12 * 1024 * 1024
DEFAULT_ICONS_RELATIVE_DIR = Path("recognition") / "elf_icons_128"
DEBUG_RUNS_RELATIVE_DIR = Path("recognition") / "debug_runs"
DEBUG_ARTIFACT_TTL_SECONDS = 24 * 60 * 60
DEBUG_ARTIFACT_MAX_RUNS = 50
ASSET_HINT_PATTERN = re.compile(r"^(?P<dex_no>\d{3,4})(?:[_\-\s]+(?P<name>.+))?$")


def _icons_dir() -> Path:
    """返回本地透明头像模板目录。"""
    return Path(settings.rocom_data_dir) / DEFAULT_ICONS_RELATIVE_DIR


def _icon_url(file_name: str) -> str:
    """把模板文件名转换成前端可访问的本地资源 URL。"""
    encoded = quote(file_name)
    return f"/api/v1/assets/rocom/recognition/elf_icons_128/{encoded}"


def _rocom_asset_url(relative_path: Path) -> str:
    """把 data/rocom 下的相对图片路径转成前端可访问 URL。"""
    encoded_parts = [quote(part) for part in relative_path.parts]
    return f"/api/v1/assets/rocom/{'/'.join(encoded_parts)}"


def _confidence_level(score: float) -> str:
    """把连续相似度转成粗略置信等级。"""
    if score >= 0.9:
        return "high"
    if score >= 0.78:
        return "medium"
    return "low"


def _load_uploaded_image(file_bytes: bytes) -> Image.Image:
    """校验上传内容并解析为 Pillow 图像。"""
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


def _image_to_bgr(image: Image.Image) -> np.ndarray:
    """把 Pillow 图像转成 OpenCV BGR。"""
    rgb = image.convert("RGB")
    return cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)


def _load_recognizer(icons_dir: Path) -> AlphaTemplateRecognizer:
    """加载透明模板库识别器。"""
    try:
        return get_avatar_recognizer(icons_dir, mirror_mode="enemy")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Avatar template directory not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="No avatar templates available") from exc


def _recognize_screenshot(image: Image.Image, icons_dir: Path) -> RecognitionRunResult:
    """对整张截图执行透明模板库识别。"""
    recognizer = _load_recognizer(icons_dir)
    return recognizer.recognize_screenshot(_image_to_bgr(image))


def _debug_root() -> Path:
    """返回头像识别调试产物根目录。"""
    return Path(settings.rocom_data_dir) / DEBUG_RUNS_RELATIVE_DIR


def _cleanup_debug_artifacts(now: float | None = None) -> None:
    """按 TTL 和最大数量清理旧的头像识别调试产物目录。"""
    root = _debug_root()
    if not root.is_dir():
        return
    current = now if now is not None else time.time()
    run_dirs = [path for path in root.iterdir() if path.is_dir()]
    for path in run_dirs:
        try:
            age_seconds = current - path.stat().st_mtime
        except OSError:
            continue
        if age_seconds > DEBUG_ARTIFACT_TTL_SECONDS:
            shutil.rmtree(path, ignore_errors=True)

    remaining = [path for path in root.iterdir() if path.is_dir()]
    remaining.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    for path in remaining[DEBUG_ARTIFACT_MAX_RUNS:]:
        shutil.rmtree(path, ignore_errors=True)


def _save_recognition_debug_artifacts(
    screenshot_bgr: np.ndarray,
    result: RecognitionRunResult,
    recognizer: AlphaTemplateRecognizer,
) -> EnemyLineupRecognitionDebugOut:
    """保存并返回本次识别的调试图片 URL。"""
    _cleanup_debug_artifacts()
    run_id = uuid.uuid4().hex
    relative_dir = DEBUG_RUNS_RELATIVE_DIR / run_id
    output_dir = Path(settings.rocom_data_dir) / relative_dir
    save_debug_artifacts(screenshot_bgr, result, recognizer, output_dir)
    return EnemyLineupRecognitionDebugOut(
        run_id=run_id,
        expires_after_seconds=DEBUG_ARTIFACT_TTL_SECONDS,
        annotated_image_url=_rocom_asset_url(relative_dir / "annotated_recognition.png"),
        contact_sheet_url=_rocom_asset_url(relative_dir / "recognition_contact_sheet.png"),
        slots=[
            EnemyAvatarSlotDebugOut(
                slot_index=slot.slot,
                crop_url=_rocom_asset_url(relative_dir / "slot_crops" / f"slot_{slot.slot}.png"),
                detail_url=_rocom_asset_url(
                    relative_dir / "comparison" / f"slot_{slot.slot}_detail.png"
                ),
                top5_url=_rocom_asset_url(
                    relative_dir / "comparison" / f"slot_{slot.slot}_top5.png"
                ),
            )
            for slot in result.slots
            if slot.top1 is not None
        ],
    )


def _split_asset_hint(text: str) -> tuple[str | None, str]:
    """从模板文件名里提取图鉴编号和名称提示。"""
    stem = Path(text).stem.strip()
    if not stem:
        return None, text
    match = ASSET_HINT_PATTERN.match(stem)
    if match is None:
        return None, stem
    dex_no = match.group("dex_no")
    name = (match.group("name") or stem).strip() or stem
    return dex_no, name


def _find_matched_elves(
    db: Session,
    *,
    label: str,
    file_name: str,
) -> list[EnemyAvatarMatchedElfOut]:
    """按模板标签和图鉴编号把视觉结果映射到数据库精灵。"""
    search_terms: set[str] = set()
    dex_nos: set[str] = set()
    for text in {label, Path(file_name).stem}:
        if not text:
            continue
        dex_no, name = _split_asset_hint(text)
        if dex_no:
            dex_nos.add(dex_no.zfill(4))
        if name:
            search_terms.add(name)
        search_terms.add(text)

    filters = [ElfDefinition.elf_name == term for term in sorted(search_terms) if term]
    filters.extend(ElfDefinition.elf_id.like(f"rocom_elf_{dex_no}_%") for dex_no in sorted(dex_nos))
    if not filters:
        return []

    stmt = (
        select(ElfDefinition)
        .where(ElfDefinition.deleted_at.is_(None), or_(*filters))
        .order_by(ElfDefinition.elf_name, ElfDefinition.elf_id)
    )
    elves = list(db.scalars(stmt).all())
    seen_ids: set[str] = set()
    matched: list[EnemyAvatarMatchedElfOut] = []
    for elf in elves:
        if elf.elf_id in seen_ids:
            continue
        seen_ids.add(elf.elf_id)
        matched.append(
            EnemyAvatarMatchedElfOut(
                elf_id=elf.elf_id,
                elf_name=elf.elf_name,
                avatar=elf.avatar,
                element_types_json=elf.element_types_json,
                data_version=elf.data_version,
            )
        )
    return matched


def _candidate_to_out(
    db: Session,
    candidate: AvatarMatchCandidate,
) -> EnemyAvatarCandidateOut:
    """把原型输出映射成前端已在使用的候选结构。"""
    color_similarity = (
        math.exp(-candidate.color_delta_e / 40.0)
        if math.isfinite(candidate.color_delta_e)
        else 0.0
    )
    dex_no, elf_name = _split_asset_hint(candidate.label)
    matched_elves = _find_matched_elves(
        db,
        label=candidate.label,
        file_name=candidate.file_name,
    )
    return EnemyAvatarCandidateOut(
        dex_no=dex_no or f"{candidate.visual_id:03d}",
        elf_name=elf_name,
        file_name=candidate.file_name,
        icon_url=_icon_url(candidate.file_name),
        score=round(candidate.final_score, 6),
        spatial_score=round(candidate.coarse_score, 6),
        histogram_score=round(color_similarity, 6),
        pixel_score=round(candidate.final_score, 6),
        hash_score=0.0,
        edge_score=0.0,
        confidence_level=candidate.confidence_level or _confidence_level(candidate.final_score),
        matched_elves=matched_elves,
    )


@router.post("/enemy-lineup", response_model=EnemyLineupRecognitionOut)
async def recognize_enemy_lineup_from_screenshot(
    file: UploadFile = File(..., description="战斗准备页截图"),
    top_k: int = Query(default=5, ge=1, le=10, description="每个槽位返回的候选数量"),
    include_debug: bool = Query(default=True, description="是否保存并返回调试图片 URL"),
    db: Session = Depends(get_db),
) -> EnemyLineupRecognitionOut:
    """识别战斗准备页右侧敌方阵容头像。"""
    file_bytes = await file.read(MAX_SCREENSHOT_BYTES + 1)
    image = _load_uploaded_image(file_bytes)
    screenshot_bgr = _image_to_bgr(image)
    recognizer = _load_recognizer(_icons_dir())
    raw_result = recognizer.recognize_screenshot(screenshot_bgr)
    debug_artifacts = (
        _save_recognition_debug_artifacts(screenshot_bgr, raw_result, recognizer)
        if include_debug
        else None
    )

    warnings: list[str] = [
        "截图识别结果仅供候选确认，不会自动写入阵容；请逐槽确认。",
        *raw_result.warnings,
    ]
    slots: list[EnemyAvatarSlotRecognitionOut] = []
    for slot in raw_result.slots:
        candidates = [_candidate_to_out(db, candidate) for candidate in slot.top5[:top_k]]
        slots.append(
            EnemyAvatarSlotRecognitionOut(
                slot_index=slot.slot,
                box=RecognitionBoxOut(
                    x1=slot.box.x1,
                    y1=slot.box.y1,
                    x2=slot.box.x2,
                    y2=slot.box.y2,
                ),
                location_method="fixed_reference",
                location_confidence=1.0,
                candidates=candidates,
            )
        )

    return EnemyLineupRecognitionOut(
        source_image_size=raw_result.source_image_size,
        icon_template_count=raw_result.asset_count,
        slots=slots,
        warnings=list(dict.fromkeys(warnings)),
        debug_artifacts=debug_artifacts,
    )
