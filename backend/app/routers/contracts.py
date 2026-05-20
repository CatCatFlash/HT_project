from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from .. import database
from ..deps import get_user_id
from ..exceptions import AuditError, NotFoundError, ParseError
from ..models import (
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_TEXT,
    TASK_STATUS_ANALYZING,
    TASK_STATUS_FAILED,
    TASK_STATUS_PARSED,
    TASK_STATUS_SUCCESS,
    TASK_STATUS_UPLOADED,
)
from ..schemas import (
    AuditResultResponse,
    DeleteResponse,
    HistoryItem,
    PreviewResponse,
    StartAuditResponse,
    TextSubmitRequest,
    TextSubmitResponse,
    UploadResponse,
)
from ..services.audit_service import AuditService
from ..services.file_storage import build_storage_path, validate_upload
from ..services.text_parser import normalize_text, parse_contract_bytes

router = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])
audit_service = AuditService()


def _status_text(status: str) -> str:
    mapping = {
        "uploaded": "已上传",
        "parsed": "已解析",
        "analyzing": "审核中",
        "success": "审核完成",
        "failed": "审核失败",
    }
    return mapping.get(status, status)


def _history_title(file_name: str | None, source_type: str) -> str:
    if file_name:
        return file_name
    if source_type == SOURCE_TYPE_TEXT:
        return "粘贴合同内容"
    return "未命名合同"


@router.post("/upload")
async def upload_contract(
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
) -> dict:
    content = await file.read()
    validate_upload(file, len(content))
    task_id = uuid4().hex
    parsed_text = ""
    page_count = None

    storage_path = build_storage_path(file.filename or "contract")
    storage_path.write_bytes(content)

    database.create_task(
        task_id=task_id,
        user_id=user_id,
        source_type=SOURCE_TYPE_FILE,
        file_name=file.filename,
        file_url=str(storage_path),
        raw_text=None,
        parsed_text=None,
        status=TASK_STATUS_UPLOADED,
    )

    try:
        parsed_text, page_count = parse_contract_bytes(file.filename or "", content)
        database.update_task(
            task_id,
            parsed_text=parsed_text,
            status=TASK_STATUS_PARSED,
            error_code=None,
            error_message=None,
        )
    except ParseError as exc:
        database.update_task(
            task_id,
            status=TASK_STATUS_FAILED,
            error_code=exc.code,
            error_message=exc.message,
        )
        raise

    preview_text = parsed_text[:2000]
    payload = UploadResponse(
        task_id=task_id,
        file_id=task_id,
        file_name=file.filename or "",
        upload_status=TASK_STATUS_UPLOADED,
        parse_status=TASK_STATUS_PARSED,
        preview_text=preview_text,
        char_count=len(parsed_text),
    ).model_dump()
    if page_count is not None:
        payload["page_count"] = page_count
    return {"success": True, "data": payload}


@router.post("/text")
async def submit_contract_text(
    request: TextSubmitRequest,
    user_id: str = Depends(get_user_id),
) -> dict:
    parsed_text = normalize_text(request.text)
    if not parsed_text:
        raise ParseError("PARSE_EMPTY_CONTENT", "文本内容不能为空", 400)

    task_id = uuid4().hex
    database.create_task(
        task_id=task_id,
        user_id=user_id,
        source_type=SOURCE_TYPE_TEXT,
        file_name=None,
        file_url=None,
        raw_text=request.text,
        parsed_text=parsed_text,
        status=TASK_STATUS_PARSED,
    )
    return {
        "success": True,
        "data": TextSubmitResponse(
            task_id=task_id,
            status=TASK_STATUS_PARSED,
            preview_text=parsed_text[:2000],
            char_count=len(parsed_text),
        ).model_dump(),
    }


@router.get("/{task_id}/preview")
async def get_preview(task_id: str, user_id: str = Depends(get_user_id)) -> dict:
    task = database.fetch_task(task_id, user_id)
    if not task:
        raise NotFoundError("审核任务不存在")
    if task.status == TASK_STATUS_FAILED and not task.parsed_text:
        raise ParseError(task.error_code or "PARSE_FAILED", task.error_message or "解析失败", 400)
    parsed_text = task.parsed_text or ""
    return {
        "success": True,
        "data": PreviewResponse(
            task_id=task.id,
            source_type=task.source_type,
            file_name=task.file_name,
            parsed_text=parsed_text,
            preview_text=parsed_text[:2000],
            char_count=len(parsed_text),
            status=task.status,
        ).model_dump(),
    }


@router.post("/{task_id}/audit")
async def start_audit(
    task_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
) -> dict:
    task = database.fetch_task(task_id, user_id)
    if not task:
        raise NotFoundError("审核任务不存在")
    if not task.parsed_text:
        raise ParseError("PARSE_EMPTY_CONTENT", "当前任务没有可审核的解析文本", 400)

    database.update_task(task_id, status=TASK_STATUS_ANALYZING, error_code=None, error_message=None)
    background_tasks.add_task(_run_audit_job, task_id, user_id)
    return {
        "success": True,
        "data": StartAuditResponse(
            task_id=task_id,
            audit_job_id=task_id,
            status=TASK_STATUS_ANALYZING,
        ).model_dump(),
    }


@router.get("/{task_id}/result")
async def get_audit_result(task_id: str, user_id: str = Depends(get_user_id)) -> dict:
    task = database.fetch_task(task_id, user_id)
    if not task:
        raise NotFoundError("审核任务不存在")

    result_record = database.fetch_audit_result(task_id)
    result_payload = result_record.result_json if result_record else None
    summary_payload = None
    risks_payload = None
    if result_payload:
        summary_payload = {
            "total_risks": result_payload["total_risks"],
            "high_risks": result_payload["high_risks"],
            "medium_risks": result_payload["medium_risks"],
            "low_risks": result_payload["low_risks"],
            "overall_message": result_payload["overall_message"],
        }
        risks_payload = result_payload["risks"]

    return {
        "success": True,
        "data": AuditResultResponse(
            task_id=task.id,
            status=task.status,
            error_code=task.error_code,
            error_message=task.error_message,
            result=result_payload,
            summary=summary_payload,
            risks=risks_payload,
        ).model_dump(),
    }


@router.get("/history")
async def get_history(user_id: str = Depends(get_user_id)) -> dict:
    rows = database.list_tasks(user_id)
    items = [
        HistoryItem(
            id=row["id"],
            task_id=row["id"],
            title=_history_title(row["file_name"], row["source_type"]),
            source_type=row["source_type"],
            file_name=row["file_name"],
            status=row["status"],
            status_text=_status_text(row["status"]),
            total_risks=row["total_risks"],
            high_risks=row["high_risks"],
            medium_risks=row["medium_risks"],
            low_risks=row["low_risks"],
            overall_message=row["overall_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["updated_at"] if row["status"] == TASK_STATUS_SUCCESS else None,
        ).model_dump()
        for row in rows
    ]
    return {"success": True, "data": {"items": items}}


@router.delete("/{task_id}")
async def delete_history(task_id: str, user_id: str = Depends(get_user_id)) -> dict:
    task = database.fetch_task(task_id, user_id)
    if not task:
        raise NotFoundError("审核任务不存在")
    if task.file_url:
        path = Path(task.file_url)
        if path.exists():
            path.unlink()
    deleted = database.delete_task(task_id, user_id)
    return {"success": True, "data": DeleteResponse(task_id=task_id, deleted=deleted).model_dump()}


def _run_audit_job(task_id: str, user_id: str) -> None:
    task = database.fetch_task(task_id, user_id)
    if not task or not task.parsed_text:
        database.update_task(
            task_id,
            status=TASK_STATUS_FAILED,
            error_code="AUDIT_TASK_MISSING",
            error_message="审核任务不存在或缺少解析文本",
        )
        return

    try:
        result = audit_service.analyze(task.parsed_text)
        database.save_audit_result(task_id, result)
        database.update_task(task_id, status=TASK_STATUS_SUCCESS, error_code=None, error_message=None)
    except AuditError as exc:
        database.update_task(
            task_id,
            status=TASK_STATUS_FAILED,
            error_code=exc.code,
            error_message=exc.message,
        )
    except Exception:
        database.update_task(
            task_id,
            status=TASK_STATUS_FAILED,
            error_code="AUDIT_FAILED",
            error_message="审核失败，请稍后重试",
        )
