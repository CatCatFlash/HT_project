import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from .config import DB_PATH
from .models import AuditResultRecord, ContractTask


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contract_tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                file_name TEXT,
                file_url TEXT,
                raw_text TEXT,
                parsed_text TEXT,
                status TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_results (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL UNIQUE,
                total_risks INTEGER NOT NULL,
                high_risks INTEGER NOT NULL,
                medium_risks INTEGER NOT NULL,
                low_risks INTEGER NOT NULL,
                overall_message TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES contract_tasks(id)
            )
            """
        )


def _now() -> str:
    return datetime.utcnow().isoformat()


def create_task(
    *,
    task_id: str,
    user_id: str,
    source_type: str,
    file_name: str | None,
    file_url: str | None,
    raw_text: str | None,
    parsed_text: str | None,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO contract_tasks (
                id, user_id, source_type, file_name, file_url, raw_text,
                parsed_text, status, error_code, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                source_type,
                file_name,
                file_url,
                raw_text,
                parsed_text,
                status,
                error_code,
                error_message,
                now,
                now,
            ),
        )


def update_task(
    task_id: str,
    *,
    parsed_text: str | None = None,
    raw_text: str | None = None,
    status: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if parsed_text is not None:
        fields.append("parsed_text = ?")
        values.append(parsed_text)
    if raw_text is not None:
        fields.append("raw_text = ?")
        values.append(raw_text)
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    fields.append("error_code = ?")
    values.append(error_code)
    fields.append("error_message = ?")
    values.append(error_message)
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(task_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE contract_tasks SET {', '.join(fields)} WHERE id = ?",
            values,
        )


def fetch_task(task_id: str, user_id: str) -> ContractTask | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM contract_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
    return _row_to_task(row) if row else None


def list_tasks(user_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                t.*,
                r.total_risks,
                r.high_risks,
                r.medium_risks,
                r.low_risks,
                r.overall_message
            FROM contract_tasks t
            LEFT JOIN audit_results r ON r.task_id = t.id
            WHERE t.user_id = ?
            ORDER BY t.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_task(task_id: str, user_id: str) -> bool:
    with get_connection() as conn:
        conn.execute("DELETE FROM audit_results WHERE task_id = ?", (task_id,))
        result = conn.execute(
            "DELETE FROM contract_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
    return result.rowcount > 0


def save_audit_result(task_id: str, result: dict[str, Any]) -> None:
    result_id = f"result_{task_id}"
    created_at = _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_results (
                id, task_id, total_risks, high_risks, medium_risks,
                low_risks, overall_message, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                total_risks = excluded.total_risks,
                high_risks = excluded.high_risks,
                medium_risks = excluded.medium_risks,
                low_risks = excluded.low_risks,
                overall_message = excluded.overall_message,
                result_json = excluded.result_json,
                created_at = excluded.created_at
            """,
            (
                result_id,
                task_id,
                result["total_risks"],
                result["high_risks"],
                result["medium_risks"],
                result["low_risks"],
                result["overall_message"],
                json.dumps(result, ensure_ascii=False),
                created_at,
            ),
        )


def fetch_audit_result(task_id: str) -> AuditResultRecord | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM audit_results WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    return _row_to_result(row) if row else None


def _row_to_task(row: sqlite3.Row) -> ContractTask:
    return ContractTask(
        id=row["id"],
        user_id=row["user_id"],
        source_type=row["source_type"],
        file_name=row["file_name"],
        file_url=row["file_url"],
        raw_text=row["raw_text"],
        parsed_text=row["parsed_text"],
        status=row["status"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_result(row: sqlite3.Row) -> AuditResultRecord:
    result_json = json.loads(row["result_json"])
    return AuditResultRecord(
        id=row["id"],
        task_id=row["task_id"],
        total_risks=row["total_risks"],
        high_risks=row["high_risks"],
        medium_risks=row["medium_risks"],
        low_risks=row["low_risks"],
        overall_message=row["overall_message"],
        result_json=result_json,
        created_at=datetime.fromisoformat(row["created_at"]),
    )
