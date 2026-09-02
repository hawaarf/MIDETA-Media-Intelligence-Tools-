"""Batch URL and tabular result helpers."""
from __future__ import annotations
from datetime import date, datetime
import re

from src.models import SocialResult

SOCIAL_BATCH_VERSION = 14

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_posting_date(value) -> str:
    """Format a posting date consistently for tables and downloads."""
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                return text
    return f"{parsed.day:02d}-{MONTH_NAMES[parsed.month - 1]}-{parsed.year:04d}"

def parse_url_list(value: str) -> list[str]:
    """Return unique nonempty URLs while preserving input order."""
    return list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))


def is_current_social_batch(batch: dict) -> bool:
    """Return whether a stored UI batch uses the active parser format."""
    return batch.get("schema_version") == SOCIAL_BATCH_VERSION

def social_result_row(result: SocialResult) -> dict:
    fields = {
        "Tanggal posting": result.posted_at,
        "Author": result.username,
        "Caption": result.caption,
        "Followers": result.followers,
        "Views": result.views,
        "Likes": result.likes,
        "Comments": result.comments,
        "Save atau bookmark": result.bookmarks,
        "Shares": result.shares,
        "Reposts": result.reposts,
    }
    row = {"URL": result.url, "Platform": result.platform, "Waktu pengambilan": result.collected_at.isoformat(), "Data contoh": result.is_mock, "Catatan": result.note}
    for label, field in fields.items():
        row[label] = field.value
        row[f"Status {label}"] = str(field.status)
    return row


def compact_social_export_row(result: SocialResult) -> dict:
    """Create a compact, spreadsheet-friendly enrichment row.

    Detailed field statuses remain available in the interface. Downloads use one
    concise availability summary so the file stays readable in CSV and XLSX.
    """
    fields = (
        ("Tanggal posting", result.posted_at),
        ("Author", result.username),
        ("Caption", result.caption),
        ("Followers", result.followers),
        ("Views", result.views),
        ("Likes", result.likes),
        ("Comments", result.comments),
        ("Save atau bookmark", result.bookmarks),
        ("Shares", result.shares),
        ("Reposts", result.reposts),
    )
    unavailable: list[str] = []
    row = {"Platform": result.platform, "URL": result.url}
    for label, field in fields:
        if field.value in (None, ""):
            row[label] = "Tidak tersedia"
            unavailable.append(label)
            continue
        value = field.value
        if label == "Tanggal posting":
            value = format_posting_date(value)
        if isinstance(value, str):
            value = re.sub(r"\s+", " ", value).strip()
        row[label] = value
    row["Waktu pengambilan"] = result.collected_at.strftime("%Y-%m-%d %H:%M:%S")
    row["Data yang tidak tersedia"] = ", ".join(unavailable) if unavailable else "Lengkap"
    return row

def rank_comment_rows(rows: list[dict]) -> list[dict]:
    """Rank globally by likes and replies, favoring active conversations."""
    def value(row: dict, key: str) -> int:
        raw = row.get(key)
        try:
            return int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            return 0
    ranked = sorted(rows, key=lambda row: (value(row, "Likes") + 2 * value(row, "Jumlah reply"), value(row, "Jumlah reply"), value(row, "Likes")), reverse=True)
    for index, row in enumerate(ranked, 1):
        row["Rank"] = index
        row["Skor engagement"] = value(row, "Likes") + 2 * value(row, "Jumlah reply")
    return ranked
