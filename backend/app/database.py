import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from .config import DB_PATH
from .models import AuditResultRecord, ContractTask, ProgressDialogRecord


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
                text_hash TEXT,
                strategy_version TEXT,
                status TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_task_columns(conn)
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS progress_dialogs (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT NOT NULL,
                progress INTEGER NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                summary TEXT NOT NULL,
                blockers TEXT NOT NULL,
                next_step TEXT NOT NULL,
                due_label TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _seed_progress_dialogs(conn)


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
    text_hash: str | None,
    strategy_version: str | None,
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
                parsed_text, text_hash, strategy_version, status, error_code, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                source_type,
                file_name,
                file_url,
                raw_text,
                parsed_text,
                text_hash,
                strategy_version,
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
    text_hash: str | None = None,
    strategy_version: str | None = None,
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
    if text_hash is not None:
        fields.append("text_hash = ?")
        values.append(text_hash)
    if strategy_version is not None:
        fields.append("strategy_version = ?")
        values.append(strategy_version)
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


def find_reusable_audit_result(
    *,
    user_id: str,
    text_hash: str,
    strategy_version: str,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                t.id AS task_id,
                t.created_at,
                r.result_json
            FROM contract_tasks t
            JOIN audit_results r ON r.task_id = t.id
            WHERE t.user_id = ?
              AND t.text_hash = ?
              AND t.strategy_version = ?
              AND t.status = 'success'
            ORDER BY t.updated_at DESC
            LIMIT 1
            """,
            (user_id, text_hash, strategy_version),
        ).fetchone()
    if not row:
        return None
    return {
        "task_id": row["task_id"],
        "created_at": row["created_at"],
        "result_json": json.loads(row["result_json"]),
    }


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


def list_progress_dialogs() -> list[ProgressDialogRecord]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM progress_dialogs
            ORDER BY id ASC
            """
        ).fetchall()
    return [_row_to_progress_dialog(row) for row in rows]


def update_progress_dialog(
    dialog_id: int,
    *,
    owner: str,
    progress: int,
    status: str,
    phase: str,
    summary: str,
    blockers: str,
    next_step: str,
    due_label: str,
) -> bool:
    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE progress_dialogs
            SET owner = ?, progress = ?, status = ?, phase = ?, summary = ?,
                blockers = ?, next_step = ?, due_label = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                owner,
                progress,
                status,
                phase,
                summary,
                blockers,
                next_step,
                due_label,
                _now(),
                dialog_id,
            ),
        )
    return result.rowcount > 0


def _row_to_task(row: sqlite3.Row) -> ContractTask:
    return ContractTask(
        id=row["id"],
        user_id=row["user_id"],
        source_type=row["source_type"],
        file_name=row["file_name"],
        file_url=row["file_url"],
        raw_text=row["raw_text"],
        parsed_text=row["parsed_text"],
        text_hash=row["text_hash"] if "text_hash" in row.keys() else None,
        strategy_version=row["strategy_version"] if "strategy_version" in row.keys() else None,
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


def _row_to_progress_dialog(row: sqlite3.Row) -> ProgressDialogRecord:
    return ProgressDialogRecord(
        id=row["id"],
        name=row["name"],
        owner=row["owner"],
        progress=row["progress"],
        status=row["status"],
        phase=row["phase"],
        summary=row["summary"],
        blockers=row["blockers"],
        next_step=row["next_step"],
        due_label=row["due_label"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _ensure_task_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(contract_tasks)").fetchall()
    }
    if "text_hash" not in existing:
        conn.execute("ALTER TABLE contract_tasks ADD COLUMN text_hash TEXT")
    if "strategy_version" not in existing:
        conn.execute("ALTER TABLE contract_tasks ADD COLUMN strategy_version TEXT")


def _seed_progress_dialogs(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS count FROM progress_dialogs").fetchone()
    if existing and existing["count"] > 0:
        return

    now = _now()
    seed_rows = [
        (
            1,
            "需求确认",
            "产品负责人",
            92,
            "on-track",
            "即将完成",
            "核心范围与 V1 边界已经确认，等待最后一轮业务口径签字。",
            "需要业务侧确认免责声明最终文案。",
            "完成最后签字后冻结 V1 范围。",
            "今天 18:00",
            now,
        ),
        (
            2,
            "交互设计",
            "UI 设计",
            76,
            "attention",
            "细节优化",
            "主链路页面已经成型，但后台筛选交互还在打磨。",
            "移动端窄屏状态下的详情布局还需要压缩。",
            "补完移动端适配并交付切图规范。",
            "明天 12:00",
            now,
        ),
        (
            3,
            "前端开发",
            "Web 前端",
            81,
            "on-track",
            "功能收口",
            "主流程界面已跑通，当前进入状态管理和细节收口阶段。",
            "等待后端联调地址和统一错误码。",
            "切换真实接口并补齐加载与异常态。",
            "5 月 21 日",
            now,
        ),
        (
            4,
            "后端接口",
            "服务端开发",
            68,
            "attention",
            "联调准备",
            "接口结构已完成，当前卡在真实审核服务接入和稳定性校验。",
            "真实模型服务尚未接入，当前仍使用 Mock 流程。",
            "完成审核服务接入并提供联调环境。",
            "5 月 22 日",
            now,
        ),
        (
            5,
            "测试验收",
            "测试同学",
            44,
            "risk",
            "等待联调",
            "测试用例框架已列出，但真实联调前还无法完成核心回归。",
            "缺少真实接口和样例数据，暂时只能覆盖 Mock 路径。",
            "联调完成后启动首轮回归。",
            "5 月 23 日",
            now,
        ),
        (
            6,
            "上线准备",
            "项目经理",
            37,
            "risk",
            "预备阶段",
            "上线清单已开始整理，但依赖前面几个模块的交付时间。",
            "联调与测试时间偏紧，需要预留缓冲。",
            "根据测试结果锁定发布时间和回滚方案。",
            "5 月 24 日",
            now,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO progress_dialogs (
            id, name, owner, progress, status, phase, summary,
            blockers, next_step, due_label, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        seed_rows,
    )
