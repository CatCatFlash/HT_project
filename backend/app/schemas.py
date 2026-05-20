from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["high", "medium", "low"]
TaskStatus = Literal["uploaded", "parsed", "analyzing", "success", "failed"]


class ApiResponse(BaseModel):
    success: bool = True
    data: dict


class ErrorResponse(BaseModel):
    success: bool = False
    error: dict


class RiskItem(BaseModel):
    title: str = Field(..., description="风险标题")
    level: RiskLevel = Field(..., description="风险等级")
    reason: str = Field(..., description="风险原因")
    suggestion: str = Field(..., description="修改建议")


class AuditStructuredResult(BaseModel):
    total_risks: int
    high_risks: int
    medium_risks: int
    low_risks: int
    overall_message: str
    risks: list[RiskItem]


class TextSubmitRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=100_000)


class UploadResponse(BaseModel):
    task_id: str
    file_id: str
    file_name: str
    upload_status: TaskStatus
    parse_status: TaskStatus
    preview_text: str
    char_count: int
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
