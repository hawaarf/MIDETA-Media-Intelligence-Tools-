# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Fast YouTube enrichment through the official YouTube Data API v3."""
from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlparse

import requests

from src.config import DATA_DIR, REQUEST_TIMEOUT_SECONDS
from src.dates import social_datetime_iso
from src.models import DataField, FieldStatus, SocialResult
from src.social_urls import canonical_social_url, platform_from_url


YOUTUBE_API_KEY_PATH = DATA_DIR / "private" / "youtube_api_key"
YOUTUBE_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
YOUTUBE_CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
YOUTUBE_API_BATCH_SIZE = 50
YOUTUBE_API_RUNTIME_VERSION = 1
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


class YouTubeDataAPIError(RuntimeError):
    """Raised when the configured YouTube Data API cannot serve a batch."""


def _chunks(values: list[str], size: int = YOUTUBE_API_BATCH_SIZE) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _video_id(url: str) -> str | None:
    if platform_from_url(url) != "YouTube":
        return None
    canonical = canonical_social_url(url, "YouTube") or url
    parsed = urlparse(canonical)
    video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    return video_id if _VIDEO_ID_RE.fullmatch(video_id) else None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _field(value: Any, missing: FieldStatus = FieldStatus.NOT_PUBLIC) -> DataField:
    if value not in (None, ""):
        return DataField(value=value, status=FieldStatus.AVAILABLE)
    return DataField(value=None, status=missing)


def _empty_result(url: str, reason: str) -> SocialResult:
    unavailable = DataField(value=None, status=FieldStatus.NOT_PUBLIC)
    unsupported = DataField(value=None, status=FieldStatus.NOT_SUPPORTED)
    return SocialResult(
        url=url,
        platform="YouTube",
        username=unavailable,
        caption=unavailable,
        posted_at=unavailable,
        followers=unavailable,
        likes=unavailable,
        comments=unavailable,
        shares=unsupported,
        views=unavailable,
        bookmarks=unsupported,
        reposts=unsupported,
        note=reason,
    )


class YouTubeDataAPIClient:
    """Store a local API key and enrich YouTube URLs in API-sized batches."""

    def __init__(
        self,
        key_path: Path = YOUTUBE_API_KEY_PATH,
        *,
        request_timeout: int = REQUEST_TIMEOUT_SECONDS,
        request_get: Callable[..., Any] = requests.get,
    ):
        self.key_path = Path(key_path)
        self.request_timeout = request_timeout
        self.request_get = request_get
        self._channel_subscribers: dict[str, int | None] = {}
        self._cache_lock = Lock()

    def key_source(self) -> str:
        if os.getenv("YOUTUBE_API_KEY", "").strip():
            return "environment"
        try:
            if self.key_path.read_text(encoding="utf-8").strip():
                return "local"
        except OSError:
            pass
        return "none"

    def api_key(self) -> str | None:
        environment_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if environment_key:
            return environment_key
        try:
            saved_key = self.key_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return saved_key or None

    def has_key(self) -> bool:
        return bool(self.api_key())

    def save_key(self, value: str) -> None:
        key = str(value or "").strip()
        if len(key) < 20 or any(character.isspace() for character in key):
            raise YouTubeDataAPIError("YouTube API key tidak terlihat valid.")
        try:
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_text(key, encoding="utf-8")
            self.key_path.chmod(0o600)
        except OSError as exc:
            raise YouTubeDataAPIError("YouTube API key tidak dapat disimpan di komputer ini.") from exc

    def delete_key(self) -> None:
        try:
            self.key_path.unlink(missing_ok=True)
        except OSError as exc:
            raise YouTubeDataAPIError("YouTube API key lokal tidak dapat dihapus.") from exc

    @staticmethod
    def _error_message(payload: Any) -> str:
        if not isinstance(payload, dict):
            return "respons API tidak dapat dibaca"
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return "permintaan API ditolak"

    def _request(self, endpoint: str, params: dict[str, str], api_key: str) -> dict[str, Any]:
        try:
            response = self.request_get(
                endpoint,
                params={**params, "key": api_key},
                headers={"Accept": "application/json"},
                timeout=self.request_timeout,
            )
        except requests.RequestException as exc:
            raise YouTubeDataAPIError("YouTube Data API tidak dapat dihubungi.") from exc
        try:
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise YouTubeDataAPIError("YouTube Data API mengirim respons yang tidak dapat dibaca.") from exc
            status = int(getattr(response, "status_code", 200) or 200)
            if status >= 400:
                message = self._error_message(payload).replace(api_key, "[API key]")
                raise YouTubeDataAPIError(f"YouTube Data API HTTP {status}: {message}")
            if not isinstance(payload, dict):
                raise YouTubeDataAPIError("YouTube Data API mengirim format yang tidak dikenal.")
            return payload
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _video_items(self, video_ids: list[str], api_key: str) -> dict[str, dict[str, Any]]:
        items: dict[str, dict[str, Any]] = {}
        for group in _chunks(video_ids):
            payload = self._request(
                YOUTUBE_VIDEOS_ENDPOINT,
                {"part": "snippet,statistics", "id": ",".join(group)},
                api_key,
            )
            for item in payload.get("items") or []:
                if not isinstance(item, dict):
                    continue
                video_id = str(item.get("id") or "")
                if video_id in group:
                    items[video_id] = item
        return items

    def _subscriber_counts(
        self,
        channel_ids: list[str],
        api_key: str,
    ) -> tuple[dict[str, int | None], str]:
        unique_ids = list(dict.fromkeys(channel_id for channel_id in channel_ids if channel_id))
        with self._cache_lock:
            missing = [channel_id for channel_id in unique_ids if channel_id not in self._channel_subscribers]
        warning = ""
        try:
            for group in _chunks(missing):
                payload = self._request(
                    YOUTUBE_CHANNELS_ENDPOINT,
                    {"part": "statistics", "id": ",".join(group)},
                    api_key,
                )
                returned: set[str] = set()
                with self._cache_lock:
                    for item in payload.get("items") or []:
                        if not isinstance(item, dict):
                            continue
                        channel_id = str(item.get("id") or "")
                        if channel_id not in group:
                            continue
                        returned.add(channel_id)
                        statistics = item.get("statistics")
                        statistics = statistics if isinstance(statistics, dict) else {}
                        self._channel_subscribers[channel_id] = (
                            None
                            if statistics.get("hiddenSubscriberCount") is True
                            else _integer(statistics.get("subscriberCount"))
                        )
                    for channel_id in group:
                        if channel_id not in returned:
                            self._channel_subscribers[channel_id] = None
        except YouTubeDataAPIError as exc:
            warning = str(exc)
        with self._cache_lock:
            return ({channel_id: self._channel_subscribers.get(channel_id) for channel_id in unique_ids}, warning)

    def collect_many(self, urls: list[str]) -> dict[str, SocialResult]:
        api_key = self.api_key()
        if not api_key:
            raise YouTubeDataAPIError("YouTube API key belum disimpan.")

        url_video_ids = {url: _video_id(url) for url in urls}
        video_ids = list(dict.fromkeys(video_id for video_id in url_video_ids.values() if video_id))
        video_items = self._video_items(video_ids, api_key) if video_ids else {}
        channel_ids = [
            str((item.get("snippet") or {}).get("channelId") or "")
            for item in video_items.values()
            if isinstance(item.get("snippet"), dict)
        ]
        subscribers, channel_warning = self._subscriber_counts(channel_ids, api_key)

        results: dict[str, SocialResult] = {}
        for url, video_id in url_video_ids.items():
            if not video_id:
                results[url] = _empty_result(url, "ID video YouTube tidak dapat dibaca dari URL.")
                continue
            item = video_items.get(video_id)
            if not item:
                results[url] = _empty_result(
                    url,
                    "Video tidak ditemukan, privat, atau tidak tersedia melalui YouTube Data API.",
                )
                continue
            snippet = item.get("snippet")
            statistics = item.get("statistics")
            snippet = snippet if isinstance(snippet, dict) else {}
            statistics = statistics if isinstance(statistics, dict) else {}
            channel_id = str(snippet.get("channelId") or "")
            description = re.sub(r"\s+", " ", str(snippet.get("description") or "")).strip()
            published_at = social_datetime_iso(snippet.get("publishedAt"))
            note = "Metadata diambil melalui YouTube Data API."
            if channel_warning:
                note += f" Subscribers belum dapat diperbarui: {channel_warning}"
            results[url] = SocialResult(
                url=url,
                platform="YouTube",
                username=_field(str(snippet.get("channelTitle") or "").strip()),
                caption=_field(description),
                posted_at=_field(published_at),
                followers=_field(subscribers.get(channel_id)),
                likes=_field(_integer(statistics.get("likeCount"))),
                comments=_field(_integer(statistics.get("commentCount"))),
                shares=_field(None, FieldStatus.NOT_SUPPORTED),
                views=_field(_integer(statistics.get("viewCount"))),
                bookmarks=_field(None, FieldStatus.NOT_SUPPORTED),
                reposts=_field(None, FieldStatus.NOT_SUPPORTED),
                note=note,
            )
        return results
