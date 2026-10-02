# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Plain-text reporting format for completed social enrichment results."""
from __future__ import annotations

import html
import re
from datetime import date

from src.dates import parse_social_datetime
from src.models import DataField, FieldStatus, SocialResult


MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HANDLE_PLATFORMS = {"Instagram", "TikTok", "Threads", "X"}
METRIC_ORDERS = {
    "TikTok": ("likes", "comments", "bookmarks", "shares", "reposts"),
    "Facebook": ("likes", "comments", "shares", "bookmarks", "reposts"),
    "Instagram": ("likes", "comments", "reposts", "shares", "bookmarks"),
    "Threads": ("likes", "comments", "reposts", "shares", "bookmarks"),
    "X": ("likes", "comments", "reposts", "bookmarks", "shares"),
    "YouTube": ("likes", "comments", "shares", "bookmarks", "reposts"),
}
METRIC_LABELS = {
    "likes": "Like",
    "comments": "Comment",
    "bookmarks": "Save",
    "shares": "Share",
    "reposts": "Repost",
}
INDONESIAN_NUMBERS = {
    1: "Satu",
    2: "Dua",
    3: "Tiga",
    4: "Empat",
    5: "Lima",
    6: "Enam",
    7: "Tujuh",
    8: "Delapan",
    9: "Sembilan",
    10: "Sepuluh",
}
ENGLISH_NUMBERS = {
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
    10: "Ten",
}


def _clean_caption(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.I)
    text = re.sub(r"(?<!\w)#[\w.-]+", " ", text)
    text = re.sub(r"\b(?:see|lihat)\s+(?:more|selengkapnya|translation|terjemahan)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" \t\r\n|•-–—")


def _caption_sentences(value: str) -> list[str]:
    text = _clean_caption(value)
    if not text:
        return []
    sentences = [
        sentence.strip(" \t\r\n|•-–—")
        for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", text)
    ]
    return [sentence for sentence in sentences if len(sentence.split()) >= 3]


def _limit_words(value: str, maximum: int) -> str:
    words = value.split()
    if len(words) <= maximum:
        return value.strip()
    return f"{' '.join(words[:maximum]).rstrip(' ,;:.')}…"


def reportable_social_results(results: list[SocialResult]) -> list[SocialResult]:
    """Keep rows with enough real metadata to produce a useful report block."""
    reportable: list[SocialResult] = []
    for result in results:
        fields = (
            result.username,
            result.caption,
            result.posted_at,
            result.likes,
            result.comments,
            result.bookmarks,
            result.shares,
            result.reposts,
        )
        if any(
            field.status == FieldStatus.AVAILABLE and field.value not in (None, "")
            for field in fields
        ):
            reportable.append(result)
    return reportable


def build_social_report_message(
    results: list[SocialResult],
    language: str = "Indonesia",
) -> str:
    """Build an editable, extractive message from the available captions."""
    report_results = reportable_social_results(results)
    captions = [
        str(result.caption.value)
        for result in report_results
        if result.caption.status == FieldStatus.AVAILABLE
        and result.caption.value not in (None, "")
    ]
    sentence_groups = [_caption_sentences(caption) for caption in captions]
    candidates: list[str] = []
    # Pick the lead sentence from every post before taking supporting details.
    for sentence_index in range(2):
        for sentences in sentence_groups:
            if sentence_index < len(sentences):
                candidates.append(sentences[sentence_index])

    selected: list[str] = []
    seen: set[str] = set()
    for sentence in candidates:
        key = re.sub(r"[^a-z0-9]+", "", sentence.casefold())
        if not key or key in seen:
            continue
        if any(key in previous or previous in key for previous in seen if len(previous) >= 40):
            continue
        seen.add(key)
        selected.append(sentence)
        if len(" ".join(selected).split()) >= 65:
            break

    english = language.casefold().startswith("eng")
    if not selected:
        return "Caption summary is not available." if english else "Ringkasan caption belum tersedia."

    summary = _limit_words(" ".join(selected), 70 if len(report_results) > 1 else 60)
    if summary and summary[-1] not in ".!?…":
        summary += "."
    if len(report_results) <= 1:
        return summary

    count = len(report_results)
    if english:
        count_text = ENGLISH_NUMBERS.get(count, str(count))
        return f"{count_text} posts highlight the following caption information: {summary}"
    count_text = INDONESIAN_NUMBERS.get(count)
    prefix = f"{count_text} unggahan" if count_text else f"Sebanyak {count} unggahan"
    return f"{prefix} menyoroti informasi berikut dari caption: {summary}"


def _report_date(value) -> date | None:
    parsed = parse_social_datetime(value)
    return parsed.date() if parsed else None


def format_report_date(value, *, language: str = "Indonesia") -> str:
    parsed = _report_date(value)
    if parsed is None:
        return "Date unavailable" if language.casefold().startswith("eng") else "Tanggal tidak tersedia"
    return f"{parsed.day} {MONTH_NAMES[parsed.month - 1]} {parsed.year:04d}"


def _date_range(results: list[SocialResult], language: str) -> str:
    dates = sorted(
        {
            parsed
            for result in results
            if (parsed := _report_date(result.posted_at.value)) is not None
        }
    )
    if not dates:
        return "Date unavailable" if language.casefold().startswith("eng") else "Tanggal tidak tersedia"
    first, last = dates[0], dates[-1]
    if first == last:
        return format_report_date(first, language=language)
    if first.year == last.year and first.month == last.month:
        return f"{first.day}–{last.day} {MONTH_NAMES[first.month - 1]} {first.year:04d}"
    if first.year == last.year:
        return (
            f"{first.day} {MONTH_NAMES[first.month - 1]}–"
            f"{last.day} {MONTH_NAMES[last.month - 1]} {first.year:04d}"
        )
    return (
        f"{first.day} {MONTH_NAMES[first.month - 1]} {first.year:04d}–"
        f"{last.day} {MONTH_NAMES[last.month - 1]} {last.year:04d}"
    )


def _author(result: SocialResult, language: str) -> str:
    value = re.sub(r"\s+", " ", str(result.username.value or "")).strip()
    if not value:
        return "Author unavailable" if language.casefold().startswith("eng") else "Author tidak tersedia"
    if result.platform in HANDLE_PLATFORMS and " " not in value and not value.startswith("@"):
        value = f"@{value}"
    if result.platform == "Facebook":
        value = value.replace(" - ", " / ")
    return value


def _metric_number(field: DataField) -> int | None:
    if field.status != FieldStatus.AVAILABLE or field.value in (None, ""):
        return None
    try:
        return max(0, int(float(str(field.value).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def engagement_items(result: SocialResult) -> tuple[list[tuple[str, int]], int | None]:
    """Return visible interaction counters and their total, excluding views."""
    items: list[tuple[str, int]] = []
    for name in METRIC_ORDERS.get(result.platform, METRIC_ORDERS["YouTube"]):
        value = _metric_number(getattr(result, name))
        if value is not None:
            items.append((METRIC_LABELS[name], value))
    return items, sum(value for _, value in items) if items else None


def format_social_report(
    results: list[SocialResult],
    language: str = "Indonesia",
    *,
    message: str | None = None,
) -> str:
    """Render the copy-ready single- or multi-post reporting format."""
    report_results = reportable_social_results(results)
    if not report_results:
        return ""
    english = language.casefold().startswith("eng")
    message_label = "Message" if english else "Pesan"
    unavailable = "Not available" if english else "Belum tersedia"
    message_text = (message or "").strip() or build_social_report_message(report_results, language)
    platforms = list(dict.fromkeys(result.platform for result in report_results))
    platform_text = " & ".join(platforms)

    if len(report_results) == 1:
        result = report_results[0]
        items, total = engagement_items(result)
        engagement = ", ".join(f"{label} {value:,}" for label, value in items) or unavailable
        total_text = f"{total:,}" if total is not None else unavailable
        return "\n".join(
            (
                f"{platform_text} — {format_report_date(result.posted_at.value, language=language)}",
                f"{_author(result, language)} — {result.url}",
                f"{message_label}: {message_text}",
                f"Engagement: {engagement}",
                f"Total Engagement: {total_text}",
            )
        )

    lines = [
        f"{platform_text} — {_date_range(report_results, language)} — {len(report_results)} Posts",
        f"{message_label}: {message_text}",
        "",
    ]
    all_totals: list[int] = []
    for result in report_results:
        items, total = engagement_items(result)
        engagement = ", ".join(f"{label} {value:,}" for label, value in items) or unavailable
        total_text = f"{total:,}" if total is not None else unavailable
        if total is not None:
            all_totals.append(total)
        lines.extend(
            (
                f"{_author(result, language)} — {format_report_date(result.posted_at.value, language=language)}",
                f"\t{result.url}",
                f"\tEngagement: {engagement}",
                f"\tTotal Engagement: {total_text}",
                "",
            )
        )
    overall = f"{sum(all_totals):,}" if all_totals else unavailable
    lines.append(f"Total All Engagement: {overall}")
    return "\n".join(lines)
