from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from ..config import MAX_FILE_SIZE, SUPPORTED_EXTENSIONS, UPLOAD_DIR
from ..exceptions import UploadError


def validate_upload(file: UploadFile, file_size: int) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if not file.filename:
        raise UploadError("UPLOAD_EMPTY_NAME", "文件名不能为空", 400)
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UploadError("UPLOAD_UNSUPPORTED_TYPE", "仅支持 PDF、DOC、DOCX 文件上传", 400)
    if file_size <= 0:
        raise UploadError("UPLOAD_EMPTY_FILE", "上传文件不能为空", 400)
    if file_size > MAX_FILE_SIZE:
        raise UploadError("UPLOAD_FILE_TOO_LARGE", "文件大小不能超过 10MB", 400)
    return suffix


def build_storage_path(original_name: str) -> Path:
    suffix = Path(original_name).suffix.lower()
    return UPLOAD_DIR / f"{uuid4().hex}{suffix}"
