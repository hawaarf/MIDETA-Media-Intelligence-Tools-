# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Turn discovered TikTok profile posts into standard enrichment results."""
from __future__ import annotations

from typing import Any, Callable, Iterable

from src.models import DataField, FieldStatus, SocialResult
from src.tiktok_browser import build_tiktok_browser_result
from src.tiktok_free import TikTokFreeCollector


def _field(value: Any, missing_status: FieldStatus = FieldStatus.NOT_PUBLIC) -> DataField:
    return DataField(
        value=value if value not in (None, "") else None,
        status=FieldStatus.AVAILABLE if value not in (None, "") else missing_status,
    )


def profile_row_result(
    row: dict[str, Any],
    *,
    failed_reason: str | None = None,
) -> SocialResult:
    """Build a standard TikTok row from already-discovered profile metadata."""
    numeric_status = FieldStatus.FAILED if failed_reason else FieldStatus.NOT_PUBLIC
    note = "Metadata dasar berasal dari Profile Scraping TikTok."
    if failed_reason:
        note = f"{note} Enrichment engagement gagal: {failed_reason}"
    return SocialResult(
        url=str(row.get("URL") or ""),
        platform="TikTok",
        username=_field(row.get("Author")),
        caption=_field(row.get("Caption")),
        posted_at=_field(row.get("Date Publish")),
        followers=_field(None, numeric_status),
        likes=_field(None, numeric_status),
        comments=_field(None, numeric_status),
        shares=_field(None, numeric_status),
        views=_field(None, numeric_status),
        bookmarks=_field(None, numeric_status),
        reposts=_field(None, FieldStatus.NOT_SUPPORTED),
        note=note,
    )


def merge_profile_metadata(result: SocialResult, row: dict[str, Any]) -> SocialResult:
    """Retain discovery metadata when an enrichment provider omits it."""
    merged = result.model_copy(deep=True)
    for name, key in (
        ("username", "Author"),
        ("caption", "Caption"),
        ("posted_at", "Date Publish"),
    ):
        field = getattr(merged, name)
        fallback = row.get(key)
        if field.value in (None, "") and fallback not in (None, ""):
            setattr(merged, name, _field(fallback))
    merged.url = str(row.get("URL") or merged.url)
    return merged


def enrich_profile_rows(
    rows: Iterable[dict[str, Any]],
    *,
    collector: TikTokFreeCollector | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[SocialResult]:
    """Enrich discovered posts in order using the normal TikTok collector."""
    source_rows = list(rows)
    active_collector = collector or TikTokFreeCollector()
    results: list[SocialResult] = []
    total = len(source_rows)
    for position, row in enumerate(source_rows, 1):
        url = str(row.get("URL") or "")
        try:
            metrics = active_collector.collect(url)
            enriched = build_tiktok_browser_result(url, metrics)
            result = merge_profile_metadata(enriched, row)
        except Exception as exc:
            result = profile_row_result(row, failed_reason=str(exc))
        results.append(result)
        if progress_callback:
            progress_callback(
                {
                    "processed": position,
                    "total": total,
                    "url": url,
                    "username": row.get("Author"),
                }
            )
    return results
