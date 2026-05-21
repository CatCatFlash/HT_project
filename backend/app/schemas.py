from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["high", "medium", "low"]
TaskStatus = Literal["uploaded", "parsing", "parsed", "analyzing", "success", "failed"]


class ApiResponse(BaseModel):
    success: bool = True
    data: dict


class ErrorResponse(BaseModel):
    success: bool = False
    error: dict
    trace_id: str


class RiskItem(BaseModel):
    title: str = Field(..., description="风险标题")
    level: RiskLevel = Field(..., description="风险等级")
    reason: str = Field(..., description="风险原因")
    suggestion: str = Field(..., description="修改建议")


class AuditStructuredResult(BaseModel):
    strategy_version: str | None = None
    total_risks: int
    high_risks: int
    medium_risks: int
    low_risks: int
    overall_message: str
    core_risks: list[RiskItem] | None = None
    additional_risks: list[RiskItem] | None = None
    risks: list[RiskItem]


class TextSubmitRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=100_000)


class UploadInlineRequest(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=255)
    file_content_base64: str = Field(..., min_length=1)


class UploadResponse(BaseModel):
    task_id: str
    file_id: str
    file_name: str
    upload_status: TaskStatus
    parse_status: TaskStatus
    preview_text: str | None = None
    char_count: int | None = None
    page_count: int | None = None


class TextSubmitResponse(BaseModel):
    task_id: str
    status: TaskStatus
    preview_text: str
    char_count: int


class PreviewResponse(BaseModel):
    task_id: str
    source_type: str
    file_name: str | None
    parsed_text: str
    preview_text: str
    char_count: int
    status: TaskStatus
    page_count: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class StartAuditResponse(BaseModel):
    task_id: str
    audit_job_id: str
    status: TaskStatus


class AuditResultResponse(BaseModel):
    task_id: str
    status: TaskStatus
    error_code: str | None = None
    error_message: str | None = None
    result: AuditStructuredResult | None = None
    summary: dict | None = None
    risks: list[RiskItem] | None = None


class HistoryItem(BaseModel):
    id: str
    task_id: str
    title: str
    source_type: str
    file_name: str | None
    status: TaskStatus
    status_text: str
    total_risks: int | None = None
    high_risks: int | None = None
    medium_risks: int | None = None
    low_risks: int | None = None
    overall_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class DeleteResponse(BaseModel):
    task_id: str
    deleted: bool


ProgressStatus = Literal["on-track", "attention", "risk"]


class ProgressDialogItem(BaseModel):
    id: int
    name: str
    owner: str
    progress: int = Field(..., ge=0, le=100)
    status: ProgressStatus
    phase: str
    summary: str
    blockers: str
    next_step: str
    due_label: str
    updated_at: datetime


class ProgressDialogUpdateRequest(BaseModel):
    owner: str = Field(..., min_length=1, max_length=50)
    progress: int = Field(..., ge=0, le=100)
    status: ProgressStatus
    phase: str = Field(..., min_length=1, max_length=50)
    summary: str = Field(..., min_length=1, max_length=300)
    blockers: str = Field(..., min_length=1, max_length=300)
    next_step: str = Field(..., min_length=1, max_length=300)
    due_label: str = Field(..., min_length=1, max_length=50)


class ProgressOverview(BaseModel):
    completion: int
    healthy_count: int
    attention_count: int
    risk_count: int


class ProgressDashboardResponse(BaseModel):
    overview: ProgressOverview
    items: list[ProgressDialogItem]
