"""Batch URL and tabular result helpers."""
from __future__ import annotations
from datetime import date, datetime
import re

from src.dates import parse_social_datetime
from src.models import DataField, FieldStatus, SocialResult

SOCIAL_BATCH_VERSION = 42
COMMENT_BATCH_VERSION = 9

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FAILED_URL_MESSAGE = "URL tidak dapat diproses"


def format_posting_date(value) -> str:
    """Format a posting date consistently for tables and downloads."""
    parsed_datetime = parse_social_datetime(value)
    if parsed_datetime is None:
        return str(value).strip()
    parsed = parsed_datetime.date()
    return f"{parsed.day:02d}-{MONTH_NAMES[parsed.month - 1]}-{parsed.year:04d}"


def format_comment_date(value) -> str:
    """Use the short English date format from the comment reference file."""
    if value in (None, ""):
        return "Tidak tersedia"
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        text = str(value).strip()
        parsed = None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%b %d, %Y", "%a %b %d %H:%M:%S %z %Y"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return text
    return f"{MONTH_NAMES[parsed.month - 1]} {parsed.day}, {parsed.year:04d}"

URL_PATTERN = re.compile(r"https?://[^\s,<>\"'\[\](){}]+", re.IGNORECASE)
URL_TRAILING_PUNCTUATION = ".,;:!?"


def parse_url_list(value: str) -> list[str]:
    """Extract unique URLs from pasted rows while preserving input order.

    Spreadsheet rows often include a date or another column before the URL.
    Only the URL itself is sent to the connector, so values such as
    ``Aug 30, 2026 https://www.instagram.com/p/example/`` remain valid input.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for line in value.splitlines():
        for match in URL_PATTERN.findall(line):
            url = match.rstrip(URL_TRAILING_PUNCTUATION)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def group_social_urls(urls: list[str]) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    """Group mixed social URLs by their detected platform.

    Detection uses the same connector registry as enrichment, so aliases such as
    ``youtu.be``, ``fb.watch``, ``twitter.com``, and ``threads.com`` follow the
    same rules as the platform-specific input.
    """
    from src.connectors import detect_platform

    grouped: dict[str, list[str]] = {}
    unsupported: list[dict[str, str]] = []
    for url in urls:
        try:
            platform = detect_platform(url)
        except ValueError as exc:
            unsupported.append({"URL": url, "Alasan": str(exc)})
            continue
        grouped.setdefault(platform, []).append(url)
    return grouped, unsupported


def is_current_social_batch(batch: dict) -> bool:
    """Return whether a stored UI batch uses the active parser format."""
    return batch.get("schema_version") == SOCIAL_BATCH_VERSION


def failed_social_result(url: str, platform: str, reason: str | None = None) -> SocialResult:
    """Keep a failed URL in the same table position as the original input."""
    note = FAILED_URL_MESSAGE
    if reason:
        note = f"{note}: {reason}"

    def failed_field() -> DataField:
        return DataField(value=None, status=FieldStatus.FAILED)

    return SocialResult(
        url=url,
        platform=platform,
        username=failed_field(),
        caption=failed_field(),
        posted_at=failed_field(),
        followers=failed_field(),
        likes=failed_field(),
        comments=failed_field(),
        shares=failed_field(),
        views=failed_field(),
        bookmarks=failed_field(),
        reposts=failed_field(),
        note=note,
    )


def social_job_results(job: dict) -> list[SocialResult]:
    """Return processed job rows in their original input order, including failures."""
    items = job.get("items")
    if isinstance(items, list):
        ordered: list[SocialResult] = []
        for item in items:
            if item.get("result"):
                ordered.append(SocialResult.model_validate(item["result"]))
                continue
            if item.get("status") != "failed":
                continue
            error = item.get("error") or {}
            reason = error.get("Alasan") or error.get("reason") or error.get("error")
            ordered.append(
                failed_social_result(
                    str(item.get("url") or error.get("URL") or ""),
                    str(error.get("Platform") or job.get("platform") or "Tidak dikenali"),
                    str(reason) if reason else None,
                )
            )
        return ordered

    ordered = [SocialResult.model_validate(item) for item in job.get("results", [])]
    for error in job.get("errors", []):
        ordered.append(
            failed_social_result(
                str(error.get("URL") or ""),
                str(error.get("Platform") or job.get("platform") or "Tidak dikenali"),
                str(error.get("Alasan")) if error.get("Alasan") else None,
            )
        )
    return ordered


def social_result_failed(result: SocialResult) -> bool:
    fields = (
        result.username,
        result.caption,
        result.posted_at,
        result.followers,
        result.likes,
        result.comments,
        result.shares,
        result.views,
        result.bookmarks,
        result.reposts,
    )
    return all(field.status == FieldStatus.FAILED for field in fields)


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
    failed = social_result_failed(result)
    for label, field in fields.items():
        row[label] = FAILED_URL_MESSAGE if failed else field.value
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
    failed = social_result_failed(result)
    for label, field in fields:
        if failed:
            row[label] = FAILED_URL_MESSAGE
            continue
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
    row["Data yang tidak tersedia"] = (
        FAILED_URL_MESSAGE if failed else ", ".join(unavailable) if unavailable else "Lengkap"
    )
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


def compact_comment_export_rows(rows: list[dict]) -> list[dict]:
    """Match the concise column layout used by the supplied comment CSV."""
    export_rows = []
    for position, row in enumerate(rows, 1):
        author = re.sub(r"\s+", " ", str(row.get("Author") or "Tidak tersedia")).strip().lstrip("@")
        comment = re.sub(r"\s+", " ", str(row.get("Komentar") or "")).strip()
        try:
            likes = int(row.get("Likes") or 0)
        except (TypeError, ValueError):
            likes = 0
        export_rows.append(
            {
                "index": int(row.get("Rank") or position),
                "date": format_comment_date(row.get("Tanggal komentar")),
                "author": author,
                "type": row.get("Tipe") or "parent",
                "comment": comment,
                "like": likes,
            }
        )
    return export_rows
