"""SQLite persistence for MIDETA analysis history."""
from __future__ import annotations
import json
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from src.config import DATABASE_PATH
from src.models import HistoryRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature TEXT NOT NULL,
    platform TEXT,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_feature ON history(feature);
CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at);

CREATE TABLE IF NOT EXISTS social_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version INTEGER NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL,
    mock_mode INTEGER NOT NULL DEFAULT 0,
    browser_mode INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_social_jobs_platform ON social_jobs(platform, id DESC);

CREATE TABLE IF NOT EXISTS social_job_items (
    job_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT,
    error_json TEXT,
    browser_issue_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (job_id, position),
    FOREIGN KEY (job_id) REFERENCES social_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_social_job_items_status ON social_job_items(job_id, status, position);
"""

def connect(path: Path = DATABASE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


def create_social_job(
    platform: str,
    urls: list[str],
    schema_version: int,
    mock_mode: bool = False,
    browser_mode: bool = False,
    path: Path = DATABASE_PATH,
) -> int:
    """Create a durable enrichment queue and return its ID."""
    now = datetime.now().isoformat(timespec="seconds")
    with connect(path) as connection:
        cursor = connection.execute(
            "INSERT INTO social_jobs(schema_version, platform, status, total, mock_mode, browser_mode, created_at, updated_at) VALUES (?, ?, 'running', ?, ?, ?, ?, ?)",
            (schema_version, platform, len(urls), int(mock_mode), int(browser_mode), now, now),
        )
        job_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO social_job_items(job_id, position, source_url, status) VALUES (?, ?, ?, 'pending')",
            ((job_id, position, url) for position, url in enumerate(urls, 1)),
        )
    return job_id


def set_social_job_status(job_id: int, status: str, path: Path = DATABASE_PATH) -> bool:
    if status not in {"running", "paused", "completed"}:
        raise ValueError("Status proses enrichment tidak dikenal.")
    with connect(path) as connection:
        cursor = connection.execute(
            "UPDATE social_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(timespec="seconds"), job_id),
        )
        return cursor.rowcount > 0


def next_social_job_items(job_id: int, limit: int, path: Path = DATABASE_PATH) -> list[dict[str, Any]]:
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT position, source_url FROM social_job_items WHERE job_id = ? AND status = 'pending' ORDER BY position LIMIT ?",
            (job_id, limit),
        ).fetchall()
    return [{"position": row["position"], "url": row["source_url"]} for row in rows]


def record_social_job_item(
    job_id: int,
    position: int,
    status: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    browser_issue: dict[str, Any] | None = None,
    path: Path = DATABASE_PATH,
) -> None:
    if status not in {"completed", "failed"}:
        raise ValueError("Status URL enrichment tidak dikenal.")
    now = datetime.now().isoformat(timespec="seconds")
    with connect(path) as connection:
        connection.execute(
            "UPDATE social_job_items SET status = ?, result_json = ?, error_json = ?, browser_issue_json = ?, updated_at = ? WHERE job_id = ? AND position = ?",
            (
                status,
                json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                json.dumps(error, ensure_ascii=False, default=str) if error is not None else None,
                json.dumps(browser_issue, ensure_ascii=False, default=str) if browser_issue is not None else None,
                now,
                job_id,
                position,
            ),
        )
        pending = connection.execute(
            "SELECT COUNT(*) FROM social_job_items WHERE job_id = ? AND status = 'pending'",
            (job_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE social_jobs SET status = CASE WHEN ? = 0 THEN 'completed' ELSE status END, updated_at = ? WHERE id = ?",
            (pending, now, job_id),
        )


def get_social_job(job_id: int, path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    with connect(path) as connection:
        job = connection.execute("SELECT * FROM social_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            return None
        items = connection.execute(
            "SELECT * FROM social_job_items WHERE job_id = ? ORDER BY position",
            (job_id,),
        ).fetchall()
    results, errors, browser_issues = [], [], []
    for item in items:
        if item["result_json"]:
            results.append(json.loads(item["result_json"]))
        if item["error_json"]:
            errors.append(json.loads(item["error_json"]))
        if item["browser_issue_json"]:
            browser_issues.append(json.loads(item["browser_issue_json"]))
    processed = sum(item["status"] != "pending" for item in items)
    return {
        "id": job["id"],
        "schema_version": job["schema_version"],
        "platform": job["platform"],
        "status": job["status"],
        "total": job["total"],
        "processed": processed,
        "pending": job["total"] - processed,
        "mock_mode": bool(job["mock_mode"]),
        "browser_mode": bool(job["browser_mode"]),
        "results": results,
        "errors": errors,
        "browser_issues": browser_issues,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def get_latest_social_job(platform: str, path: Path = DATABASE_PATH) -> dict[str, Any] | None:
    with connect(path) as connection:
        row = connection.execute(
            "SELECT id FROM social_jobs WHERE platform = ? ORDER BY id DESC LIMIT 1",
            (platform,),
        ).fetchone()
    return get_social_job(int(row["id"]), path) if row else None

def add_history(feature: str, source_url: str, status: str, result: dict[str, Any], platform: str | None = None, path: Path = DATABASE_PATH) -> int:
    with connect(path) as connection:
        cursor = connection.execute("INSERT INTO history(feature, platform, source_url, status, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (feature, platform, source_url, status, json.dumps(result, ensure_ascii=False, default=str), datetime.now().isoformat(timespec="seconds")))
        return int(cursor.lastrowid)

def list_history(search: str = "", feature: str | None = None, platform: str | None = None, start: date | None = None, end: date | None = None, path: Path = DATABASE_PATH) -> list[HistoryRecord]:
    clauses, values = [], []
    if search:
        clauses.append("(source_url LIKE ? OR result_json LIKE ?)")
        values.extend([f"%{search}%", f"%{search}%"])
    if feature:
        clauses.append("feature = ?"); values.append(feature)
    if platform:
        clauses.append("platform = ?"); values.append(platform)
    if start:
        clauses.append("created_at >= ?"); values.append(datetime.combine(start, time.min).isoformat())
    if end:
        clauses.append("created_at <= ?"); values.append(datetime.combine(end, time.max).isoformat())
    query = "SELECT * FROM history" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at DESC"
    with connect(path) as connection:
        rows = connection.execute(query, values).fetchall()
    return [HistoryRecord(id=row["id"], feature=row["feature"], platform=row["platform"], source_url=row["source_url"], status=row["status"], result=json.loads(row["result_json"]), created_at=datetime.fromisoformat(row["created_at"])) for row in rows]

def delete_history(record_id: int, path: Path = DATABASE_PATH) -> bool:
    with connect(path) as connection:
        cursor = connection.execute("DELETE FROM history WHERE id = ?", (record_id,))
        return cursor.rowcount > 0

def update_history(record_id: int, status: str, result: dict[str, Any], platform: str | None = None, path: Path = DATABASE_PATH) -> bool:
    with connect(path) as connection:
        cursor = connection.execute("UPDATE history SET status = ?, result_json = ?, platform = COALESCE(?, platform) WHERE id = ?", (status, json.dumps(result, ensure_ascii=False, default=str), platform, record_id))
        return cursor.rowcount > 0
