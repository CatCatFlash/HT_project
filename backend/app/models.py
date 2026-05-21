from dataclasses import dataclass
from datetime import datetime
from typing import Any


TASK_STATUS_UPLOADED = "uploaded"
TASK_STATUS_PARSING = "parsing"
TASK_STATUS_PARSED = "parsed"
TASK_STATUS_ANALYZING = "analyzing"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_FAILED = "failed"

SOURCE_TYPE_FILE = "file"
SOURCE_TYPE_TEXT = "text"


@dataclass
class ContractTask:
    id: str
    user_id: str
    source_type: str
    file_name: str | None
    file_url: str | None
    raw_text: str | None
    parsed_text: str | None
    text_hash: str | None
    strategy_version: str | None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass
class AuditResultRecord:
    id: str
    task_id: str
    total_risks: int
    high_risks: int
    medium_risks: int
    low_risks: int
    overall_message: str
    result_json: dict[str, Any]
    created_at: datetime


@dataclass
class ProgressDialogRecord:
    id: int
    name: str
    owner: str
    progress: int
    status: str
    phase: str
    summary: str
    blockers: str
    next_step: str
    due_label: str
    updated_at: datetime
