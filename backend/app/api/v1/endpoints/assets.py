"""本地静态规则图片访问接口。

该接口只暴露 `data/rocom` 下的图片文件，用于把 rocom 爬虫下载到本地的精灵头像、
技能图标等资源转换成前端可直接访问的 URL。
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter()

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


def _resolve_rocom_asset(relative_path: str) -> Path:
    """校验并解析 rocom 本地图片路径，避免目录穿越和非图片文件访问。"""
    if not relative_path or "\\" in relative_path:
        raise HTTPException(status_code=400, detail="Invalid asset path")

    requested = Path(relative_path)
    if requested.is_absolute() or any(part in {"", ".", ".."} for part in requested.parts):
        raise HTTPException(status_code=400, detail="Invalid asset path")

    suffix = requested.suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported asset type")

    root = Path(settings.rocom_data_dir).resolve()
    candidate = (root / requested).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Asset path escapes rocom data dir") from exc

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return candidate


@router.get("/rocom/{relative_path:path}", response_class=FileResponse)
def get_rocom_asset(relative_path: str) -> FileResponse:
    """读取 `data/rocom` 下的本地 rocom 图片资源。"""
    return FileResponse(_resolve_rocom_asset(relative_path))
