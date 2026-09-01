"""SQLite persistence for MIDETA analysis history."""
from __future__ import annotations
import json
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from src.config import DATABASE_PATH
from src.models import HistoryRecord

SCHEMA = """CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, feature TEXT NOT NULL, platform TEXT, source_url TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_history_feature ON history(feature); CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at);"""

def connect(path: Path = DATABASE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection

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
