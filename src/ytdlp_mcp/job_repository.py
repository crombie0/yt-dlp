from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteJobRepository:
    def __init__(self, path: Path):
        self._path = path.expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def path(self) -> Path:
        return self._path

    def load_all(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    job_id,
                    kind,
                    status,
                    created_at,
                    updated_at,
                    progress_json,
                    result_json,
                    error_json,
                    logs_json,
                    files_json,
                    info_json
                FROM jobs
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [
            {
                "job_id": row["job_id"],
                "kind": row["kind"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "progress": _loads(row["progress_json"], {}),
                "result": _loads(row["result_json"], None),
                "error": _loads(row["error_json"], None),
                "logs": _loads(row["logs_json"], []),
                "files": _loads(row["files_json"], []),
                "info": _loads(row["info_json"], None),
            }
            for row in rows
        ]

    def save(self, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id,
                    kind,
                    status,
                    created_at,
                    updated_at,
                    progress_json,
                    result_json,
                    error_json,
                    logs_json,
                    files_json,
                    info_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    progress_json = excluded.progress_json,
                    result_json = excluded.result_json,
                    error_json = excluded.error_json,
                    logs_json = excluded.logs_json,
                    files_json = excluded.files_json,
                    info_json = excluded.info_json
                """,
                (
                    payload["job_id"],
                    payload["kind"],
                    payload["status"],
                    payload["created_at"],
                    payload["updated_at"],
                    _dumps(payload.get("progress", {})),
                    _dumps(payload.get("result")),
                    _dumps(payload.get("error")),
                    _dumps(payload.get("logs", [])),
                    _dumps(payload.get("files", [])),
                    _dumps(payload.get("info")),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    progress_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error_json TEXT NOT NULL,
                    logs_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    info_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
