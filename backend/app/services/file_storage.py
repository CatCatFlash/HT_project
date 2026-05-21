from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from ..config import MAX_FILE_SIZE, SUPPORTED_EXTENSIONS, UPLOAD_DIR
from ..exceptions import UploadError


def validate_upload(file: UploadFile, file_size: int) -> str:
    raw_name = (file.filename or "").strip()
    suffix = Path(raw_name).suffix.lower()
    if not raw_name:
        raise UploadError("UPLOAD_INVALID_FILENAME", "文件名不能为空，请重新选择文件后再上传", 400, phase="upload.validate")
    if any(char in raw_name for char in {"\x00", "\r", "\n"}):
        raise UploadError("UPLOAD_INVALID_FILENAME", "文件名格式异常，请修改文件名后重新上传", 400, phase="upload.validate")
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UploadError("UPLOAD_UNSUPPORTED_TYPE", "仅支持 PDF、DOC、DOCX 文件上传", 400, phase="upload.validate")
    if file_size <= 0:
        raise UploadError("UPLOAD_EMPTY_FILE", "上传文件不能为空，请重新选择文件后再上传", 400, phase="upload.validate")
    if file_size > MAX_FILE_SIZE:
        raise UploadError("UPLOAD_FILE_TOO_LARGE", "文件大小不能超过 10MB，请压缩后重新上传", 400, phase="upload.validate")
    return suffix


def build_storage_path(original_name: str) -> Path:
    suffix = Path(original_name).suffix.lower()
    return UPLOAD_DIR / f"{uuid4().hex}{suffix}"
