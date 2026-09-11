"""Instagram enrichment through a dedicated, user-authenticated Chrome profile."""
from __future__ import annotations

import json
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
from src.connectors.instagram import InstagramConnector
from src.dates import social_datetime_iso
from src.models import DataField, FieldStatus, SocialResult


INSTAGRAM_PROFILE_DIR = DATA_DIR / "browser_profiles" / "instagram"


class InstagramBrowserError(RuntimeError):
    pass


class InstagramLoginRequired(InstagramBrowserError):
    pass


@dataclass
class InstagramBrowserMetrics:
    username: str | None = None
    caption: str | None = None
    posted_at: str | None = None
    followers: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    reposts: int | None = None
    views_applicable: bool | None = None


def apply_instagram_browser_metrics(
    result: SocialResult,
    metrics: InstagramBrowserMetrics,
    mode: str = "advanced",
) -> SocialResult:
    """Replace public fallbacks with values displayed by the logged-in browser."""
    if mode == "fast":
        # Keep the fast contract explicit: these profile-level values were not
        # collected, even if a public fallback happened to expose one.
        result.followers = DataField(value=None, status=FieldStatus.NOT_SUPPORTED)
        result.views = DataField(value=None, status=FieldStatus.NOT_SUPPORTED)
    if metrics.username:
        result.username = DataField(value=metrics.username, status=FieldStatus.AVAILABLE)
    if metrics.caption:
        result.caption = DataField(value=metrics.caption, status=FieldStatus.AVAILABLE)
    if metrics.posted_at:
        result.posted_at = DataField(value=metrics.posted_at, status=FieldStatus.AVAILABLE)
    if metrics.followers is not None:
        result.followers = DataField(value=metrics.followers, status=FieldStatus.AVAILABLE)
    if metrics.views is not None:
        result.views = DataField(value=metrics.views, status=FieldStatus.AVAILABLE)
    if metrics.likes is not None:
        result.likes = DataField(value=metrics.likes, status=FieldStatus.AVAILABLE)
    if metrics.comments is not None:
        result.comments = DataField(value=metrics.comments, status=FieldStatus.AVAILABLE)
    if metrics.shares is not None:
        result.shares = DataField(value=metrics.shares, status=FieldStatus.AVAILABLE)
    if metrics.reposts is not None:
        result.reposts = DataField(value=metrics.reposts, status=FieldStatus.AVAILABLE)
    browser_note = (
        "Instagram diperiksa dengan Fast enrichment melalui halaman posting di browser MIDETA yang sudah login."
        if mode == "fast"
        else (
            "Instagram diperiksa dengan Advanced enrichment melalui posting dan profil di browser MIDETA yang sudah login; "
            "Views hanya diisi ketika tersedia untuk video/Reels."
        )
    )
    result.note = f"{result.note} {browser_note}".strip() if result.note else browser_note
    return result


def build_instagram_browser_result(
    url: str,
    metrics: InstagramBrowserMetrics,
    mode: str = "advanced",
) -> SocialResult:
    """Build an Instagram result using only the authenticated post response."""
    result = SocialResult(
        url=url,
        platform="Instagram",
        username=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        caption=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        posted_at=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        followers=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        likes=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        comments=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        shares=DataField(value=None, status=FieldStatus.NOT_SUPPORTED),
        views=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
        bookmarks=DataField(value=None, status=FieldStatus.NOT_SUPPORTED),
        reposts=DataField(value=None, status=FieldStatus.NOT_PUBLIC),
    )
    return apply_instagram_browser_metrics(result, metrics, mode=mode)


class InstagramBrowserCollector:
    def __init__(
        self,
        profile_dir: Path = INSTAGRAM_PROFILE_DIR,
        wait_seconds: int = 20,
        headless: bool = False,
    ):
        self.profile_dir = Path(profile_dir)
        self.wait_seconds = wait_seconds
        self.headless = headless
        self.driver = None
        self._followers_cache: dict[str, tuple[float, int]] = {}

    @staticmethod
    def _shortcode(url: str) -> str | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part.casefold() in {"p", "reel", "reels"}:
                return parts[index + 1]
        return None

    @staticmethod
    def _username(value: str | None) -> str | None:
        username = (value or "").strip().lstrip("@")
        return username if re.fullmatch(r"[A-Za-z0-9._]+", username) else None

    @staticmethod
    def _count(value: str) -> int | None:
        match = re.search(r"(?<!\w)(\d[\d.,]*\s*(?:k|m|b)?)(?!\w)", value, re.I)
        return BaseConnector._human_count(match.group(1)) if match else None

    @classmethod
    def _labeled_count(cls, text: str, *labels: str) -> int | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(
            rf"(\d[\d.,]*\s*(?:k|m|b)?)\s+(?:{label_pattern})\b",
            text,
            re.I,
        )
        return BaseConnector._human_count(match.group(1)) if match else None

    @classmethod
    def _target_username(cls, source: str, shortcode: str) -> str | None:
        soup = BeautifulSoup(source, "lxml")
        for payload in BaseConnector._embedded_json(soup):
            for node in BaseConnector._walk(payload):
                post = node.get("post") if isinstance(node.get("post"), dict) else node
                code = post.get("code") or post.get("shortcode")
                if str(code or "").casefold() != shortcode.casefold():
                    continue
                user = post.get("user")
                if isinstance(user, dict):
                    username = cls._username(user.get("username"))
                    if username:
                        return username
                username = cls._username(post.get("username"))
                if username:
                    return username
        return None

    @classmethod
    def _post_metadata(cls, source: str, url: str, shortcode: str) -> InstagramBrowserMetrics:
        soup = BeautifulSoup(source, "lxml")
        description = BaseConnector._meta(
            soup,
            'meta[property="og:description"]',
            'meta[name="description"]',
        )
        author = BaseConnector._meta(
            soup,
            'meta[name="author"]',
            'meta[property="profile:username"]',
        )
        author = cls._username(author) or cls._target_username(source, shortcode)
        if not author and description:
            author_match = re.search(
                r"-\s*([A-Za-z0-9._]+)\s+on\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}\s*:",
                description,
                re.I,
            )
            author = cls._username(author_match.group(1)) if author_match else None

        connector = InstagramConnector()
        caption = connector._platform_caption(source, url, description)
        posted_at = connector._platform_posted_at(source, soup, url, None)
        likes = cls._target_metric(source, shortcode, "like_count", "likes_count")
        comments = cls._target_metric(
            source,
            shortcode,
            "comment_count",
            "comments_count",
            "total_comment_count",
        )
        shares = cls._target_metric(source, shortcode, "share_count", "shares_count")
        if description:
            if likes is None:
                likes = cls._labeled_count(description, "like", "likes")
            if comments is None:
                comments = cls._labeled_count(description, "comment", "comments")
            if shares is None:
                shares = cls._labeled_count(description, "share", "shares")
        return InstagramBrowserMetrics(
            username=author,
            caption=caption,
            posted_at=posted_at,
            likes=likes,
            comments=comments,
            shares=shares,
        )

    def _username_from_dom(self) -> str | None:
        try:
            links = self.driver.find_elements(By.XPATH, "//article//a[@href] | //main//a[@href]")
        except WebDriverException:
            return None
        reserved = {"accounts", "direct", "explore", "p", "reel", "reels", "stories"}
        for link in links:
            try:
                href = str(link.get_attribute("href") or "")
            except WebDriverException:
                continue
            parts = [part for part in urlparse(href).path.split("/") if part]
            if len(parts) != 1 or parts[0].casefold() in reserved:
                continue
            username = self._username(parts[0])
            if username:
                return username
        return None

    @classmethod
    def _target_metric(cls, source: str, shortcode: str, *keys: str) -> int | None:
        code_matches = list(
            re.finditer(
                rf'"(?:code|shortcode|media_code)"\s*:\s*"{re.escape(shortcode)}"',
                source,
                re.I,
            )
        )
        if not code_matches:
            return None
        key_pattern = "|".join(re.escape(key) for key in keys)
        values: list[tuple[int, int]] = []
        for metric in re.finditer(
            rf'"(?:{key_pattern})"\s*:\s*(?:\{{[^{{}}]{{0,240}}?"(?:count|total_count)"\s*:\s*)?"?([\d.,]+\s*(?:k|m|b)?)',
            source,
            re.I,
        ):
            nearest = min(code_matches, key=lambda code: abs(code.start() - metric.start()))
            distance = abs(nearest.start() - metric.start())
            if distance > 40_000:
                continue
            between = source[min(nearest.start(), metric.start()):max(nearest.start(), metric.start())]
            if re.search(r"}\s*,\s*{", between):
                continue
            count = BaseConnector._human_count(metric.group(1))
            if count is not None:
                values.append((distance, count))
        return min(values, key=lambda item: item[0])[1] if values else None

    @staticmethod
    def _target_media_pk(source: str, shortcode: str) -> str | None:
        """Find the numeric media ID that belongs to one shortcode."""
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        if shortcode and all(character in alphabet for character in shortcode):
            media_pk = 0
            for character in shortcode:
                media_pk = media_pk * 64 + alphabet.index(character)
            return str(media_pk)
        code_matches = list(
            re.finditer(
                rf'"(?:code|shortcode|media_code)"\s*:\s*"{re.escape(shortcode)}"',
                source,
                re.I,
            )
        )
        if not code_matches:
            return None
        pk_matches = list(re.finditer(r'"(?:pk|media_id)"\s*:\s*"?(\d+)"?', source, re.I))
        candidates: list[tuple[int, int, str]] = []
        for code in code_matches:
            for pk in pk_matches:
                distance = abs(code.start() - pk.start())
                if distance <= 8_000:
                    candidates.append((0 if pk.start() < code.start() else 1, distance, pk.group(1)))
        return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None

    @classmethod
    def _media_info_metrics(cls, source: str) -> tuple[int | None, int | None]:
        """Read reposts and views from the response for one exact media ID."""
        metrics = cls._media_info_engagement(source)
        return metrics.reposts, metrics.views

    @classmethod
    def _media_info_engagement(cls, source: str) -> InstagramBrowserMetrics:
        """Read exact engagement values from Instagram's authenticated media response."""
        try:
            payload = json.loads(source)
        except (json.JSONDecodeError, TypeError):
            payload = None
        items = payload.get("items") if isinstance(payload, dict) else None
        item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
        if item is not None:
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            caption = item.get("caption") if isinstance(item.get("caption"), dict) else {}
            posted_at = None
            taken_at = item.get("taken_at")
            try:
                if taken_at is not None:
                    posted_at = social_datetime_iso(taken_at)
            except (TypeError, ValueError, OverflowError, OSError):
                posted_at = None
            media_type = item.get("media_type")
            product_type = str(item.get("product_type") or "").casefold()
            views_applicable = media_type == 2 or product_type in {"clips", "reel", "reels"}
            return InstagramBrowserMetrics(
                username=cls._username(user.get("username")),
                caption=str(caption.get("text") or "").strip() or None,
                posted_at=posted_at,
                reposts=cls._mapping_count(
                    item,
                    "media_repost_count",
                    "repost_count",
                    "reposts_count",
                    "reshare_count",
                    "reshares_count",
                    "repost_count_reduced",
                    "reshare_count_reduced",
                ),
                views=cls._mapping_count(
                    item,
                    "play_count",
                    "view_count",
                    "video_view_count",
                    "ig_play_count",
                ),
                likes=cls._mapping_count(item, "like_count", "likes_count"),
                comments=cls._mapping_count(
                    item,
                    "comment_count",
                    "comments_count",
                    "total_comment_count",
                ),
                shares=cls._mapping_count(item, "share_count", "shares_count"),
                views_applicable=views_applicable,
            )
        return InstagramBrowserMetrics(
            reposts=cls._target_metric_from_exact_media(
                source,
                "media_repost_count",
                "repost_count",
                "reposts_count",
                "reshare_count",
                "reshares_count",
                "repost_count_reduced",
                "reshare_count_reduced",
            ),
            views=cls._target_metric_from_exact_media(
                source,
                "play_count",
                "view_count",
                "video_view_count",
                "ig_play_count",
            ),
            likes=cls._target_metric_from_exact_media(source, "like_count", "likes_count"),
            comments=cls._target_metric_from_exact_media(
                source,
                "comment_count",
                "comments_count",
                "total_comment_count",
            ),
            shares=cls._target_metric_from_exact_media(source, "share_count", "shares_count"),
        )

    @staticmethod
    def _mapping_count(item: dict, *keys: str) -> int | None:
        for key in keys:
            value = item.get(key)
            if isinstance(value, dict):
                value = value.get("count", value.get("total_count"))
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                return int(value)
            count = BaseConnector._human_count(str(value))
            if count is not None:
                return count
        return None

    @classmethod
    def _profile_info_followers(cls, source: str) -> int | None:
        try:
            payload = json.loads(source)
        except (json.JSONDecodeError, TypeError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            return None
        return cls._mapping_count(user, "follower_count", "followers_count", "edge_followed_by")

    @classmethod
    def _profile_page_followers(cls, source: str, username: str) -> int | None:
        """Read followers only from the requested profile's page payload."""
        exact = cls._profile_info_followers(source)
        if exact is not None:
            return exact
        wanted = username.casefold()
        soup = BeautifulSoup(source, "lxml")
        for payload in BaseConnector._embedded_json(soup):
            for node in BaseConnector._walk(payload):
                candidates = [node]
                if isinstance(node.get("user"), dict):
                    candidates.append(node["user"])
                for candidate in candidates:
                    candidate_username = cls._username(candidate.get("username"))
                    if not candidate_username or candidate_username.casefold() != wanted:
                        continue
                    followers = cls._mapping_count(
                        candidate,
                        "follower_count",
                        "followers_count",
                        "edge_followed_by",
                    )
                    if followers is not None:
                        return followers
        descriptions = (
            BaseConnector._meta(soup, 'meta[property="og:description"]'),
            BaseConnector._meta(soup, 'meta[name="description"]'),
        )
        for description in descriptions:
            if not description or wanted not in description.casefold():
                continue
            followers = cls._labeled_count(description, "follower", "followers")
            if followers is not None:
                return followers
        return None

    @staticmethod
    def _target_metric_from_exact_media(source: str, *keys: str) -> int | None:
        for key in keys:
            match = re.search(
                rf'"{re.escape(key)}"\s*:\s*(?:\{{[^{{}}]{{0,240}}?"(?:count|total_count)"\s*:\s*)?"?([\d.,]+\s*(?:k|m|b)?)',
                source,
                re.I,
            )
            if match:
                count = BaseConnector._human_count(match.group(1))
                if count is not None:
                    return count
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
            raise InstagramBrowserError(
                "Chrome MIDETA tidak dapat dibuka. Tutup jendela Chrome MIDETA yang lama, lalu coba lagi."
            ) from exc
        return self.driver

    def open_login(self) -> None:
        driver = self.start()
        driver.get("https://www.instagram.com/accounts/login/")

    def is_logged_in(self) -> bool:
        driver = self.start()
        try:
            if "/accounts/login" in (driver.current_url or ""):
                return False
            cookies = driver.get_cookies()
        except WebDriverException:
            return False
        return any(cookie.get("name") == "sessionid" and cookie.get("value") for cookie in cookies)

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
        time.sleep(1.2)

    def _body_text(self) -> str:
        try:
            return self.driver.find_element(By.TAG_NAME, "body").text
        except WebDriverException:
            return ""

    def _metric_by_icon(self, label: str) -> int | None:
        xpath = (
            "//*[name()='svg' and contains("
            "translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), "
            f"'{label.casefold()}')]"
        )
        icons = self.driver.find_elements(By.XPATH, xpath)
        found_icon = False
        for icon in icons:
            try:
                if not icon.is_displayed():
                    continue
                found_icon = True
                value = self.driver.execute_script(
                    r"""
                    const icon = arguments[0];
                    const box = icon.getBoundingClientRect();
                    const centerY = box.top + box.height / 2;
                    const countPattern = /^\s*\d[\d.,]*\s*[KMB]?\s*$/i;
                    let best = null;
                    for (const node of document.querySelectorAll('span, a, button, div')) {
                      if (node === icon || node.children.length > 0) continue;
                      const text = (node.innerText || '').trim();
                      if (!countPattern.test(text)) continue;
                      const rect = node.getBoundingClientRect();
                      if (!rect.width || !rect.height) continue;
                      const dx = rect.left - box.right;
                      const dy = Math.abs((rect.top + rect.height / 2) - centerY);
                      if (dx < -4 || dx > 120 || dy > 24) continue;
                      const score = dx + dy * 5;
                      if (!best || score < best.score) best = {score, text};
                    }
                    return best ? best.text : null;
                    """,
                    icon,
                )
                if value:
                    count = self._count(str(value))
                    if count is not None:
                        return count
            except WebDriverException:
                continue
        return 0 if found_icon else None

    def _authenticated_media_metrics(self, source: str, shortcode: str) -> InstagramBrowserMetrics:
        media_pk = self._target_media_pk(source, shortcode)
        if not media_pk:
            return InstagramBrowserMetrics()
        try:
            self.driver.set_script_timeout(self.wait_seconds)
            response = self.driver.execute_async_script(
                """
                const mediaPk = arguments[0];
                const done = arguments[arguments.length - 1];
                fetch(`/api/v1/media/${mediaPk}/info/`, {
                  credentials: 'include',
                  headers: {
                    'X-IG-App-ID': '936619743392459',
                    'X-Requested-With': 'XMLHttpRequest'
                  }
                })
                  .then(async response => done({status: response.status, text: await response.text()}))
                  .catch(() => done({status: 0, text: ''}));
                """,
                media_pk,
            )
        except WebDriverException:
            return InstagramBrowserMetrics()
        if not isinstance(response, dict) or int(response.get("status") or 0) != 200:
            return InstagramBrowserMetrics()
        return self._media_info_engagement(str(response.get("text") or ""))

    def _authenticated_profile_followers(self, username: str) -> int | None:
        try:
            self.driver.set_script_timeout(self.wait_seconds)
            response = self.driver.execute_async_script(
                """
                const username = arguments[0];
                const done = arguments[arguments.length - 1];
                const query = encodeURIComponent(username);
                fetch(`/api/v1/users/web_profile_info/?username=${query}`, {
                  credentials: 'include',
                  headers: {
                    'X-IG-App-ID': '936619743392459',
                    'X-Requested-With': 'XMLHttpRequest'
                  }
                })
                  .then(async response => done({status: response.status, text: await response.text()}))
                  .catch(() => done({status: 0, text: ''}));
                """,
                username,
            )
        except WebDriverException:
            return None
        if not isinstance(response, dict) or int(response.get("status") or 0) != 200:
            return None
        return self._profile_info_followers(str(response.get("text") or ""))

    def _post_metrics(self, url: str, shortcode: str) -> InstagramBrowserMetrics:
        driver = self.start()
        driver.get(url)
        self._wait_for_page()
        if not self.is_logged_in():
            raise InstagramLoginRequired("Login Instagram belum selesai di Chrome MIDETA.")
        source = driver.page_source
        body = self._body_text()
        metadata = self._post_metadata(source, url, shortcode)
        if not metadata.username:
            metadata.username = self._username_from_dom()
        api_metrics = self._authenticated_media_metrics(source, shortcode)
        if api_metrics.username:
            metadata.username = api_metrics.username
        if api_metrics.caption:
            metadata.caption = api_metrics.caption
        if api_metrics.posted_at:
            metadata.posted_at = api_metrics.posted_at
        if api_metrics.likes is not None:
            metadata.likes = api_metrics.likes
        if api_metrics.comments is not None:
            metadata.comments = api_metrics.comments
        if api_metrics.shares is not None:
            metadata.shares = api_metrics.shares
        reposts = api_metrics.reposts
        if reposts is None:
            reposts = self._target_metric(
                source,
                shortcode,
                "repost_count",
                "reposts_count",
                "reshare_count",
                "reshares_count",
                "repost_count_reduced",
                "reshare_count_reduced",
            )
        if reposts is None:
            reposts = self._metric_by_icon("repost")
        if reposts is None:
            reposts = self._labeled_count(body, "repost", "reposts", "reshare", "reshares")
        views = api_metrics.views
        if views is None:
            views = self._target_metric(source, shortcode, "play_count", "view_count", "video_view_count")
        if views is None:
            views = self._labeled_count(body, "view", "views", "play", "plays")
        if metadata.likes is None:
            metadata.likes = self._metric_by_icon("like")
        if metadata.comments is None:
            metadata.comments = self._metric_by_icon("comment")
        if metadata.shares is None:
            metadata.shares = self._labeled_count(body, "share", "shares")
        metadata.reposts = reposts
        metadata.views = views
        metadata.views_applicable = api_metrics.views_applicable
        return metadata

    def _profile_metrics(
        self,
        username: str,
        shortcode: str,
        find_views: bool = True,
    ) -> tuple[int | None, int | None]:
        cache_key = username.casefold()
        cached = self._followers_cache.get(cache_key)
        cached_followers = None
        if cached and time.monotonic() - cached[0] <= 300:
            cached_followers = cached[1]
        if not find_views and cached_followers is not None:
            return cached_followers, None

        driver = self.start()
        profile_path = "reels/" if find_views else ""
        driver.get(f"https://www.instagram.com/{username}/{profile_path}")
        self._wait_for_page()
        body = self._body_text()
        profile_source = driver.page_source
        exact_followers = self._authenticated_profile_followers(username)
        followers = exact_followers
        if followers is None:
            followers = self._profile_page_followers(profile_source, username)
        if followers is None:
            followers = self._labeled_count(body, "follower", "followers")
        if followers is None:
            public_source = InstagramConnector()._public_profile_html(
                f"https://www.instagram.com/{username}/"
            )
            if public_source:
                followers = self._profile_page_followers(public_source, username)
                if followers is None:
                    public_soup = BeautifulSoup(public_source, "lxml")
                    public_text = " ".join(
                        filter(
                            None,
                            (
                                public_soup.get_text(" ", strip=True),
                                BaseConnector._meta(public_soup, 'meta[property="og:description"]'),
                                BaseConnector._meta(public_soup, 'meta[name="description"]'),
                            ),
                        )
                    )
                    followers = self._labeled_count(public_text, "follower", "followers")
        if followers is None:
            followers = cached_followers
        if followers is not None:
            self._followers_cache[cache_key] = (time.monotonic(), followers)
        views = None
        if not find_views:
            return followers, views
        unchanged_rounds = 0
        previous_height = -1
        for _ in range(25):
            anchors = driver.find_elements(
                By.XPATH,
                f"//a[contains(@href, '/reel/{shortcode}') or contains(@href, '/p/{shortcode}') or contains(@href, '/{shortcode}/')]",
            )
            for anchor in anchors:
                try:
                    text = " ".join(
                        value
                        for value in (
                            anchor.text,
                            anchor.get_attribute("aria-label"),
                            anchor.get_attribute("title"),
                        )
                        if value
                    )
                except WebDriverException:
                    continue
                count = self._labeled_count(text, "view", "views", "play", "plays") or self._count(text)
                if count is not None:
                    views = count
                    break
            if views is not None:
                break
            source_view = self._target_metric(driver.page_source, shortcode, "play_count", "view_count", "video_view_count")
            if source_view is not None:
                views = source_view
                break
            current_height = int(driver.execute_script("return document.body.scrollHeight") or 0)
            if current_height == previous_height:
                unchanged_rounds += 1
                if unchanged_rounds >= 3:
                    break
            else:
                unchanged_rounds = 0
            previous_height = current_height
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.7)
        return followers, views

    def collect(
        self,
        url: str,
        author: str | None,
        mode: str = "advanced",
    ) -> InstagramBrowserMetrics:
        if mode not in {"fast", "advanced"}:
            raise InstagramBrowserError("Mode enrichment Instagram tidak dikenal.")
        if not self.is_logged_in():
            raise InstagramLoginRequired(
                "Instagram belum login. Tekan Buka Chrome Instagram, selesaikan login, lalu periksa kembali."
            )
        shortcode = self._shortcode(url)
        if not shortcode:
            raise InstagramBrowserError("Shortcode posting Instagram tidak dapat dibaca dari URL.")
        post_metrics = self._post_metrics(url, shortcode)
        username = post_metrics.username or self._username(author)
        if not username:
            raise InstagramBrowserError("Username Instagram tidak ditemukan pada halaman posting.")
        post_metrics.username = username
        if mode == "fast":
            # Fast mode intentionally avoids profile/Reels. Even when a view
            # happens to be present in the post response, keep this mode's
            # output limited to engagement selected by the user.
            post_metrics.followers = None
            post_metrics.views = None
            return post_metrics
        followers, grid_views = self._profile_metrics(
            username,
            shortcode,
            find_views=(
                post_metrics.views is None
                and post_metrics.views_applicable is not False
            ),
        )
        post_metrics.followers = followers
        if grid_views is not None:
            post_metrics.views = grid_views
        return post_metrics
