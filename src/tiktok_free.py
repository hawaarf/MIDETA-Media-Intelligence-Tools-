"""TikTok enrichment through public oEmbed and an optional Apify free-tier token."""
from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from src.config import DATA_DIR, MAX_REDIRECTS, REQUEST_TIMEOUT_SECONDS
from src.connectors.base import BaseConnector
from src.connectors.tiktok import TikTokConnector
from src.dates import social_datetime_iso
from src.http_client import USER_AGENT
from src.tiktok_browser import TikTokBrowserMetrics
from src.validators import validate_public_url


APIFY_TOKEN_PATH = DATA_DIR / "private" / "apify_token"
APIFY_ACTOR_ENDPOINT = (
    "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/"
    "run-sync-get-dataset-items"
)
TIKTOK_OEMBED_ENDPOINT = "https://www.tiktok.com/oembed"
TIKTOK_PUBLIC_FALLBACK_ENDPOINT = "https://www.tikwm.com/api/"
TIKTOK_FREE_PARSER_VERSION = 3


class TikTokFreeError(RuntimeError):
    pass


class TikTokFreeCollector:
    """Collect public TikTok data without navigating an automated browser."""

    _fallback_lock = Lock()
    _last_fallback_request = 0.0

    def __init__(
        self,
        token_path: Path = APIFY_TOKEN_PATH,
        request_timeout: int = REQUEST_TIMEOUT_SECONDS,
        actor_timeout: int = 180,
    ):
        self.token_path = Path(token_path)
        self.request_timeout = request_timeout
        self.actor_timeout = actor_timeout

    def token(self) -> str | None:
        environment_token = os.getenv("APIFY_API_TOKEN", "").strip()
        if environment_token:
            return environment_token
        try:
            saved_token = self.token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return saved_token or None

    def has_token(self) -> bool:
        return bool(self.token())

    def save_token(self, value: str) -> None:
        token = value.strip()
        if len(token) < 12 or any(character.isspace() for character in token):
            raise TikTokFreeError("Token Apify tidak terlihat valid.")
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(token, encoding="utf-8")
            self.token_path.chmod(0o600)
        except OSError as exc:
            raise TikTokFreeError("Token Apify tidak dapat disimpan di komputer ini.") from exc

    def delete_token(self) -> None:
        try:
            self.token_path.unlink(missing_ok=True)
        except OSError as exc:
            raise TikTokFreeError("Token Apify tidak dapat dihapus dari komputer ini.") from exc

    @staticmethod
    def _is_tiktok_host(url: str) -> bool:
        hostname = (urlparse(url).hostname or "").casefold()
        return hostname == "tiktok.com" or hostname.endswith(".tiktok.com")

    def _resolve_post_url(self, url: str) -> str:
        """Resolve vm/vt short links without opening the final video page."""
        current = validate_public_url(url, resolve_dns=False)
        if not self._is_tiktok_host(current):
            raise TikTokFreeError("URL bukan berasal dari TikTok.")
        if TikTokConnector._video_id(current):
            return current
        hostname = (urlparse(current).hostname or "").casefold()
        if hostname not in {"vm.tiktok.com", "vt.tiktok.com"}:
            return current

        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = requests.get(
                    current,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                    timeout=self.request_timeout,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise TikTokFreeError("Short URL TikTok belum dapat diarahkan ke video aslinya.") from exc

            is_redirect = response.is_redirect or response.is_permanent_redirect
            target = response.headers.get("location") if is_redirect else None
            response.close()
            if not target:
                raise TikTokFreeError("Short URL TikTok tidak memberikan tujuan posting yang valid.")
            current = urljoin(current, target)
            validate_public_url(current, resolve_dns=False)
            if not self._is_tiktok_host(current):
                raise TikTokFreeError("Short URL TikTok mengarah ke situs yang tidak dikenal.")
            if TikTokConnector._video_id(current):
                return current

        raise TikTokFreeError("Short URL TikTok melewati terlalu banyak pengalihan.")

    @staticmethod
    def _integer(mapping: dict[str, Any], *keys: str) -> int | None:
        return TikTokConnector._mapping_count(mapping, *keys)

    @staticmethod
    def _author_meta(item: dict[str, Any]) -> dict[str, Any]:
        author = item.get("authorMeta")
        if isinstance(author, dict):
            return author
        return {
            key.removeprefix("authorMeta."): value
            for key, value in item.items()
            if key.startswith("authorMeta.")
        }

    @classmethod
    def _metrics_from_apify_item(
        cls,
        item: dict[str, Any],
        video_id: str | None,
    ) -> TikTokBrowserMetrics:
        item_url = str(item.get("webVideoUrl") or item.get("url") or "")
        item_video_id = str(item.get("id") or "") or (TikTokConnector._video_id(item_url) or "")
        if not item_video_id or (video_id and item_video_id != video_id):
            return TikTokBrowserMetrics(source="free")

        author = cls._author_meta(item)
        posted_at = None
        for key in ("createTimeISO", "createTime", "create_time", "datePublished"):
            value = item.get(key)
            if value in (None, ""):
                continue
            try:
                posted_at = social_datetime_iso(value)
            except (TypeError, ValueError, OverflowError, OSError):
                posted_at = None
            if posted_at:
                break

        return TikTokBrowserMetrics(
            username=TikTokFreeCollector._clean_username(
                author.get("name")
                or author.get("uniqueId")
                or author.get("unique_id")
                or item.get("authorUniqueId")
            ),
            caption=TikTokConnector._caption_value(
                item.get("text") or item.get("desc") or item.get("description")
            ),
            posted_at=posted_at,
            followers=cls._integer(author, "fans", "followerCount", "follower_count", "followersCount"),
            views=cls._integer(item, "playCount", "play_count", "viewCount", "view_count"),
            likes=cls._integer(item, "diggCount", "digg_count", "likeCount", "like_count"),
            comments=cls._integer(item, "commentCount", "comment_count"),
            shares=cls._integer(item, "shareCount", "share_count"),
            bookmarks=cls._integer(
                item,
                "collectCount",
                "collect_count",
                "favoriteCount",
                "bookmarkCount",
            ),
            source="free",
        )

    @staticmethod
    def _clean_username(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip().lstrip("@")
        return cleaned or None

    def _oembed_metrics(self, url: str) -> TikTokBrowserMetrics:
        try:
            response = requests.get(
                TIKTOK_OEMBED_ENDPOINT,
                params={"url": url},
                headers={"Accept": "application/json"},
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return TikTokBrowserMetrics(
                source="free",
                warning="Metadata publik TikTok belum dapat dibaca. Coba lagi nanti.",
            )
        if not isinstance(payload, dict):
            return TikTokBrowserMetrics(source="free")
        return TikTokBrowserMetrics(
            username=self._clean_username(
                payload.get("author_unique_id") or payload.get("author_name")
            ),
            caption=TikTokConnector._caption_value(payload.get("title")),
            source="free",
        )

    def _apify_metrics(self, url: str, token: str) -> TikTokBrowserMetrics:
        video_id = TikTokConnector._video_id(url)
        hostname = (urlparse(url).hostname or "").casefold()
        if not video_id and hostname not in {"vm.tiktok.com", "vt.tiktok.com"}:
            raise TikTokFreeError("ID video TikTok tidak dapat dibaca dari URL.")
        run_input = {
            "postURLs": [url],
            "resultsPerPage": 1,
            "scrapeRelatedVideos": False,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
            "shouldDownloadSlideshowImages": False,
            "shouldDownloadAvatars": False,
            "shouldDownloadMusicCovers": False,
            "downloadSubtitlesOptions": "NEVER_DOWNLOAD_SUBTITLES",
            "commentsPerPost": 0,
            "topLevelCommentsPerPost": 0,
            "maxRepliesPerComment": 0,
            "maxFollowersPerProfile": 0,
            "maxFollowingPerProfile": 0,
            "proxyCountryCode": "None",
        }
        try:
            response = requests.post(
                APIFY_ACTOR_ENDPOINT,
                params={"clean": "true"},
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=run_input,
                timeout=self.actor_timeout,
            )
        except requests.Timeout as exc:
            raise TikTokFreeError("Layanan gratis TikTok terlalu lama merespons.") from exc
        except requests.RequestException as exc:
            raise TikTokFreeError("Layanan gratis TikTok belum dapat dihubungi.") from exc

        if response.status_code in {401, 403}:
            raise TikTokFreeError("Token Apify ditolak. Simpan token yang benar lalu coba lagi.")
        if response.status_code == 402:
            raise TikTokFreeError("Kredit gratis Apify sudah habis untuk periode ini.")
        if response.status_code == 429:
            raise TikTokFreeError("Layanan gratis sedang membatasi proses. Coba lagi beberapa saat.")
        try:
            response.raise_for_status()
            items = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TikTokFreeError("Layanan gratis TikTok mengembalikan hasil yang tidak dapat dibaca.") from exc
        if not isinstance(items, list):
            raise TikTokFreeError("Layanan gratis TikTok tidak mengembalikan daftar hasil.")

        for item in items:
            if not isinstance(item, dict):
                continue
            metrics = self._metrics_from_apify_item(item, video_id)
            if any(
                getattr(metrics, name) is not None
                for name in ("caption", "views", "likes", "comments", "shares", "followers")
            ):
                return metrics
        error_item = next(
            (item for item in items if isinstance(item, dict) and (item.get("errorCode") or item.get("error"))),
            None,
        )
        if error_item:
            error_code = str(error_item.get("errorCode") or "").casefold()
            if "private" in error_code or "not_found" in error_code:
                raise TikTokFreeError("Video TikTok tidak ditemukan, bersifat privat, atau tidak lagi tersedia.")
        raise TikTokFreeError("Views dan followers belum tersedia dari layanan gratis untuk URL ini.")

    @classmethod
    def _metrics_from_public_item(
        cls,
        item: dict[str, Any],
        video_id: str | None,
    ) -> TikTokBrowserMetrics:
        item_id = str(item.get("id") or item.get("aweme_id") or item.get("video_id") or "")
        if not item_id or (video_id and item_id != video_id):
            return TikTokBrowserMetrics(source="free")

        author = item.get("author")
        if not isinstance(author, dict):
            author = {}
        posted_at = None
        for key in ("create_time", "createTime", "datePublished"):
            value = item.get(key)
            if value in (None, ""):
                continue
            try:
                posted_at = social_datetime_iso(value)
            except (TypeError, ValueError, OverflowError, OSError):
                posted_at = None
            if posted_at:
                break

        return TikTokBrowserMetrics(
            username=cls._clean_username(
                author.get("unique_id")
                or author.get("uniqueId")
                or item.get("authorUniqueId")
            ),
            caption=TikTokConnector._caption_value(
                item.get("title")
                or item.get("content_desc")
                or item.get("desc")
                or item.get("description")
            ),
            posted_at=posted_at,
            views=cls._integer(item, "play_count", "playCount", "view_count", "viewCount"),
            likes=cls._integer(item, "digg_count", "diggCount", "like_count", "likeCount"),
            comments=cls._integer(item, "comment_count", "commentCount"),
            shares=cls._integer(item, "share_count", "shareCount"),
            bookmarks=cls._integer(item, "collect_count", "collectCount", "bookmarkCount"),
            source="free",
        )

    def _public_fallback_metrics(self, url: str) -> TikTokBrowserMetrics:
        video_id = TikTokConnector._video_id(url)
        if not video_id:
            raise TikTokFreeError("ID posting TikTok tidak dapat dibaca dari URL.")

        payload: Any = None
        for attempt in range(2):
            try:
                # The public endpoint accepts one request per second. Serializing
                # calls keeps multi-platform enrichment from dropping later rows.
                with self._fallback_lock:
                    wait_for = 1.05 - (time.monotonic() - type(self)._last_fallback_request)
                    if wait_for > 0:
                        time.sleep(wait_for)
                    response = requests.get(
                        TIKTOK_PUBLIC_FALLBACK_ENDPOINT,
                        params={"url": url, "hd": "0"},
                        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                        timeout=self.request_timeout,
                    )
                    type(self)._last_fallback_request = time.monotonic()
                response.raise_for_status()
                payload = response.json()
            except requests.Timeout as exc:
                raise TikTokFreeError("Layanan cadangan TikTok terlalu lama merespons.") from exc
            except (requests.RequestException, ValueError) as exc:
                raise TikTokFreeError("Layanan cadangan TikTok belum dapat dihubungi.") from exc

            message = str(payload.get("msg") or payload.get("message") or "") if isinstance(payload, dict) else ""
            if isinstance(payload, dict) and payload.get("code") == -1 and "1 request/second" in message:
                if attempt == 0:
                    continue
                raise TikTokFreeError("Layanan cadangan TikTok sedang membatasi permintaan.")
            break

        if not isinstance(payload, dict) or payload.get("code") not in (0, "0"):
            raise TikTokFreeError("Posting TikTok belum dapat dibaca oleh layanan cadangan.")
        item = payload.get("data")
        if not isinstance(item, dict):
            raise TikTokFreeError("Layanan cadangan TikTok tidak mengembalikan data posting.")
        metrics = self._metrics_from_public_item(item, video_id)
        if not self._has_data(metrics):
            raise TikTokFreeError("Hasil layanan cadangan tidak cocok dengan URL TikTok target.")
        return metrics

    @staticmethod
    def _has_data(metrics: TikTokBrowserMetrics) -> bool:
        return any(
            getattr(metrics, name) is not None
            for name in (
                "username",
                "caption",
                "posted_at",
                "views",
                "likes",
                "comments",
                "shares",
                "bookmarks",
                "followers",
            )
        )

    @staticmethod
    def _needs_post_fallback(metrics: TikTokBrowserMetrics) -> bool:
        return any(
            getattr(metrics, name) is None
            for name in ("caption", "posted_at", "views", "likes", "comments", "shares", "bookmarks")
        )

    @staticmethod
    def _public_profile_followers(username: str | None) -> int | None:
        if not username:
            return None
        return TikTokConnector()._followers_from_profile(f"https://www.tiktok.com/@{username}")

    @staticmethod
    def _merge(
        preferred: TikTokBrowserMetrics,
        fallback: TikTokBrowserMetrics,
    ) -> TikTokBrowserMetrics:
        values: dict[str, Any] = {}
        for name in TikTokBrowserMetrics.__dataclass_fields__:
            value = getattr(preferred, name)
            values[name] = value if value not in (None, "") else getattr(fallback, name)
        return TikTokBrowserMetrics(**values)

    def collect(self, url: str) -> TikTokBrowserMetrics:
        resolved_url = url
        resolve_warning = None
        try:
            resolved_url = self._resolve_post_url(url)
        except TikTokFreeError as exc:
            # Apify can still resolve many TikTok short URLs on its side.
            resolve_warning = str(exc)

        public = self._oembed_metrics(resolved_url)
        token = self.token()
        provider = TikTokBrowserMetrics(source="free")
        provider_errors: list[str] = []
        if token:
            try:
                provider = self._apify_metrics(resolved_url, token)
            except TikTokFreeError as exc:
                provider_errors.append(str(exc))

        if not token or self._needs_post_fallback(provider):
            try:
                fallback = self._public_fallback_metrics(resolved_url)
                provider = self._merge(provider, fallback)
            except TikTokFreeError as exc:
                provider_errors.append(str(exc))

        if not self._has_data(provider):
            if self._has_data(public):
                warning = " ".join(dict.fromkeys(provider_errors))
                if resolve_warning:
                    warning = f"{resolve_warning} {warning}".strip()
                public.warning = warning or public.warning
                return public
            reason = " ".join(dict.fromkeys(provider_errors))
            if resolve_warning:
                reason = f"{resolve_warning} {reason}".strip()
            raise TikTokFreeError(reason or "URL TikTok tidak dapat diproses.")

        combined = self._merge(provider, public)
        if combined.followers is None:
            combined.followers = self._public_profile_followers(combined.username)
        combined.source = "free"
        combined.warning = provider.warning
        return combined
