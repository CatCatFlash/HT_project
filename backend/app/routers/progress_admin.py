from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .. import database
from ..exceptions import NotFoundError
from ..schemas import (
    ProgressDashboardResponse,
    ProgressDialogItem,
    ProgressDialogUpdateRequest,
    ProgressOverview,
)

router = APIRouter(tags=["progress-admin"])
STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "progress_admin"


@router.get("/admin/progress")
async def progress_admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/v1/progress/dialogs")
async def list_progress_dialogs() -> dict:
    items = database.list_progress_dialogs()
    payload = [ProgressDialogItem(**item.__dict__).model_dump() for item in items]
    return {
        "success": True,
        "data": ProgressDashboardResponse(
            overview=_build_overview(items),
            items=payload,
        ).model_dump(),
    }


@router.put("/api/v1/progress/dialogs/{dialog_id}")
async def update_progress_dialog(dialog_id: int, request: ProgressDialogUpdateRequest) -> dict:
    updated = database.update_progress_dialog(
        dialog_id,
        owner=request.owner,
        progress=request.progress,
        status=request.status,
        phase=request.phase,
        summary=request.summary,
        blockers=request.blockers,
        next_step=request.next_step,
        due_label=request.due_label,
    )
    if not updated:
        raise NotFoundError("进度窗口不存在")

    items = database.list_progress_dialogs()
    current = next((item for item in items if item.id == dialog_id), None)
    if current is None:
        raise NotFoundError("进度窗口不存在")

    return {
        "success": True,
        "data": ProgressDialogItem(**current.__dict__).model_dump(),
    }


def _build_overview(items: list) -> ProgressOverview:
    total = len(items) or 1
    completion = round(sum(item.progress for item in items) / total)
    healthy_count = sum(1 for item in items if item.status == "on-track")
    attention_count = sum(1 for item in items if item.status == "attention")
    risk_count = sum(1 for item in items if item.status == "risk")
    return ProgressOverview(
        completion=completion,
        healthy_count=healthy_count,
        attention_count=attention_count,
        risk_count=risk_count,
    )
