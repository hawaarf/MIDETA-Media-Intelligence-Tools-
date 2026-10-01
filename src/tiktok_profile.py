# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""No-login TikTok profile post discovery with date-range filtering."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import re
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from src.config import MAX_PROFILE_POSTS, REQUEST_TIMEOUT_SECONDS


TIKTOK_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{2,64}$")
JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
PROFILE_PAGE_SIZE = 35
OLDER_POST_STOP_COUNT = 20
SEC_UID_RE = re.compile(r'"secUid"\s*:\s*"([A-Za-z0-9_-]+)"')


class TikTokProfileScrapeError(RuntimeError):
    """Raised when a public TikTok profile cannot be enumerated safely."""


@dataclass(slots=True)
class TikTokProfileScrapeResult:
    username: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    pages_scanned: int = 0
    posts_scanned: int = 0
    undated_posts: int = 0
    complete: bool = False
    reached_start_date: bool = False
    oldest_matching_date: date | None = None
    newest_before_start_date: date | None = None
    warning: str = ""


def parse_tiktok_profile(value: str) -> str:
    """Return a TikTok username from a profile URL, ``@handle``, or handle."""
    raw = str(value or "").strip()
    if not raw:
        raise TikTokProfileScrapeError("Masukkan URL profil atau username TikTok.")

    if "://" not in raw and "/" not in raw:
        username = raw.lstrip("@").strip()
    else:
        candidate = raw if "://" in raw else f"https://{raw}"
        parsed = urlparse(candidate)
        hostname = (parsed.hostname or "").casefold()
        if hostname != "tiktok.com" and not hostname.endswith(".tiktok.com"):
            raise TikTokProfileScrapeError("URL harus berasal dari profil TikTok.")
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) != 1 or not parts[0].startswith("@"):
            raise TikTokProfileScrapeError(
                "Gunakan URL profil seperti https://www.tiktok.com/@username, bukan URL posting."
            )
        username = parts[0].lstrip("@").strip()

    if not TIKTOK_USERNAME_RE.fullmatch(username):
        raise TikTokProfileScrapeError("Username TikTok tidak terlihat valid.")
    return username


def canonical_profile_url(username: str) -> str:
    return f"https://www.tiktok.com/@{username}"


def _sec_uid_from_html(source: str) -> str:
    """Read TikTok's public pagination identifier from profile source."""
    match = SEC_UID_RE.search(str(source or ""))
    return match.group(1) if match else ""


def _mapping_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _post_datetime(item: dict[str, Any]) -> datetime | None:
    raw = _mapping_value(item, "timestamp", "create_time", "createTime", "upload_date")
    if raw in (None, ""):
        return None
    try:
        text = str(raw).strip()
        if isinstance(raw, (int, float)) or text.isdigit():
            if len(text) == 8 and text.startswith(("19", "20")):
                return datetime.strptime(text, "%Y%m%d").replace(tzinfo=JAKARTA_TZ)
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).astimezone(JAKARTA_TZ)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(JAKARTA_TZ)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _post_id(item: dict[str, Any]) -> str:
    value = _mapping_value(item, "id", "aweme_id", "video_id", "item_id")
    return str(value or "").strip()


def _author_username(item: dict[str, Any], fallback: str) -> str:
    # yt-dlp's ``uploader_id``/``channel_id`` can be an internal numeric ID,
    # not the public @handle. Prefer the handle embedded in the post URL and
    # otherwise keep the profile username supplied by the user.
    candidate = str(
        _mapping_value(item, "webpage_url", "url", "original_url") or ""
    ).strip()
    if candidate:
        parts = [unquote(part) for part in urlparse(candidate).path.split("/") if part]
        if parts and parts[0].startswith("@"):
            cleaned = parts[0].lstrip("@").strip()
            if TIKTOK_USERNAME_RE.fullmatch(cleaned):
                return cleaned
    return fallback


def _entry_post_type(item: dict[str, Any]) -> str:
    candidate = str(
        _mapping_value(item, "webpage_url", "url", "original_url") or ""
    ).casefold()
    return "Photo" if "/photo/" in candidate else "Video"


def _post_caption(item: dict[str, Any]) -> str:
    """Return the full public caption, preferring description over title."""
    value = _mapping_value(item, "description", "desc", "caption", "title", "fulltitle")
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _QuietLogger:
    """Keep yt-dlp diagnostics inside MIDETA instead of flooding Terminal."""

    def debug(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass

    def error(self, _message: str) -> None:
        pass


class TikTokProfileCollector:
    """Enumerate public profile posts directly from TikTok with local yt-dlp."""

    def __init__(
        self,
        *,
        max_posts: int = MAX_PROFILE_POSTS,
        request_timeout: int = REQUEST_TIMEOUT_SECONDS,
        entry_provider: Callable[[str], Iterable[dict[str, Any]]] | None = None,
    ):
        self.max_posts = min(max(1, int(max_posts)), MAX_PROFILE_POSTS)
        self.request_timeout = request_timeout
        self.entry_provider = entry_provider

    def _public_sec_uid(self, username: str) -> str:
        """Resolve a public profile ID when TikTok withholds it from yt-dlp.

        TikTok serves different profile HTML to different browser families. Its
        iOS Safari response still contains the public ``secUid`` required by the
        official creator-item pagination endpoint. No cookies, login, or stored
        credentials are used here.
        """
        try:
            from curl_cffi import requests

            response = requests.get(
                f"{canonical_profile_url(username)}?is_from_webapp=1&sender_device=pc",
                impersonate="safari_ios",
                timeout=self.request_timeout,
                headers={
                    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "https://www.google.com/",
                },
            )
            if response.status_code != 200:
                return ""
            return _sec_uid_from_html(response.text)
        except Exception:
            return ""

    def _extract_profile_info(self, target: str) -> dict[str, Any]:
        """Open one lazy yt-dlp profile playlist without downloading media."""
        import yt_dlp
        from yt_dlp.networking.impersonate import ImpersonateTarget

        options = {
            "extract_flat": True,
            "skip_download": True,
            "lazy_playlist": True,
            "playlistend": self.max_posts,
            "socket_timeout": self.request_timeout,
            "quiet": True,
            "no_warnings": True,
            "logger": _QuietLogger(),
            # curl-cffi lets yt-dlp make a browser-compatible public request
            # without launching Chrome or importing cookies/login credentials.
            "impersonate": ImpersonateTarget("chrome"),
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(target, download=False)
        return info if isinstance(info, dict) else {}

    def _profile_entries(self, username: str) -> Iterable[dict[str, Any]]:
        """Yield flat TikTok post entries lazily so old ranges can stop early."""
        if self.entry_provider is not None:
            return self.entry_provider(username)
        try:
            from yt_dlp.utils import DownloadError
        except ImportError as exc:
            raise TikTokProfileScrapeError(
                "Dependency Profile Scraping belum terpasang. Jalankan pip install -r requirements.txt."
            ) from exc

        try:
            info = self._extract_profile_info(canonical_profile_url(username))
        except DownloadError as exc:
            message = str(exc).casefold()
            if "unable to extract secondary user id" in message:
                sec_uid = self._public_sec_uid(username)
                if sec_uid:
                    try:
                        info = self._extract_profile_info(f"tiktokuser:{sec_uid}")
                    except DownloadError as fallback_exc:
                        raise TikTokProfileScrapeError(
                            "TikTok sedang membatasi daftar posting publik. Coba lagi beberapa saat."
                        ) from fallback_exc
                else:
                    raise TikTokProfileScrapeError(
                        "Profil ditemukan, tetapi TikTok belum memberikan akses ke daftar posting publik. "
                        "Coba lagi beberapa saat."
                    ) from exc
            elif "not found" in message:
                raise TikTokProfileScrapeError(
                    "Profil TikTok tidak ditemukan atau username sudah berubah."
                ) from exc
            else:
                raise TikTokProfileScrapeError(
                    "TikTok sedang membatasi permintaan publik. Coba lagi beberapa saat."
                ) from exc

        entries = info.get("entries") if isinstance(info, dict) else None
        if entries is None:
            raise TikTokProfileScrapeError(
                "Profil TikTok tidak mengembalikan daftar posting publik."
            )
        return entries

    def collect(
        self,
        profile: str,
        start_date: date,
        end_date: date,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> TikTokProfileScrapeResult:
        if start_date > end_date:
            raise TikTokProfileScrapeError("Tanggal awal tidak boleh melewati tanggal akhir.")

        username = parse_tiktok_profile(profile)
        result = TikTokProfileScrapeResult(username=username)
        seen_posts: set[str] = set()
        rows_by_date: list[tuple[datetime, dict[str, Any]]] = []
        timeline_started = False
        consecutive_older = 0
        stopped_after_range = False

        try:
            entries = self._profile_entries(username)
            for item in entries:
                if not isinstance(item, dict):
                    continue
                post_id = _post_id(item)
                if not post_id or post_id in seen_posts:
                    continue
                seen_posts.add(post_id)
                result.posts_scanned += 1
                result.pages_scanned = max(
                    1, (result.posts_scanned + PROFILE_PAGE_SIZE - 1) // PROFILE_PAGE_SIZE
                )
                posted_at = _post_datetime(item)
                if posted_at is None:
                    result.undated_posts += 1
                else:
                    posted_date = posted_at.date()
                    if posted_date >= start_date:
                        timeline_started = True
                        consecutive_older = 0
                    elif timeline_started:
                        consecutive_older += 1
                        if result.newest_before_start_date is None:
                            result.newest_before_start_date = posted_date

                    if start_date <= posted_date <= end_date:
                        author = _author_username(item, username)
                        post_type = _entry_post_type(item)
                        path_type = "photo" if post_type == "Photo" else "video"
                        rows_by_date.append(
                            (
                                posted_at,
                                {
                                    "Date Publish": posted_date.isoformat(),
                                    "Author": author,
                                    "Post Type": post_type,
                                    "Caption": _post_caption(item),
                                    "URL": f"https://www.tiktok.com/@{author}/{path_type}/{post_id}",
                                },
                            )
                        )

                if progress_callback and (
                    result.posts_scanned == 1 or result.posts_scanned % 25 == 0
                ):
                    progress_callback(
                        {
                            "pages_scanned": result.pages_scanned,
                            "posts_scanned": result.posts_scanned,
                            "matched": len(rows_by_date),
                            "oldest_date": posted_at.date() if posted_at else None,
                        }
                    )

                if consecutive_older >= OLDER_POST_STOP_COUNT:
                    result.reached_start_date = True
                    stopped_after_range = True
                    break
                if result.posts_scanned >= self.max_posts:
                    break
        except TikTokProfileScrapeError:
            raise
        except Exception as exc:
            raise TikTokProfileScrapeError(
                "Daftar posting TikTok terputus sebelum proses selesai. Coba lagi beberapa saat."
            ) from exc

        result.complete = stopped_after_range or result.posts_scanned < self.max_posts
        if result.posts_scanned >= self.max_posts and not stopped_after_range:
            result.warning = (
                f"Batas aman {self.max_posts:,} posting tercapai sebelum seluruh rentang selesai."
            )

        rows_by_date.sort(key=lambda item: item[0], reverse=True)
        if rows_by_date:
            result.oldest_matching_date = rows_by_date[-1][0].date()
        result.rows = [
            {
                "No": index,
                "Date Publish": row["Date Publish"],
                "Author": row["Author"],
                "Post Type": row["Post Type"],
                "Caption": row["Caption"],
                "URL": row["URL"],
            }
            for index, (_, row) in enumerate(rows_by_date, 1)
        ]
        if result.undated_posts:
            extra = f"{result.undated_posts:,} posting tanpa tanggal dilewati."
            result.warning = f"{result.warning} {extra}".strip()
        return result
