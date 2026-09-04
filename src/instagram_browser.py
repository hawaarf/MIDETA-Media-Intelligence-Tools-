"""Instagram enrichment through a dedicated, user-authenticated Chrome profile."""
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
from src.connectors.instagram import InstagramConnector
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
    reposts: int | None = None


def apply_instagram_browser_metrics(
    result: SocialResult,
    metrics: InstagramBrowserMetrics,
) -> SocialResult:
    """Replace public fallbacks with values displayed by the logged-in browser."""
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
    if metrics.reposts is not None:
        result.reposts = DataField(value=metrics.reposts, status=FieldStatus.AVAILABLE)
    browser_note = "Metadata Instagram diperiksa melalui browser MIDETA yang sudah login."
    result.note = f"{result.note} {browser_note}".strip() if result.note else browser_note
    return result


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
        if description:
            if likes is None:
                likes = cls._labeled_count(description, "like", "likes")
            if comments is None:
                comments = cls._labeled_count(description, "comment", "comments")
        return InstagramBrowserMetrics(
            username=author,
            caption=caption,
            posted_at=posted_at,
            likes=likes,
            comments=comments,
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
        reposts = cls._target_metric_from_exact_media(
            source,
            "media_repost_count",
            "repost_count",
            "reposts_count",
            "reshare_count",
            "reshares_count",
            "repost_count_reduced",
            "reshare_count_reduced",
        )
        views = cls._target_metric_from_exact_media(
            source,
            "play_count",
            "view_count",
            "video_view_count",
            "ig_play_count",
        )
        return reposts, views

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

    def _authenticated_media_metrics(self, source: str, shortcode: str) -> tuple[int | None, int | None]:
        media_pk = self._target_media_pk(source, shortcode)
        if not media_pk:
            return None, None
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
            return None, None
        if not isinstance(response, dict) or int(response.get("status") or 0) != 200:
            return None, None
        return self._media_info_metrics(str(response.get("text") or ""))

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
        api_reposts, api_views = self._authenticated_media_metrics(source, shortcode)
        reposts = api_reposts
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
        views = api_views
        if views is None:
            views = self._target_metric(source, shortcode, "play_count", "view_count", "video_view_count")
        if views is None:
            views = self._labeled_count(body, "view", "views", "play", "plays")
        if metadata.likes is None:
            metadata.likes = self._metric_by_icon("like")
        if metadata.comments is None:
            metadata.comments = self._metric_by_icon("comment")
        metadata.reposts = reposts
        metadata.views = views
        return metadata

    def _profile_metrics(
        self,
        username: str,
        shortcode: str,
        find_views: bool = True,
    ) -> tuple[int | None, int | None]:
        driver = self.start()
        driver.get(f"https://www.instagram.com/{username}/reels/")
        self._wait_for_page()
        body = self._body_text()
        followers = self._labeled_count(body, "follower", "followers")
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

    def collect(self, url: str, author: str | None) -> InstagramBrowserMetrics:
        if not self.is_logged_in():
            raise InstagramLoginRequired(
                "Instagram belum login. Tekan Buka Chrome Instagram, selesaikan login, lalu periksa kembali."
            )
        shortcode = self._shortcode(url)
        if not shortcode:
            raise InstagramBrowserError("Shortcode posting Instagram tidak dapat dibaca dari URL.")
        post_metrics = self._post_metrics(url, shortcode)
        username = self._username(author) or post_metrics.username
        if not username:
            raise InstagramBrowserError("Username Instagram tidak ditemukan pada halaman posting.")
        followers, grid_views = self._profile_metrics(
            username,
            shortcode,
            find_views=post_metrics.views is None,
        )
        post_metrics.username = username
        post_metrics.followers = followers
        if grid_views is not None:
            post_metrics.views = grid_views
        return post_metrics
