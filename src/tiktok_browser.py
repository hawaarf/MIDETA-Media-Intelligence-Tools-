"""TikTok enrichment through a dedicated, user-authenticated Chrome profile."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from src.config import DATA_DIR
from src.connectors.base import BaseConnector
from src.connectors.tiktok import TikTokConnector
from src.dates import social_datetime_iso
from src.models import DataField, FieldStatus, SocialResult


TIKTOK_PROFILE_DIR = DATA_DIR / "browser_profiles" / "tiktok"


class TikTokBrowserError(RuntimeError):
    pass


class TikTokLoginRequired(TikTokBrowserError):
    pass


@dataclass
class TikTokBrowserMetrics:
    username: str | None = None
    caption: str | None = None
    posted_at: str | None = None
    followers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    bookmarks: int | None = None


def build_tiktok_browser_result(url: str, metrics: TikTokBrowserMetrics) -> SocialResult:
    result = SocialResult(
        url=url,
        platform="TikTok",
        username=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        caption=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        posted_at=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        followers=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        likes=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        comments=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        shares=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        views=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        bookmarks=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        reposts=DataField(value=None, status=FieldStatus.NOT_SUPPORTED),
        note=(
            "TikTok diperiksa melalui video dan profil author di browser MIDETA yang sudah login. "
            "Setiap engagement dicocokkan dengan ID video target."
        ),
    )
    for name in (
        "username",
        "caption",
        "posted_at",
        "followers",
        "likes",
        "comments",
        "shares",
        "views",
        "bookmarks",
    ):
        value = getattr(metrics, name)
        if value is not None and value != "":
            setattr(result, name, DataField(value=value, status=FieldStatus.AVAILABLE))
    return result


class TikTokBrowserCollector:
    def __init__(
        self,
        profile_dir: Path = TIKTOK_PROFILE_DIR,
        wait_seconds: int = 20,
        headless: bool = False,
    ):
        self.profile_dir = Path(profile_dir)
        self.wait_seconds = wait_seconds
        self.headless = headless
        self.driver = None
        self._followers_cache: dict[str, tuple[float, int]] = {}

    @staticmethod
    def _username(value: str | None) -> str | None:
        username = (value or "").strip().lstrip("@")
        return username if re.fullmatch(r"[A-Za-z0-9._]+", username) else None

    @classmethod
    def _username_from_url(cls, url: str) -> str | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        return next((cls._username(part) for part in parts if part.startswith("@")), None)

    @staticmethod
    def _count(value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"(?<!\w)(\d[\d.,]*\s*(?:k|m|b)?)(?!\w)", value, re.I)
        return BaseConnector._human_count(match.group(1)) if match else None

    @classmethod
    def _video_metrics_from_source(cls, source: str, video_id: str) -> TikTokBrowserMetrics:
        node = TikTokConnector._target_video_item(source, video_id)
        if node is None:
            return TikTokBrowserMetrics()
        stats = node.get("stats") if isinstance(node.get("stats"), dict) else {}
        stats_v2 = node.get("statsV2") if isinstance(node.get("statsV2"), dict) else {}
        author = node.get("author") if isinstance(node.get("author"), dict) else {}
        caption = TikTokConnector._target_caption_from_json(source, video_id)
        posted_at = None
        for key in ("createTime", "create_time", "publishTime", "publish_time", "datePublished"):
            if node.get(key) is None:
                continue
            try:
                posted_at = social_datetime_iso(node.get(key))
            except (TypeError, ValueError, OverflowError, OSError):
                posted_at = None
            if posted_at:
                break

        def metric(*keys: str) -> int | None:
            value = TikTokConnector._mapping_count(stats, *keys) if stats else None
            return value if value is not None else (
                TikTokConnector._mapping_count(stats_v2, *keys) if stats_v2 else None
            )

        return TikTokBrowserMetrics(
            username=cls._username(author.get("uniqueId") or author.get("unique_id") or author.get("username")),
            caption=caption,
            posted_at=posted_at,
            views=metric("playCount", "play_count", "viewCount", "view_count"),
            likes=metric("diggCount", "digg_count", "likeCount", "like_count"),
            comments=metric("commentCount", "comment_count"),
            shares=metric("shareCount", "share_count"),
            bookmarks=metric("collectCount", "collect_count", "favoriteCount", "bookmarkCount"),
        )

    @classmethod
    def _profile_followers_from_source(cls, source: str, username: str) -> int | None:
        wanted = username.casefold()
        soup = BeautifulSoup(source, "lxml")
        for payload in BaseConnector._embedded_json(soup):
            for node in BaseConnector._walk(payload):
                candidates = [node]
                for key in ("user", "author", "userInfo"):
                    if isinstance(node.get(key), dict):
                        candidates.append(node[key])
                for candidate in candidates:
                    identity = cls._username(
                        candidate.get("uniqueId")
                        or candidate.get("unique_id")
                        or candidate.get("username")
                    )
                    if not identity or identity.casefold() != wanted:
                        continue
                    metric_sources = [candidate, node]
                    for key in ("stats", "authorStats", "userStats"):
                        if isinstance(candidate.get(key), dict):
                            metric_sources.append(candidate[key])
                        if isinstance(node.get(key), dict):
                            metric_sources.append(node[key])
                    for metrics in metric_sources:
                        followers = TikTokConnector._mapping_count(
                            metrics,
                            "followerCount",
                            "follower_count",
                            "followersCount",
                        )
                        if followers is not None:
                            return followers
        return None

    def is_running(self) -> bool:
        if self.driver is None:
            return False
        try:
            return bool(self.driver.window_handles)
        except (InvalidSessionIdException, NoSuchWindowException, WebDriverException):
            self.driver = None
            return False

    def start(self):
        if self.is_running():
            return self.driver
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={self.profile_dir.resolve()}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        if self.headless:
            options.add_argument("--headless=new")
        options.page_load_strategy = "eager"
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(self.wait_seconds + 10)
        except WebDriverException as exc:
            self.driver = None
            raise TikTokBrowserError(
                "Chrome TikTok MIDETA tidak dapat dibuka. Tutup jendela Chrome TikTok MIDETA yang lama, lalu coba lagi."
            ) from exc
        return self.driver

    def open_login(self) -> None:
        self.start().get("https://www.tiktok.com/login")

    def is_logged_in(self) -> bool:
        driver = self.start()
        try:
            if "/login" in str(driver.current_url or "").casefold():
                return False
            cookies = driver.get_cookies()
        except WebDriverException:
            return False
        session_names = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard"}
        return any(cookie.get("name") in session_names and cookie.get("value") for cookie in cookies)

    def close(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.quit()
        except WebDriverException:
            pass
        finally:
            self.driver = None

    def _wait_for_page(self) -> None:
        driver = self.start()
        WebDriverWait(driver, self.wait_seconds).until(
            lambda active: active.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        time.sleep(1.5)

    def _dom_text(self, selectors: tuple[str, ...]) -> str | None:
        try:
            value = self.driver.execute_script(
                """
                for (const selector of arguments[0]) {
                  const node = document.querySelector(selector);
                  if (!node) continue;
                  const text = (node.textContent || node.innerText || node.getAttribute('aria-label') || '').trim();
                  if (text) return text;
                }
                return null;
                """,
                list(selectors),
            )
        except WebDriverException:
            return None
        return str(value).strip() if value else None

    def _post_dom_metrics(self) -> TikTokBrowserMetrics:
        caption = self._dom_text(
            (
                '[data-e2e="browse-video-desc"]',
                'h1[data-e2e="browse-video-desc"]',
                '[data-e2e="video-desc"]',
            )
        )
        if caption:
            caption = re.sub(r"\s+(?:more|less|selengkapnya|lainnya)\s*$", "", caption, flags=re.I).strip()
        selectors = {
            "likes": ('strong[data-e2e="like-count"]', '[data-e2e="browse-like-count"]'),
            "comments": ('strong[data-e2e="comment-count"]', '[data-e2e="browse-comment-count"]'),
            "shares": ('strong[data-e2e="share-count"]', '[data-e2e="browse-share-count"]'),
            "bookmarks": ('strong[data-e2e="favorite-count"]', '[data-e2e="bookmark-count"]'),
            "views": ('strong[data-e2e="video-views"]', '[data-e2e="video-views"]'),
        }
        values = {name: self._count(self._dom_text(query)) for name, query in selectors.items()}
        return TikTokBrowserMetrics(caption=caption, **values)

    @staticmethod
    def _merge(preferred: TikTokBrowserMetrics, fallback: TikTokBrowserMetrics) -> TikTokBrowserMetrics:
        values = {}
        for name in TikTokBrowserMetrics.__dataclass_fields__:
            value = getattr(preferred, name)
            values[name] = value if value is not None and value != "" else getattr(fallback, name)
        return TikTokBrowserMetrics(**values)

    def _post_metrics(self, url: str, video_id: str) -> TikTokBrowserMetrics:
        driver = self.start()
        driver.get(url)
        self._wait_for_page()
        if not self.is_logged_in():
            raise TikTokLoginRequired("Login TikTok belum selesai di Chrome MIDETA.")
        current_url = str(driver.current_url or "")
        if "/login" in current_url.casefold():
            raise TikTokLoginRequired("TikTok mengalihkan halaman ke login. Login kembali lalu lanjutkan proses.")
        try:
            WebDriverWait(driver, self.wait_seconds).until(
                lambda active: (
                    TikTokConnector._target_video_item(active.page_source, video_id) is not None
                    or bool(active.find_elements(By.CSS_SELECTOR, '[data-e2e="browse-video-desc"]'))
                )
            )
        except WebDriverException:
            pass
        source_metrics = self._video_metrics_from_source(driver.page_source, video_id)
        dom_metrics = self._post_dom_metrics()
        metrics = self._merge(source_metrics, dom_metrics)
        if not metrics.caption:
            metrics.caption = TikTokConnector()._platform_caption(driver.page_source, url, None)
        return metrics

    def _profile_video_views_from_dom(self, video_id: str) -> int | None:
        try:
            value = self.driver.execute_script(
                """
                const videoId = arguments[0];
                const links = [...document.querySelectorAll('a[href]')]
                  .filter(link => (link.getAttribute('href') || '').includes(`/video/${videoId}`));
                for (const link of links) {
                  const card = link.closest('[data-e2e="user-post-item"]') || link;
                  const count = card.querySelector('[data-e2e="video-views"], strong, span');
                  if (!count) continue;
                  const text = (count.textContent || count.innerText || '').trim();
                  if (text) return text;
                }
                return null;
                """,
                video_id,
            )
        except WebDriverException:
            return None
        return self._count(str(value)) if value else None

    def _profile_metrics(self, username: str, video_id: str) -> tuple[int | None, int | None]:
        cache_key = username.casefold()
        cached = self._followers_cache.get(cache_key)
        followers = cached[1] if cached and time.monotonic() - cached[0] <= 300 else None
        driver = self.start()
        driver.get(f"https://www.tiktok.com/@{username}")
        self._wait_for_page()
        if not self.is_logged_in():
            raise TikTokLoginRequired("Sesi TikTok berakhir saat membuka profil author.")
        try:
            WebDriverWait(driver, self.wait_seconds).until(
                lambda active: (
                    self._profile_followers_from_source(active.page_source, username) is not None
                    or bool(active.find_elements(By.CSS_SELECTOR, '[data-e2e="followers-count"]'))
                )
            )
        except WebDriverException:
            pass
        source = driver.page_source
        followers = followers if followers is not None else self._profile_followers_from_source(source, username)
        if followers is None:
            followers = self._count(
                self._dom_text(('strong[data-e2e="followers-count"]', '[data-e2e="followers-count"]'))
            )
        if followers is not None:
            self._followers_cache[cache_key] = (time.monotonic(), followers)
        video = self._video_metrics_from_source(source, video_id)
        views = video.views if video.views is not None else self._profile_video_views_from_dom(video_id)
        return followers, views

    def collect(self, url: str, author: str | None = None, mode: str = "advanced") -> TikTokBrowserMetrics:
        del mode
        if not self.is_logged_in():
            raise TikTokLoginRequired("TikTok belum login di Chrome MIDETA.")
        video_id = TikTokConnector._video_id(url)
        if not video_id:
            raise TikTokBrowserError("ID video TikTok tidak dapat dibaca dari URL.")
        url_username = self._username_from_url(url)
        post = self._post_metrics(url, video_id)
        post.username = post.username or url_username or self._username(author)
        if not post.username:
            raise TikTokBrowserError("Username TikTok tidak dapat dibaca dari URL atau halaman video.")
        post.followers, profile_views = self._profile_metrics(post.username, video_id)
        if post.views is None:
            post.views = profile_views
        return post
