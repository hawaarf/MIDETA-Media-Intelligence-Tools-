"""Comment collection through a dedicated Chrome profile."""
from __future__ import annotations

import atexit
import json
import re
import time
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait

from src.config import DATA_DIR, MAX_COMMENTS_PER_URL
from src.connectors import get_platform_connector
from src.connectors.base import BaseConnector
from src.dates import relative_social_date_iso, social_date_iso
from src.models import CommentCollection, DataField, FieldStatus, PublicComment, SocialResult


class CommentBrowserError(RuntimeError):
    pass


class CommentBrowserLoginRequired(CommentBrowserError):
    pass


class CommentBrowserCollector:
    RUNTIME_VERSION = 22
    THREADS_MAX_SCROLL_ROUNDS = 240
    FACEBOOK_MAX_SCROLL_ROUNDS = 240
    X_MAX_SCROLL_ROUNDS = 240
    X_IDLE_STABLE_ROUNDS = 16
    OTHER_MAX_SCROLL_ROUNDS = 30
    END_STABLE_ROUNDS = 3
    IDLE_STABLE_ROUNDS = 8
    LOGIN_URLS = {
        "Facebook": "https://www.facebook.com/login/",
        "Threads": "https://www.threads.com/login/",
        "X": "https://x.com/i/flow/login",
    }
    HOME_URLS = {
        "Facebook": "https://www.facebook.com/",
        "Threads": "https://www.threads.com/",
        "X": "https://x.com/home",
    }
    LOGIN_COOKIES = {
        "Facebook": {"c_user"},
        "Threads": {"sessionid", "ds_user_id"},
        "X": {"auth_token"},
    }
    PLATFORM_HOSTS = {
        "Facebook": "facebook.com",
        "Threads": "threads.com",
        "X": "x.com",
    }

    def __init__(
        self,
        platform: str,
        profile_dir: Path | None = None,
        wait_seconds: int = 20,
        headless: bool = False,
    ):
        if platform not in self.LOGIN_URLS:
            raise ValueError("Browser komentar hanya tersedia untuk Facebook, Threads, dan X.")
        self.platform = platform
        self.profile_dir = Path(profile_dir or DATA_DIR / "browser_profiles" / platform.casefold())
        self.wait_seconds = wait_seconds
        self.headless = headless
        self.driver = None
        self._threads_followers_cache: dict[str, tuple[float, str]] = {}
        self._x_response_capture_ready = False
        atexit.register(self.close)

    @staticmethod
    def _count(value) -> int:
        if value in (None, ""):
            return 0
        match = re.search(r"\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?", str(value), re.I)
        return BaseConnector._human_count(match.group(0)) if match else 0

    @staticmethod
    def _clean_facebook_author(value) -> tuple[str, str]:
        """Separate a Facebook relative timestamp accidentally wrapped by the author link."""
        text = re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()
        match = re.search(
            r"\s+(just now|baru saja|yesterday|kemarin|(?:\d+\s*|se)"
            r"(?:sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours|"
            r"d|day|days|w|wk|wks|week|weeks|detik|menit|jam|hari|minggu)"
            r"(?:\s+(?:ago|lalu|yang lalu))?)$",
            text,
            re.I,
        )
        if not match:
            return text, ""
        return text[: match.start()].strip(), match.group(1).strip()

    def is_running(self) -> bool:
        if self.driver is None:
            return False
        try:
            handles = self.driver.window_handles
            if not handles:
                self._discard_driver()
                return False
            try:
                current_handle = self.driver.current_window_handle
            except (InvalidSessionIdException, NoSuchWindowException, WebDriverException):
                current_handle = None
            if current_handle not in handles:
                self.driver.switch_to.window(handles[-1])
            return True
        except (InvalidSessionIdException, NoSuchWindowException, WebDriverException):
            self._discard_driver()
            return False

    def _discard_driver(self) -> None:
        """Forget a dead Chrome session so the next action can start cleanly."""
        driver, self.driver = self.driver, None
        if driver is None:
            return
        try:
            driver.quit()
        except WebDriverException:
            pass

    @staticmethod
    def _session_was_lost(exc: WebDriverException) -> bool:
        if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException)):
            return True
        message = str(exc).casefold()
        return any(
            marker in message
            for marker in (
                "no such window",
                "target window already closed",
                "web view not found",
                "invalid session id",
                "session deleted",
                "disconnected",
                "not connected to devtools",
            )
        )

    def start(self):
        if self.is_running():
            return self.driver
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        debugger_file = self.profile_dir / "DevToolsActivePort"
        if debugger_file.exists():
            try:
                port = debugger_file.read_text(encoding="utf-8").splitlines()[0].strip()
                if port.isdigit():
                    attach_options = webdriver.ChromeOptions()
                    attach_options.debugger_address = f"127.0.0.1:{port}"
                    self.driver = webdriver.Chrome(options=attach_options)
                    self.driver.set_page_load_timeout(self.wait_seconds + 10)
                    return self.driver
            except (OSError, IndexError, WebDriverException):
                self.driver = None
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
            raise CommentBrowserError(
                f"Chrome MIDETA untuk {self.platform} tidak dapat dibuka. Tutup jendela lama, lalu coba lagi."
            ) from exc
        return self.driver

    @staticmethod
    def _threads_permalink(driver, fallback_url: str) -> str:
        # A permalink supplied by the user is authoritative.  Never replace it
        # with the first post link rendered by Threads (which can be a
        # recommendation rather than the requested conversation).
        if re.search(r"/@[^/]+/post/[^/?#]+", str(fallback_url or ""), re.I):
            return str(fallback_url).split("#", 1)[0].rstrip("/")
        current_url = str(getattr(driver, "current_url", "") or fallback_url)
        if re.search(r"/@[^/]+/post/[^/?#]+", current_url, re.I):
            return current_url.split("#", 1)[0].rstrip("/")
        try:
            candidates = driver.execute_script(
                r"""
                const canonical = document.querySelector('link[rel="canonical"]')?.href || '';
                const openGraph = document.querySelector('meta[property="og:url"]')?.content || '';
                return [window.location.href || '', canonical, openGraph];
                """
            )
        except WebDriverException:
            candidates = []
        if isinstance(candidates, (list, tuple)):
            return next(
                (
                    str(candidate).split("#", 1)[0].rstrip("/")
                    for candidate in candidates[:3]
                    if re.search(r"/@[^/]+/post/[^/?#]+", str(candidate or ""), re.I)
                ),
                current_url,
            )
        return current_url

    def _resolve_threads_permalink(self, driver, fallback_url: str) -> str:
        """Wait for a Threads share URL to expose its own canonical post."""
        if re.search(r"/@[^/]+/post/[^/?#]+", str(fallback_url or ""), re.I):
            return self._threads_permalink(driver, fallback_url)
        resolved = ""
        try:
            resolved = WebDriverWait(driver, min(self.wait_seconds, 10)).until(
                lambda active: (
                    candidate
                    if re.search(r"/@[^/]+/post/[^/?#]+", candidate, re.I)
                    else False
                )
                if (candidate := self._threads_permalink(active, fallback_url))
                else False
            )
        except WebDriverException:
            pass
        return str(resolved or self._threads_permalink(driver, fallback_url))

    @staticmethod
    def _threads_detail_url(url: str) -> str:
        """Use the permalink route that exposes the post header and its views."""
        base = str(url or "").split("#", 1)[0].rstrip("/")
        return f"{base}#/" if re.search(r"/@[^/]+/post/[^/?#]+", base, re.I) else str(url)

    @staticmethod
    def _open_threads_target_card(driver, target_code: str) -> bool:
        if not target_code:
            return False
        try:
            return bool(
                driver.execute_script(
                    r"""
                    const wanted = String(arguments[0] || '').toLowerCase();
                    const link = Array.from(document.querySelectorAll('a[href*="/post/"]')).find(node => {
                      const href = String(node.href || node.getAttribute('href') || '').toLowerCase();
                      return href.includes(`/post/${wanted}`);
                    });
                    if (!link) return false;
                    link.scrollIntoView({block: 'center', inline: 'nearest'});
                    link.click();
                    return true;
                    """,
                    target_code,
                )
            )
        except WebDriverException:
            return False

    def _activate_threads_target(self, driver, permalink: str, target_code: str) -> str:
        """Open the exact Threads card and return only its active permalink."""
        def active_permalink(active) -> str | bool:
            value = str(getattr(active, "current_url", "") or "")
            match = re.search(r"/@[^/]+/post/([^/?#]+)", value, re.I)
            if match and match.group(1).casefold() == target_code.casefold():
                return value.split("#", 1)[0].rstrip("/")
            return False

        active = active_permalink(driver)
        if active:
            return str(active)

        # Threads sometimes turns a valid post route into its home page with
        # injected_media_ids. The exact post card remains present there, so
        # open that card by shortcode instead of accepting another feed item.
        if self._open_threads_target_card(driver, target_code):
            try:
                return str(WebDriverWait(driver, min(self.wait_seconds, 8)).until(active_permalink))
            except WebDriverException:
                pass

        driver.get(self._threads_detail_url(permalink))
        self._wait_for_page()
        active = active_permalink(driver)
        if active:
            return str(active)
        if self._open_threads_target_card(driver, target_code):
            try:
                return str(WebDriverWait(driver, min(self.wait_seconds, 8)).until(active_permalink))
            except WebDriverException:
                pass

        # The shortcode-only route can expose the requested card even when a
        # copied username in the permalink is stale or misspelled.
        driver.get(f"https://www.threads.com/t/{target_code}")
        self._wait_for_page()
        if self._open_threads_target_card(driver, target_code):
            try:
                return str(WebDriverWait(driver, min(self.wait_seconds, 8)).until(active_permalink))
            except WebDriverException:
                pass
        return ""

    def collect_threads_enrichment(self, url: str):
        """Collect one exact Threads post from the saved browser session."""
        if self.platform != "Threads":
            raise CommentBrowserError("Fallback enrichment ini hanya tersedia untuk Threads.")
        try:
            return self._collect_threads_enrichment_once(url)
        except WebDriverException as exc:
            if self._session_was_lost(exc):
                self._discard_driver()
                try:
                    return self._collect_threads_enrichment_once(url)
                except WebDriverException as retry_exc:
                    self._discard_driver()
                    raise CommentBrowserError(
                        "Chrome MIDETA untuk Threads terputus. Jalankan URL ini sekali lagi."
                    ) from retry_exc
            raise CommentBrowserError(
                "Chrome MIDETA untuk Threads tidak dapat membaca posting ini."
            ) from exc

    def collect_facebook_enrichment(self, url: str) -> SocialResult:
        """Collect one exact Facebook post plus profile-level views/followers."""
        if self.platform != "Facebook":
            raise CommentBrowserError("Advanced enrichment ini hanya tersedia untuk Facebook.")
        if not self.is_logged_in(open_platform=False):
            raise CommentBrowserLoginRequired(
                "Facebook belum login. Buka Chrome Facebook, selesaikan login, lalu tekan Periksa Login."
            )
        try:
            return self._collect_facebook_enrichment_once(url)
        except WebDriverException as exc:
            if self._session_was_lost(exc):
                self._discard_driver()
                raise CommentBrowserLoginRequired(
                    "Sesi Chrome Facebook terputus. Buka Chrome Facebook dan periksa login sebelum melanjutkan."
                ) from exc
            raise CommentBrowserError(
                "Chrome MIDETA untuk Facebook tidak dapat membaca posting ini. Pastikan posting terlihat, lalu coba lagi."
            ) from exc

    @staticmethod
    def _same_facebook_target(expected_url: str, candidate_url: str) -> bool:
        """Reject a stale/recommended Facebook post when the target ID is known."""
        connector = get_platform_connector(expected_url, "Facebook")
        expected_ids = set(connector._post_identifiers(expected_url))
        if not expected_ids:
            return True
        candidate_ids = set(connector._post_identifiers(candidate_url))
        return bool(expected_ids & candidate_ids)

    @classmethod
    def _facebook_permalink(cls, driver, fallback_url: str) -> str:
        post_pattern = re.compile(
            r"facebook\.com/(?:reel/|watch(?:/|\?)|[^/?#]+/(?:posts|videos|photos|reels)/|groups/[^/?#]+/(?:posts|permalink)/|(?:permalink|story|photo)\.php)",
            re.I,
        )

        def target_permalink(active):
            current_url = str(getattr(active, "current_url", "") or "")
            try:
                candidates = active.execute_script(
                    r"""
                    const canonical = document.querySelector('link[rel="canonical"]')?.href || '';
                    const openGraph = document.querySelector('meta[property="og:url"]')?.content || '';
                    return [window.location.href || '', canonical, openGraph];
                    """
                )
            except WebDriverException:
                candidates = []
            if not isinstance(candidates, (list, tuple)):
                candidates = []
            for candidate in [current_url, *candidates]:
                value = str(candidate or "").strip()
                if post_pattern.search(value) and cls._same_facebook_target(fallback_url, value):
                    return value
            return False

        try:
            return WebDriverWait(driver, 12, poll_frequency=0.25).until(target_permalink)
        except WebDriverException as exc:
            current_url = str(getattr(driver, "current_url", "") or fallback_url)
            raise CommentBrowserError(
                "URL Facebook tidak berhasil diarahkan ke posting target. Buka ulang sesi Facebook lalu coba URL ini lagi."
            ) from exc

    def _facebook_reels_html(self, reels_url: str, connector, target: str) -> tuple[str, int | None]:
        driver = self.start()
        driver.get(reels_url)
        self._wait_for_page()
        last_height = None
        stable_rounds = 0
        html = driver.page_source
        for _ in range(35):
            views = connector._views_from_reels_html(html, target)
            if views is not None:
                return html, views
            try:
                state = driver.execute_script(
                    r"""
                    const target = String(arguments[0] || '');
                    const match = Array.from(document.querySelectorAll('a[href]')).find(node =>
                      String(node.href || node.getAttribute('href') || '').includes(target)
                    );
                    if (match) match.scrollIntoView({block: 'center', inline: 'nearest'});
                    const before = document.documentElement.scrollHeight;
                    if (!match) window.scrollTo(0, before);
                    return {found: Boolean(match), height: before};
                    """,
                    target,
                )
            except WebDriverException:
                break
            time.sleep(0.45)
            html = driver.page_source
            height = state.get("height") if isinstance(state, dict) else None
            found = bool(state.get("found")) if isinstance(state, dict) else False
            if found:
                views = connector._views_from_reels_html(html, target)
                return html, views
            if height == last_height:
                stable_rounds += 1
            else:
                stable_rounds = 0
            last_height = height
            if stable_rounds >= 5:
                break
        return html, connector._views_from_reels_html(html, target)

    def _collect_facebook_enrichment_once(self, url: str) -> SocialResult:
        driver = self.start()
        driver.get(url)
        self._wait_for_page()
        current_url = self._facebook_permalink(driver, url)
        connector = get_platform_connector(current_url, "Facebook")
        target_ids = [
            identifier
            for identifier in connector._post_identifiers(current_url)
            if identifier.isdigit()
        ]
        if target_ids:
            try:
                WebDriverWait(driver, min(self.wait_seconds, 10)).until(
                    lambda active: bool(connector._target_feedback_positions(active.page_source, current_url))
                )
            except WebDriverException:
                pass
        post_html = driver.page_source
        post_soup = BeautifulSoup(post_html, "lxml")
        profile_url = connector._target_profile_url(post_html, post_soup, current_url)
        profile_html = None
        reels_html = None
        visible_views = None
        if profile_url:
            driver.get(profile_url)
            self._wait_for_page()
            profile_html = driver.page_source
        provisional = connector.enrich_loaded_html(
            post_html,
            current_url,
            profile_html=profile_html,
        )
        if provisional.views.value is None and profile_url and target_ids:
            reels_url = connector._profile_reels_url(profile_url)
            reels_html, visible_views = self._facebook_reels_html(
                reels_url,
                connector,
                target_ids[0],
            )
        result = connector.enrich_loaded_html(
            post_html,
            current_url,
            profile_html=profile_html,
            reels_html=reels_html,
        )
        if visible_views is not None:
            result.views = DataField(value=visible_views, status=FieldStatus.AVAILABLE)
        return result

    @staticmethod
    def _threads_visible_views(driver) -> int | None:
        try:
            label = driver.execute_script(
                r"""
                const count = '[\\d.,]+\\s*(?:k|m|b|rb|ribu|jt|juta)?';
                const labels = '(?:views?|tayangan|penayangan|kali\\s+(?:dilihat|ditonton))';
                const pattern = new RegExp(`^\\s*(?:${count}\\s+${labels}|(?:views?|tayangan|penayangan|dilihat|ditonton)\\s*:?\\s*${count})\\s*$`, 'i');
                const nodes = Array.from(document.querySelectorAll('div, span, header, h1, h2, h3'));
                const exact = nodes.find(node => {
                  const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
                  return pattern.test(text) && !Array.from(node.children).some(child =>
                    pattern.test((child.innerText || '').replace(/\s+/g, ' ').trim())
                  );
                });
                if (exact) return (exact.innerText || '').replace(/\s+/g, ' ').trim();
                const body = (document.body?.innerText || '').replace(/\s+/g, ' ');
                return (
                  body.match(/([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+(?:views?|tayangan|penayangan|kali\s+(?:dilihat|ditonton))\b/i) ||
                  body.match(/(?:views?|tayangan|penayangan|dilihat|ditonton)\s*:?\s*([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)/i) ||
                  []
                )[0] || '';
                """
            )
        except WebDriverException:
            return None
        text = str(label or "")
        match = re.search(
            r"([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+"
            r"(?:views?|tayangan|penayangan|kali\s+(?:dilihat|ditonton))\b",
            text,
            re.I,
        )
        if not match:
            match = re.search(
                r"(?:views?|tayangan|penayangan|dilihat|ditonton)\s*:?\s*"
                r"([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)",
                text,
                re.I,
            )
        return BaseConnector._human_count(match.group(1)) if match else None

    def _collect_threads_enrichment_once(self, url: str):
        driver = self.start()
        driver.get(url)
        self._wait_for_page()
        current_url = self._threads_permalink(driver, url)
        target_match = re.search(r"/post/([^/?#]+)", current_url, re.I)
        target_code = target_match.group(1) if target_match else ""
        connector = get_platform_connector(current_url, "Threads")
        if target_code:
            try:
                WebDriverWait(driver, min(self.wait_seconds, 10)).until(
                    lambda active: connector._target_post(active.page_source, target_code) is not None
                )
            except WebDriverException:
                pass
        post_html = driver.page_source
        visible_views = None
        try:
            visible_views = WebDriverWait(driver, min(self.wait_seconds, 5)).until(
                lambda active: self._threads_visible_views(active)
            )
        except WebDriverException:
            visible_views = self._threads_visible_views(driver)

        # A signed-in Threads session can render a permalink as a card in the
        # For You feed. Open that exact card to reach the real thread header,
        # where Threads exposes the public view count.
        if visible_views is None and self._open_threads_target_card(driver, target_code):
            try:
                visible_views = WebDriverWait(driver, min(self.wait_seconds, 10)).until(
                    lambda active: self._threads_visible_views(active)
                )
            except WebDriverException:
                visible_views = self._threads_visible_views(driver)
            post_html = driver.page_source

        # Reload the detail hash as a final route-level fallback. This also
        # handles sessions that already added the hash while showing the feed.
        detail_url = self._threads_detail_url(current_url)
        if visible_views is None and re.search(r"/@[^/]+/post/[^/?#]+", detail_url, re.I):
            driver.get(detail_url)
            self._wait_for_page()
            current_url = self._threads_permalink(driver, current_url)
            if target_code:
                try:
                    WebDriverWait(driver, min(self.wait_seconds, 10)).until(
                        lambda active: connector._target_post(active.page_source, target_code) is not None
                    )
                except WebDriverException:
                    pass
            post_html = driver.page_source
            try:
                visible_views = WebDriverWait(driver, min(self.wait_seconds, 10)).until(
                    lambda active: self._threads_visible_views(active)
                )
            except WebDriverException:
                visible_views = self._threads_visible_views(driver)
        preview = connector.enrich_loaded_html(post_html, current_url)
        username = str(preview.username.value or "").strip().lstrip("@")
        profile_html = None
        if username:
            cached = self._threads_followers_cache.get(username.casefold())
            if cached and time.monotonic() - cached[0] < 900:
                profile_html = cached[1]
            else:
                driver.get(f"https://www.threads.com/@{username}")
                self._wait_for_page()
                profile_html = driver.page_source
                self._threads_followers_cache[username.casefold()] = (time.monotonic(), profile_html)
        result = connector.enrich_loaded_html(
            post_html,
            current_url,
            profile_html=profile_html,
        )
        if visible_views is not None:
            result.views = DataField(value=visible_views, status=FieldStatus.AVAILABLE)
        return result

    def open_login(self) -> bool:
        """Open the saved session, showing login only when it has expired."""
        driver = self.start()
        try:
            if self.platform == "Facebook":
                # Match Instagram's quick login flow: show Chrome immediately
                # without loading and waiting for the Facebook home feed first.
                # Facebook will redirect an active saved session as needed.
                driver.get(self.LOGIN_URLS[self.platform])
                return self.is_logged_in(open_platform=False)
            driver.get(self.HOME_URLS[self.platform])
            self._wait_for_page()
            if self.is_logged_in(open_platform=False):
                return True
            driver.get(self.LOGIN_URLS[self.platform])
            return False
        except WebDriverException as exc:
            raise CommentBrowserError(
                f"Sesi Chrome MIDETA untuk {self.platform} tidak dapat dibuka."
            ) from exc

    def is_logged_in(self, *, open_platform: bool = True) -> bool:
        driver = self.start()
        if open_platform:
            current_url = str(getattr(driver, "current_url", "") or "")
            expected_host = self.PLATFORM_HOSTS[self.platform]
            if expected_host not in current_url.casefold():
                try:
                    driver.get(self.LOGIN_URLS[self.platform])
                    self._wait_for_page()
                except WebDriverException:
                    return False
        try:
            cookies = driver.get_cookies()
        except WebDriverException:
            return False
        names = {cookie.get("name") for cookie in cookies if cookie.get("value")}
        return bool(names & self.LOGIN_COOKIES[self.platform])

    def close(self) -> None:
        self._discard_driver()

    def _wait_for_page(self) -> None:
        WebDriverWait(self.start(), self.wait_seconds).until(
            lambda active: active.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        time.sleep(1.2)

    @staticmethod
    def _merge_thread_rows(stored: dict[str, dict], rows: list[dict]) -> int:
        added = 0
        for row in rows:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            if code not in stored:
                stored[code] = row
                added += 1
                continue
            updates = {key: value for key, value in row.items() if value not in (None, "")}
            if stored[code].get("comment_type") == "reply" and updates.get("comment_type") == "parent":
                updates.pop("comment_type")
            stored[code].update(updates)
        return added

    def _install_x_response_capture(self) -> None:
        """Keep X conversation payloads before its virtualized UI discards them."""
        driver = self.start()
        source = r"""
        (() => {
          if (window.__midetaXCaptureInstalled) return;
          window.__midetaXCaptureInstalled = true;
          window.__midetaXResponses = [];
          const wanted = value => /(?:TweetDetail|TweetResultByRestId|conversation)/i.test(String(value || ''));
          const remember = (url, body) => {
            const text = String(body || '');
            if (!wanted(url) || !text || !/(?:tweet_results|conversation_id_str|threaded_conversation)/i.test(text)) return;
            const queue = window.__midetaXResponses || (window.__midetaXResponses = []);
            queue.push({url: String(url || ''), body: text});
            if (queue.length > 120) queue.splice(0, queue.length - 120);
          };

          const nativeFetch = window.fetch;
          if (typeof nativeFetch === 'function') {
            window.fetch = async function(...args) {
              const response = await nativeFetch.apply(this, args);
              try {
                const request = args[0];
                const url = typeof request === 'string' ? request : (request?.url || response.url || '');
                if (wanted(url)) response.clone().text().then(body => remember(url, body)).catch(() => {});
              } catch (_) {}
              return response;
            };
          }

          const nativeOpen = XMLHttpRequest.prototype.open;
          const nativeSend = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            this.__midetaXUrl = String(url || '');
            return nativeOpen.call(this, method, url, ...rest);
          };
          XMLHttpRequest.prototype.send = function(...args) {
            if (wanted(this.__midetaXUrl)) {
              this.addEventListener('load', () => {
                try {
                  if (!this.responseType || this.responseType === 'text') {
                    remember(this.__midetaXUrl, this.responseText || '');
                  }
                } catch (_) {}
              }, {once: true});
            }
            return nativeSend.apply(this, args);
          };
        })();
        """
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": source},
            )
            self._x_response_capture_ready = True
        except (AttributeError, WebDriverException):
            self._x_response_capture_ready = False

    @staticmethod
    def _x_payload_rows(payloads, target_code: str) -> list[dict]:
        """Convert captured TweetDetail responses into one stable conversation."""
        if not target_code or not isinstance(payloads, list):
            return []

        decoded: list[object] = []
        for payload in payloads:
            body = payload.get("body") if isinstance(payload, dict) else payload
            if isinstance(body, (dict, list)):
                decoded.append(body)
                continue
            text = str(body or "").strip()
            if not text:
                continue
            start_positions = [position for position in (text.find("{"), text.find("[")) if position >= 0]
            if not start_positions:
                continue
            try:
                decoded.append(json.loads(text[min(start_positions):]))
            except (json.JSONDecodeError, TypeError):
                continue

        tweets: dict[str, dict] = {}

        def walk(value) -> None:
            if isinstance(value, dict):
                legacy = value.get("legacy")
                identifier = value.get("rest_id") or value.get("id_str")
                note = value.get("note_tweet")
                looks_like_tweet = isinstance(legacy, dict) and (
                    legacy.get("conversation_id_str")
                    or legacy.get("in_reply_to_status_id_str")
                    or legacy.get("id_str")
                )
                if identifier and (looks_like_tweet or isinstance(note, dict)):
                    tweets.setdefault(str(identifier), value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for payload in decoded:
            walk(payload)

        rows: list[dict] = []
        for identifier, tweet in tweets.items():
            legacy = tweet.get("legacy") if isinstance(tweet.get("legacy"), dict) else {}
            conversation_id = str(legacy.get("conversation_id_str") or "")
            parent_id = str(legacy.get("in_reply_to_status_id_str") or "")
            is_target = identifier == target_code
            if conversation_id != target_code or (not is_target and not parent_id):
                continue

            author = ""
            core = tweet.get("core") if isinstance(tweet.get("core"), dict) else {}
            user_results = core.get("user_results") if isinstance(core.get("user_results"), dict) else {}
            user = user_results.get("result") if isinstance(user_results.get("result"), dict) else {}
            for source in (user.get("legacy"), user.get("core"), core):
                if isinstance(source, dict):
                    author = str(source.get("screen_name") or source.get("name") or "").strip()
                    if author:
                        break

            text = str(legacy.get("full_text") or "").strip()
            note = tweet.get("note_tweet") if isinstance(tweet.get("note_tweet"), dict) else {}
            note_results = note.get("note_tweet_results") if isinstance(note.get("note_tweet_results"), dict) else {}
            note_result = note_results.get("result") if isinstance(note_results.get("result"), dict) else {}
            text = str(note_result.get("text") or text).strip()
            rows.append(
                {
                    "href": f"https://x.com/{author or 'i'}/status/{identifier}",
                    "code": identifier,
                    "author": author,
                    "date": legacy.get("created_at") or "",
                    "comment": "" if is_target else text,
                    "likes": legacy.get("favorite_count") or 0,
                    "replies": legacy.get("reply_count") or 0,
                    "comment_type": "parent" if parent_id == target_code else "reply",
                    "context": (
                        f"Replying to @{legacy.get('in_reply_to_screen_name')}"
                        if legacy.get("in_reply_to_screen_name")
                        else ""
                    ),
                    "is_target": is_target,
                }
            )
        return rows

    def _x_network_rows(self, target_code: str) -> list[dict]:
        if not getattr(self, "_x_response_capture_ready", False):
            return []
        try:
            payloads = self.start().execute_script(
                r"""
                const rows = Array.isArray(window.__midetaXResponses)
                  ? window.__midetaXResponses.slice()
                  : [];
                window.__midetaXResponses = [];
                return rows;
                """
            )
        except WebDriverException:
            return []
        return self._x_payload_rows(payloads, target_code)

    def _load_conversation(
        self,
        target_code: str = "",
        url: str = "",
        max_comments: int = MAX_COMMENTS_PER_URL,
        expected_comments: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        driver = self.start()
        thread_rows: dict[str, dict] = {}
        stable_rounds = 0
        idle_rounds = 0
        previous_scroll = None
        previous_height = None
        reported_count = -1
        locked_threads_url = ""
        locked_x_url = ""
        if self.platform == "Threads":
            max_rounds = self.THREADS_MAX_SCROLL_ROUNDS
            current_url = str(getattr(driver, "current_url", "") or "")
            current_match = re.search(r"/@[^/]+/post/([^/?#]+)", current_url, re.I)
            if current_match and current_match.group(1).casefold() == target_code.casefold():
                locked_threads_url = self._threads_detail_url(current_url)
        elif self.platform == "Facebook":
            max_rounds = self.FACEBOOK_MAX_SCROLL_ROUNDS
        elif self.platform == "X":
            max_rounds = self.X_MAX_SCROLL_ROUNDS
            current_url = str(getattr(driver, "current_url", "") or "")
            current_match = re.search(r"/status/(\d+)", current_url, re.I)
            if current_match and current_match.group(1) == target_code:
                locked_x_url = current_url
        else:
            max_rounds = self.OTHER_MAX_SCROLL_ROUNDS

        def report_progress() -> int:
            nonlocal reported_count
            count = sum(
                bool(row.get("comment")) and not row.get("is_target") and row.get("code") != target_code
                for row in thread_rows.values()
            )
            count = min(count, max_comments)
            if progress_callback is not None and count != reported_count:
                progress_callback(count, max_comments)
            reported_count = count
            return count

        for _ in range(max_rounds):
            added = 0
            if self.platform == "Threads" and target_code:
                try:
                    added += self._merge_thread_rows(thread_rows, self._threads_dom_rows(target_code))
                except WebDriverException:
                    pass
            elif self.platform == "Facebook":
                try:
                    added += self._merge_thread_rows(thread_rows, self._facebook_dom_rows(url))
                except WebDriverException:
                    pass
            elif self.platform == "X":
                try:
                    added += self._merge_thread_rows(thread_rows, self._x_network_rows(target_code))
                    added += self._merge_thread_rows(thread_rows, self._x_dom_rows())
                except WebDriverException:
                    pass
            collection_target = min(max_comments, expected_comments) if expected_comments else max_comments
            if report_progress() >= collection_target:
                break
            try:
                state = driver.execute_script(
                    r"""
                    const platform = arguments[0];
                    const targetCode = String(arguments[1] || '');
                    const postAnchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
                    const targetAnchor = platform === 'Threads' && targetCode
                      ? postAnchors.find(node => {
                          const href = String(node.href || node.getAttribute('href') || '');
                          const match = href.match(/\/@[^/]+\/post\/([^/?#]+)/i);
                          return match && match[1].toLowerCase() === targetCode.toLowerCase();
                        })
                      : null;
                    const pageMatch = decodeURIComponent(window.location.pathname || '')
                      .match(/\/@[^/]+\/post\/([^/?#]+)/i);
                    const xPageMatch = decodeURIComponent(window.location.pathname || '')
                      .match(/\/status\/(\d+)/i);
                    const targetLocked = platform === 'Threads'
                      ? Boolean(targetCode && pageMatch &&
                          pageMatch[1].toLowerCase() === targetCode.toLowerCase())
                      : platform === 'X'
                      ? Boolean(targetCode && xPageMatch && xPageMatch[1] === targetCode)
                      : true;
                    if (!targetLocked) {
                      return {
                        reachedEnd: true,
                        clicked: 0,
                        scrollY: window.scrollY,
                        height: document.documentElement.scrollHeight,
                        targetLocked: false
                      };
                    }
                    const targetBox = targetAnchor
                      ? (targetAnchor.closest('[data-pressable-container="true"]') || targetAnchor)
                      : null;
                    const targetTop = targetBox
                      ? targetBox.getBoundingClientRect().top + window.scrollY
                      : 0;
                    const labels = [
                      'show replies', 'show more replies', 'view replies', 'view more replies',
                      'tampilkan balasan', 'lihat balasan', 'balasan lainnya',
                      'view previous comments', 'view more comments', 'see more comments', 'load more comments',
                      'lihat komentar sebelumnya', 'lihat komentar lainnya', 'muat komentar lainnya',
                      'tampilkan komentar lainnya',
                      'show probable spam', 'show hidden replies', 'show additional replies',
                      'tampilkan kemungkinan spam', 'tampilkan balasan tersembunyi'
                    ];
                    const endLabels = ['related threads', 'thread terkait', 'threads terkait'];
                    const endCandidates = Array.from(document.querySelectorAll('div, span')).filter(node => {
                      const text = (node.textContent || '').trim().toLowerCase();
                      return endLabels.includes(text) && !Array.from(node.children).some(child =>
                        (child.textContent || '').trim().toLowerCase() === text
                      );
                    });
                    const endTops = endCandidates
                      .map(node => node.getBoundingClientRect().top + window.scrollY)
                      .filter(top => top > targetTop);
                    const endTop = endTops.length ? Math.min(...endTops) : Number.POSITIVE_INFINITY;
                    const end = endCandidates.find(node =>
                      node.getBoundingClientRect().top + window.scrollY === endTop
                    );
                    const controlRoot = platform === 'X'
                      ? (document.querySelector('[data-testid="primaryColumn"]') || document.querySelector('main') || document)
                      : document;
                    const controls = Array.from(controlRoot.querySelectorAll('button, [role="button"]'));
                    const matchingLoaders = controls.filter(node => {
                      const text = (node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase();
                      const replyLoader =
                        /^(show|view|see|load|tampilkan|lihat|muat).*?(repl|balasan|comments?|komentar).*$/i.test(text) ||
                        /^\d[\d.,]*\s+(?:more\s+|lainnya\s+)?(?:replies|balasan|comments?|komentar)\b/i.test(text);
                      const xHiddenLoader = platform === 'X' &&
                        /^(show|view|see|tampilkan|lihat).*?(?:spam|hidden|tersembunyi)/i.test(text);
                      const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
                      const nodeTop = node.getBoundingClientRect().top + window.scrollY;
                      const insideTargetConversation = platform !== 'Threads' || (
                        nodeTop > targetTop && nodeTop < endTop
                      );
                      const postLink = node.closest('a[href*="/post/"]');
                      const isPostCard = node.matches('[data-pressable-container="true"]');
                      return visible && insideTargetConversation && !postLink && !isPostCard &&
                        (labels.some(label => text.includes(label)) || replyLoader || xHiddenLoader);
                    });
                    // Only activate the smallest matching controls. Parent
                    // pressable cards often contain the words "View replies"
                    // but open another post instead of expanding the target.
                    const leafLoaders = matchingLoaders.filter(node => !matchingLoaders.some(other =>
                      other !== node && node.contains(other)
                    ));
                    let clicked = 0;
                    for (const node of leafLoaders) {
                      node.click();
                      clicked += 1;
                    }
                    let scrollTarget = window;
                    if (platform === 'Facebook') {
                      const seed = Array.from(document.querySelectorAll('[role="article"]')).find(node =>
                          /^(comment|reply) by\b|^(komentar|balasan) (oleh|dari)\b/i.test(
                            node.getAttribute('aria-label') || ''
                          ) || node.querySelector('a[href*="comment_id="]')
                        ) ||
                        Array.from(document.querySelectorAll('button, [role="button"]')).find(node =>
                          /comments?|komentar|repl|balasan/i.test(
                            (node.innerText || node.getAttribute('aria-label') || '').trim()
                          )
                        );
                      let parent = seed?.parentElement || null;
                      while (parent) {
                        const style = window.getComputedStyle(parent);
                        const scrollable = /(auto|scroll)/.test(style.overflowY) &&
                          parent.scrollHeight > parent.clientHeight + 40;
                        if (scrollable) {
                          scrollTarget = parent;
                          break;
                        }
                        parent = parent.parentElement;
                      }
                    }
                    const step = Math.max(
                      scrollTarget === window ? window.innerHeight * 0.85 : scrollTarget.clientHeight * 0.85,
                      600
                    );
                    if (scrollTarget === window) window.scrollBy(0, step);
                    else scrollTarget.scrollBy(0, step);
                    const scrollY = scrollTarget === window ? window.scrollY : scrollTarget.scrollTop;
                    const height = scrollTarget === window ? document.documentElement.scrollHeight : scrollTarget.scrollHeight;
                    const viewport = scrollTarget === window ? window.innerHeight : scrollTarget.clientHeight;
                    const reachedScrollEnd = scrollY + viewport >= height - 4;
                    const reachedEnd = platform === 'Facebook'
                      ? reachedScrollEnd
                      : Boolean(end && end.getBoundingClientRect().top <= window.innerHeight * 1.1);
                    return {
                      reachedEnd,
                      clicked,
                      scrollY,
                      height,
                      targetLocked
                    };
                    """,
                    self.platform,
                    target_code,
                )
            except WebDriverException:
                break
            if isinstance(state, dict) and state.get("clicked"):
                time.sleep(1.1)
            elif self.platform == "X":
                time.sleep(1.0)
            else:
                time.sleep(0.7)

            if self.platform == "Threads" and target_code:
                try:
                    added += self._merge_thread_rows(thread_rows, self._threads_dom_rows(target_code))
                except WebDriverException:
                    pass
            elif self.platform == "Facebook":
                try:
                    added += self._merge_thread_rows(thread_rows, self._facebook_dom_rows(url))
                except WebDriverException:
                    pass
            elif self.platform == "X":
                try:
                    added += self._merge_thread_rows(thread_rows, self._x_network_rows(target_code))
                    added += self._merge_thread_rows(thread_rows, self._x_dom_rows())
                except WebDriverException:
                    pass

            if report_progress() >= collection_target:
                break

            state = state if isinstance(state, dict) else {"reachedEnd": bool(state)}
            if self.platform == "Threads" and state.get("targetLocked") is False:
                if locked_threads_url:
                    try:
                        driver.get(locked_threads_url)
                        self._wait_for_page()
                    except WebDriverException:
                        pass
                break
            if self.platform == "X" and state.get("targetLocked") is False:
                if locked_x_url:
                    try:
                        driver.get(locked_x_url)
                        self._wait_for_page()
                    except WebDriverException:
                        pass
                break
            scroll_position = state.get("scrollY")
            page_height = state.get("height")
            moved = previous_scroll is None or scroll_position != previous_scroll
            grew = previous_height is None or page_height != previous_height
            clicked = bool(state.get("clicked"))
            stable_rounds = stable_rounds + 1 if added == 0 and not clicked else 0
            idle_rounds = idle_rounds + 1 if not (added or moved or grew or clicked) else 0
            previous_scroll = scroll_position
            previous_height = page_height

            end_stable_rounds = 6 if self.platform == "Facebook" else self.END_STABLE_ROUNDS
            if state.get("reachedEnd") and stable_rounds >= end_stable_rounds:
                break
            if self.platform == "Facebook" and stable_rounds >= 12 and not clicked:
                break
            if self.platform == "Threads" and stable_rounds >= 12 and not clicked:
                break
            idle_limit = self.X_IDLE_STABLE_ROUNDS if self.platform == "X" else self.IDLE_STABLE_ROUNDS
            if idle_rounds >= idle_limit:
                break
        if self.platform == "X":
            try:
                self._merge_thread_rows(thread_rows, self._x_network_rows(target_code))
            except WebDriverException:
                pass
        rows = list(thread_rows.values())
        kept: list[dict] = []
        comment_count = 0
        for row in rows:
            is_comment = bool(row.get("comment")) and not row.get("is_target") and row.get("code") != target_code
            if is_comment:
                if comment_count >= max_comments:
                    continue
                comment_count += 1
            kept.append(row)
        return kept

    def _x_dom_rows(self) -> list[dict]:
        return self.start().execute_script(
            r"""
            const conversation = document.querySelector('[data-testid="primaryColumn"]') ||
              document.querySelector('main') || document;
            const articles = Array.from(conversation.querySelectorAll('article[data-testid="tweet"]'));
            const targetTop = articles.length ? articles[0].getBoundingClientRect().top : Number.NEGATIVE_INFINITY;
            const endLabels = ['discover more', 'more tweets', 'relevant people', 'temukan lainnya', 'tweet lainnya'];
            const endTops = Array.from(conversation.querySelectorAll('div, span'))
              .filter(node => {
                const text = (node.textContent || '').trim().toLowerCase();
                return endLabels.includes(text) && !Array.from(node.children).some(child =>
                  (child.textContent || '').trim().toLowerCase() === text
                );
              })
              .map(node => node.getBoundingClientRect().top)
              .filter(top => top > targetTop);
            const endTop = endTops.length ? Math.min(...endTops) : Number.POSITIVE_INFINITY;
            return articles.filter(article => article.getBoundingClientRect().top < endTop).map(article => {
              const time = article.querySelector('time');
              const statusLink = time && time.closest('a');
              const userText = article.querySelector('[data-testid="User-Name"]')?.innerText || '';
              const username = (userText.match(/@([A-Za-z0-9_]+)/) || [])[1] || '';
              const metric = name => {
                const button = article.querySelector(`[data-testid="${name}"], [data-testid="un${name}"]`);
                return button ? (button.getAttribute('aria-label') || button.innerText || '') : '';
              };
              return {
                href: statusLink?.href || '',
                code: ((statusLink?.href || '').match(/\/status\/(\d+)/) || [])[1] || '',
                author: username,
                date: time?.getAttribute('datetime') || '',
                comment: article.querySelector('[data-testid="tweetText"]')?.innerText || '',
                likes: metric('like'),
                replies: metric('reply'),
                context: article.innerText || ''
              };
            });
            """
        )

    def _prepare_x_comments(self) -> None:
        """Switch an X conversation from Relevant to the latest reply view."""
        driver = self.start()
        try:
            opened = driver.execute_script(
                r"""
                const controls = Array.from(document.querySelectorAll('button, [role="button"]'));
                const sorter = controls.find(node => {
                  const values = [node.innerText || '', node.getAttribute('aria-label') || '']
                    .map(value => value.replace(/\s+/g, ' ').trim().toLowerCase())
                    .filter(Boolean);
                  const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
                  return visible && values.some(value =>
                    /^(?:relevant|relevan|top)(?:\s+(?:replies|balasan))?$/.test(value) ||
                    /(?:timeline|urutan).*\b(?:relevant|relevan)\b/.test(value)
                  );
                });
                if (!sorter) return false;
                sorter.click();
                return true;
                """
            )
            if not opened:
                return
            time.sleep(0.5)
            selected = driver.execute_script(
                r"""
                const choices = Array.from(document.querySelectorAll(
                  '[role="menuitem"], [role="menuitemradio"], [role="option"], [role="radio"], button'
                ));
                const latest = choices.find(node => {
                  const values = [node.innerText || '', node.getAttribute('aria-label') || '']
                    .map(value => value.replace(/\s+/g, ' ').trim().toLowerCase())
                    .filter(Boolean);
                  const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
                  return visible && values.some(value =>
                    /^(?:latest|recent|newest|most recent|terbaru|paling baru)(?:\s+(?:replies|balasan))?$/.test(value)
                  );
                });
                if (!latest) return false;
                latest.click();
                return true;
                """
            )
            if selected:
                time.sleep(1.2)
        except WebDriverException:
            return

    def _threads_dom_rows(self, target_code: str) -> list[dict]:
        return self.start().execute_script(
            r"""
            const targetCode = arguments[0];
            const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
            const rows = [];
            const seen = new Set();
            const groups = [];
            const endLabels = ['related threads', 'thread terkait', 'threads terkait'];
            const endTops = Array.from(document.querySelectorAll('div, span'))
              .filter(node => {
                const text = (node.textContent || '').trim().toLowerCase();
                return endLabels.includes(text) && !Array.from(node.children).some(child =>
                  (child.textContent || '').trim().toLowerCase() === text
                );
              })
              .map(node => node.getBoundingClientRect().top);

            const matchingTargetAnchors = anchors.filter(anchor => {
              const href = anchor.href || '';
              const match = href.match(/\/(@[^/]+)\/post\/([^/?#]+)/);
              return Boolean(match && match[2] === targetCode);
            });
            const targetAnchor = matchingTargetAnchors.find(anchor =>
              anchor.closest('[data-pressable-container="true"]')
            ) || matchingTargetAnchors[0];
            const pagePath = decodeURIComponent(window.location.pathname || '');
            const pageMatch = pagePath.match(/\/@[^/]+\/post\/([^/?#]+)/);
            if (!pageMatch || pageMatch[1].toLowerCase() !== targetCode.toLowerCase()) return [];
            const targetBox = targetAnchor
              ? (targetAnchor.closest('[data-pressable-container="true"]') || targetAnchor)
              : null;
            const targetTop = targetBox ? targetBox.getBoundingClientRect().top : Number.NEGATIVE_INFINITY;
            const boundedEndTops = endTops.filter(top => top > targetTop);
            const endTop = boundedEndTops.length ? Math.min(...boundedEndTops) : Number.POSITIVE_INFINITY;
            rows.push({code: targetCode, comment: '', is_target: true});
            seen.add(targetCode);

            for (const anchor of anchors) {
              const href = anchor.href || '';
              const match = href.match(/\/(@[^/]+)\/post\/([^/?#]+)/);
              if (!match || seen.has(match[2])) continue;
              let box = anchor.closest('[data-pressable-container="true"]');
              if (!box) {
                box = anchor;
                for (let level = 0; level < 7 && box.parentElement; level++) {
                  box = box.parentElement;
                  if (box.querySelectorAll('svg').length >= 3 && (box.innerText || '').length > 5) break;
                }
              }
              if (!box || box.parentElement?.closest('[data-pressable-container="true"]')) continue;
              const top = box.getBoundingClientRect().top;
              if (top >= endTop || (targetBox && match[2] !== targetCode && top <= targetTop)) continue;
              seen.add(match[2]);
              const candidates = Array.from(box.querySelectorAll('[dir="auto"]'))
                .map(node => (node.innerText || '').trim())
                .filter(text => text && text !== match[1].slice(1));
              candidates.sort((a, b) => b.length - a.length);
              const iconMetric = labels => {
                const controls = Array.from(box.querySelectorAll('button, [role="button"]'));
                const control = controls.find(node => {
                  const iconText = Array.from(node.querySelectorAll('svg, img'))
                    .map(icon => `${icon.getAttribute('aria-label') || ''} ${icon.getAttribute('alt') || ''}`)
                    .join(' ');
                  const value = `${node.getAttribute('aria-label') || ''} ${node.textContent || ''} ${iconText}`
                    .replace(/\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                  return labels.some(label => value.includes(label));
                });
                if (!control) return '';
                const iconText = Array.from(control.querySelectorAll('svg, img'))
                  .map(icon => `${icon.getAttribute('aria-label') || ''} ${icon.getAttribute('alt') || ''}`)
                  .join(' ');
                return `${control.getAttribute('aria-label') || ''} ${control.textContent || ''} ${iconText}`.trim();
              };
              const group = box.parentElement?.parentElement || box;
              let groupIndex = groups.indexOf(group);
              if (groupIndex < 0) {
                groups.push(group);
                groupIndex = groups.length - 1;
              }
              const groupRows = Array.from(group.querySelectorAll('[data-pressable-container="true"]'))
                .filter(candidate => !candidate.parentElement?.closest('[data-pressable-container="true"]'));
              const comment = (candidates[0] || '').replace(/\n(?:Translate|Terjemahkan)\s*$/i, '').trim();
              rows.push({
                href,
                code: match[2],
                author: match[1].slice(1),
                date: box.querySelector('time')?.getAttribute('datetime') ||
                  anchor.getAttribute('title') || anchor.innerText || '',
                comment,
                likes: iconMetric(['like', 'suka']),
                replies: iconMetric(['reply', 'comment', 'balasan', 'komentar']),
                comment_type: groupRows[0] === box ? 'parent' : 'reply',
                group: groupIndex
              });
            }
            return rows;
            """,
            target_code,
        )

    def _prepare_facebook_comments(self) -> None:
        """Open the comment panel and switch Facebook to all comments."""
        driver = self.start()
        try:
            opened_panel = driver.execute_script(
                r"""
                const commentArticle = Array.from(document.querySelectorAll('[role="article"]')).some(node =>
                  /^(comment|reply) by\b|^(komentar|balasan) (oleh|dari)\b/i.test(
                    node.getAttribute('aria-label') || ''
                  ) || node.querySelector('a[href*="comment_id="]')
                );
                if (commentArticle) return false;
                const controls = Array.from(document.querySelectorAll(
                  'button, [role="button"], a, [aria-label]'
                ));
                const commentButton = controls.find(node => {
                  const label = (node.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
                  const text = `${label} ${node.innerText || ''}`.replace(/\s+/g, ' ').trim();
                  const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
                  return visible && (
                    /\b\d[\d.,]*\s*(?:comments?|komentar)\b/i.test(text) ||
                    /^(?:comments?|comment|komentar|komentari)$/i.test(label) ||
                    /^(?:comments?|comment|komentar|komentari)\b/i.test(text)
                  ) && !/(most relevant|paling relevan|top comments|komentar teratas)/i.test(text);
                });
                if (!commentButton) return false;
                const clickable = commentButton.closest('button, [role="button"], a') || commentButton;
                clickable.click();
                return true;
                """
            )
            if opened_panel:
                time.sleep(1.2)
            opened = driver.execute_script(
                r"""
                const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
                const sorter = candidates.find(node => {
                  const text = (node.innerText || node.getAttribute('aria-label') || '').trim();
                  return /^(most relevant|paling relevan|top comments|komentar teratas|newest|terbaru)\b/i.test(text);
                });
                if (!sorter) return false;
                sorter.click();
                return true;
                """
            )
            if not opened:
                return
            time.sleep(0.6)
            driver.execute_script(
                r"""
                const choices = Array.from(
                  document.querySelectorAll(
                    '[role="menuitem"], [role="menuitemradio"], [role="option"], [role="radio"]'
                  )
                );
                let allComments = choices.find(node => {
                  const text = (node.innerText || node.getAttribute('aria-label') || '').trim();
                  return /^(all comments|semua komentar)\b/i.test(text);
                });
                if (!allComments) {
                  const leaf = Array.from(document.querySelectorAll('span, div')).find(node => {
                    const text = (node.innerText || '').trim();
                    return /^(all comments|semua komentar)\b/i.test(text) &&
                      !Array.from(node.children).some(child =>
                        /^(all comments|semua komentar)\b/i.test((child.innerText || '').trim())
                      );
                  });
                  allComments = leaf?.closest(
                    '[role="menuitem"], [role="menuitemradio"], [role="option"], [role="radio"], [role="button"]'
                  ) || leaf;
                }
                if (allComments) allComments.click();
                """
            )
            time.sleep(0.8)
        except WebDriverException:
            return

    def _facebook_dom_rows(self, url: str) -> list[dict]:
        """Read Facebook comment articles without including the post or recommendations."""
        return self.start().execute_script(
            r"""
            const sourceUrl = arguments[0];
            const roleArticles = Array.from(document.querySelectorAll('[role="article"]'));
            const commentLabel = /^(comment|reply) by\b|^(komentar|balasan) (oleh|dari)\b/i;
            const uiText = /^(like|suka|reply|balas|share|bagikan|follow|ikuti|see more|lihat selengkapnya|edited|diedit)$/i;
            const relativeDate = /^(?:just now|baru saja|yesterday|kemarin|(?:\d+\s*|se)(?:sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|detik|menit|jam|hari|minggu)(?:\s+(?:ago|lalu|yang lalu))?)$/i;
            const cleanAuthor = value => (value || '')
              .replace(/\s+/g, ' ')
              .replace(/\s+(?:just now|baru saja|yesterday|kemarin|(?:\d+\s*|se)(?:sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|detik|menit|jam|hari|minggu)(?:\s+(?:ago|lalu|yang lalu))?)$/i, '')
              .trim();
            const isProfileLink = anchor => {
              const href = anchor.href || '';
              const text = (anchor.innerText || '').trim();
              return text && /facebook\.com\//i.test(href) &&
                !/(comment_id=|reply_comment_id=|\/posts\/|\/photos\/|\/videos\/|\/reel\/|\/watch\/|permalink\.php)/i.test(href);
            };
            const fallbackArticles = [];
            const replyActions = Array.from(document.querySelectorAll('button, [role="button"], a')).filter(node => {
              const text = (node.innerText || node.getAttribute('aria-label') || '').trim();
              return /^(reply|balas)$/i.test(text) &&
                Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
            });
            for (const action of replyActions) {
              if (action.closest('[role="article"]')) continue;
              let container = action.parentElement;
              for (let level = 0; level < 10 && container; level++, container = container.parentElement) {
                const hasProfile = Array.from(container.querySelectorAll('a[href]')).some(isProfileLink);
                const hasCommentText = Array.from(container.querySelectorAll('[dir="auto"]'))
                  .some(node => {
                    const text = (node.innerText || '').trim();
                    return text && !uiText.test(text) && !relativeDate.test(text);
                  });
                if (hasProfile && hasCommentText) {
                  fallbackArticles.push(container);
                  break;
                }
                if ((container.innerText || '').length > 5_000) break;
              }
            }
            const articles = Array.from(new Set([...roleArticles, ...fallbackArticles]));
            const probableComments = articles.filter(article =>
              fallbackArticles.includes(article) || commentLabel.test(article.getAttribute('aria-label') || '')
            );
            const commentLefts = probableComments
              .map(article => article.getBoundingClientRect().left)
              .filter(value => Number.isFinite(value));
            const baseCommentLeft = commentLefts.length ? Math.min(...commentLefts) : Number.POSITIVE_INFINITY;
            const rows = [];

            for (const article of articles) {
              const label = (article.getAttribute('aria-label') || '').trim();
              const isFallback = fallbackArticles.includes(article);

              const own = node => !articles.some(other =>
                other !== article && article.contains(other) && other.contains(node)
              );
              const anchors = Array.from(article.querySelectorAll('a[href]')).filter(own);
              const hasCommentLink = anchors.some(anchor => /[?&](?:comment_id|reply_comment_id)=\d+/i.test(anchor.href || ''));
              if (!isFallback && !commentLabel.test(label) && !hasCommentLink) continue;
              const profile = anchors.find(isProfileLink);
              const labelAuthor = label
                .replace(/^(comment|reply) by\s+/i, '')
                .replace(/^(komentar|balasan) (oleh|dari)\s+/i, '')
                .trim();
              const profileParts = profile
                ? Array.from(profile.querySelectorAll('[dir="auto"], span'))
                    .map(node => (node.innerText || '').trim())
                    .filter(text => text && !relativeDate.test(text))
                : [];
              const author = cleanAuthor(profileParts[0] || profile?.innerText || labelAuthor);

              const candidates = Array.from(article.querySelectorAll('[dir="auto"]'))
                .filter(own)
                .filter(node => !node.closest('a, button, [role="button"]'))
                .map(node => (node.innerText || '').trim())
                .filter(text => text && cleanAuthor(text) !== author && !relativeDate.test(text) && !uiText.test(text));
              candidates.sort((a, b) => b.length - a.length);
              const comment = candidates[0] || '';
              if (!comment) continue;

              const commentLink = anchors.find(anchor => /[?&](?:comment_id|reply_comment_id)=\d+/i.test(anchor.href || ''));
              const commentHref = commentLink?.href || '';
              const parentCommentId = (commentHref.match(/[?&]comment_id=(\d+)/i) || [])[1] || '';
              const replyCommentId = (commentHref.match(/[?&]reply_comment_id=(\d+)/i) || [])[1] || '';
              const commentId = replyCommentId || parentCommentId;
              const dateNodes = Array.from(
                article.querySelectorAll('abbr, time, [data-utime], a[title], span[title], a[href*="comment_id="]')
              ).filter(own);
              const dateValue = node => (
                node.getAttribute('datetime') || node.getAttribute('data-utime') ||
                node.getAttribute('title') || node.getAttribute('aria-label') || node.innerText || ''
              ).trim();
              const dateNode = dateNodes.find(node => {
                const value = dateValue(node);
                return Boolean(node.getAttribute('datetime') || node.getAttribute('data-utime') || relativeDate.test(value));
              });
              const labelDate = (label.match(
                /(?:just now|baru saja|yesterday|kemarin|(?:\d+\s*|se)(?:sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|wk|wks|week|weeks|detik|menit|jam|hari|minggu)(?:\s+(?:ago|lalu|yang lalu))?)$/i
              ) || [])[0] || '';
              const linkDate = (commentLink?.innerText || '').trim();
              const date = dateNode ? dateValue(dateNode) : (relativeDate.test(linkDate) ? linkDate : labelDate);

              const controls = Array.from(
                article.querySelectorAll('button, [role="button"], a, [aria-label]')
              ).filter(own);
              const metric = patterns => {
                const node = controls.find(control => {
                  const text = `${control.getAttribute('aria-label') || ''} ${control.getAttribute('title') || ''} ${control.innerText || ''}`.trim();
                  return patterns.some(pattern => pattern.test(text));
                });
                return node
                  ? `${node.getAttribute('aria-label') || ''} ${node.getAttribute('title') || ''} ${node.innerText || ''}`.trim()
                  : '';
              };
              const likes = metric([
                /\d[\d.,]*\s*(?:people\s+)?(?:reacted|reactions?|likes?|suka|reaksi|tanggapan)\b/i,
                /(?:reactions?|likes?|suka|reaksi|tanggapan)\D{0,24}\d/i,
                /see who reacted|lihat siapa yang (?:bereaksi|memberikan tanggapan)/i
              ]);
              const replies = metric([
                /(?:view|see|show|load)?\s*\d[\d.,]*\s+(?:more\s+)?repl/i,
                /(?:lihat|tampilkan|muat)?\s*\d[\d.,]*\s+balasan/i,
                /repl(?:y|ies)\D{0,16}\d|balasan\D{0,16}\d/i
              ]);
              const parentArticle = article.parentElement?.closest('[role="article"]');
              const labelledReply = /^(reply by|balasan (oleh|dari))\b/i.test(label);
              const nestedReply = parentArticle && (
                commentLabel.test(parentArticle.getAttribute('aria-label') || '') ||
                parentArticle.querySelector('a[href*="comment_id="]')
              );
              const indentedReply = article.getBoundingClientRect().left > baseCommentLeft + 24;
              const type = labelledReply || replyCommentId || nestedReply || indentedReply
                ? 'reply' : 'parent';
              const code = commentId || [author, date, comment].join('|').toLowerCase();
              rows.push({code, author, date, comment, likes, replies, comment_type: type, source_url: sourceUrl});
            }
            return rows;
            """,
            url,
        )

    def _dom_comments(self, url: str, thread_rows: list[dict] | None = None) -> list[PublicComment]:
        if self.platform == "X":
            target_match = re.search(r"/status/(\d+)", url)
            target_id = target_match.group(1) if target_match else ""
            target_author_match = re.search(r"x\.com/([^/]+)/status/", url, re.I)
            target_author = target_author_match.group(1) if target_author_match else ""
            rows = thread_rows if thread_rows is not None else self._x_dom_rows()
            comments = []
            for row in rows:
                status_match = re.search(r"/status/(\d+)", row.get("href") or "")
                if not status_match or status_match.group(1) == target_id or not row.get("comment"):
                    continue
                context = str(row.get("context") or "")
                is_parent = not target_author or f"@{target_author}".casefold() in context.casefold()
                comment_type = row.get("comment_type")
                comments.append(PublicComment(
                    author=(row.get("author") or "").lstrip("@") or None,
                    comment=str(row["comment"]).strip(),
                    commented_at=row.get("date") or None,
                    likes=self._count(row.get("likes")),
                    reply_count=self._count(row.get("replies")),
                    comment_type=(
                        comment_type
                        if comment_type in {"parent", "reply"}
                        else "parent" if is_parent else "reply"
                    ),
                    source_url=url,
                ))
            return comments

        if self.platform == "Facebook":
            rows = thread_rows if thread_rows is not None else self._facebook_dom_rows(url)
            comments = []
            for row in rows:
                if not row.get("comment"):
                    continue
                author, author_date = self._clean_facebook_author(row.get("author"))
                raw_date = row.get("date") or author_date
                commented_at = (
                    relative_social_date_iso(raw_date)
                    or social_date_iso(raw_date)
                    or raw_date
                    or None
                )
                comments.append(PublicComment(
                    author=author or None,
                    comment=str(row["comment"]).strip(),
                    commented_at=commented_at,
                    likes=self._count(row.get("likes")),
                    reply_count=self._count(row.get("replies")),
                    comment_type=(
                        row.get("comment_type")
                        if row.get("comment_type") in {"parent", "reply"}
                        else "parent"
                    ),
                    source_url=url,
                ))
            return comments

        target_match = re.search(r"/post/([^/?#]+)", url, re.I)
        target_code = target_match.group(1) if target_match else ""
        rows = thread_rows if thread_rows is not None else self._threads_dom_rows(target_code)
        if not any(str(row.get("code") or "").casefold() == target_code.casefold() for row in rows):
            return []
        comments = []
        for row in rows:
            if row.get("code") == target_code or not row.get("comment"):
                continue
            comments.append(PublicComment(
                author=(row.get("author") or "").lstrip("@") or None,
                comment=str(row["comment"]).strip(),
                commented_at=row.get("date") or None,
                likes=self._count(row.get("likes")),
                reply_count=self._count(row.get("replies")),
                comment_type=row.get("comment_type") if row.get("comment_type") in {"parent", "reply"} else "parent",
                source_url=url,
            ))
        return comments

    @staticmethod
    def _merge_comments(*groups: list[PublicComment]) -> list[PublicComment]:
        merged: list[PublicComment] = []
        positions: dict[tuple[str, str], int] = {}
        text_positions: dict[str, list[int]] = {}

        def enrich(target: PublicComment, incoming: PublicComment) -> None:
            if not target.author and incoming.author:
                target.author = incoming.author
            if not target.commented_at and incoming.commented_at:
                target.commented_at = incoming.commented_at
            target.likes = max(int(target.likes or 0), int(incoming.likes or 0))
            target.reply_count = max(int(target.reply_count or 0), int(incoming.reply_count or 0))
            if incoming.comment_type == "reply":
                target.comment_type = "reply"

        for group in groups:
            for comment in group:
                text = " ".join(str(comment.comment or "").split()).casefold()
                author = str(comment.author or "").strip().lstrip("@").casefold()
                if not text:
                    continue
                duplicate_position = positions.get((author, text))
                if duplicate_position is None and not author and text_positions.get(text):
                    duplicate_position = text_positions[text][0]
                if duplicate_position is None and author:
                    duplicate_position = positions.get(("", text))
                if duplicate_position is not None:
                    enrich(merged[duplicate_position], comment)
                    continue
                position = len(merged)
                merged.append(comment)
                positions[(author, text)] = position
                text_positions.setdefault(text, []).append(position)
        return merged

    def collect(
        self,
        url: str,
        *,
        max_comments: int = MAX_COMMENTS_PER_URL,
        expected_comments: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> CommentCollection:
        try:
            return self._collect_once(
                url,
                max_comments=max_comments,
                expected_comments=expected_comments,
                progress_callback=progress_callback,
            )
        except WebDriverException as exc:
            if self._session_was_lost(exc):
                self._discard_driver()
                try:
                    return self._collect_once(
                        url,
                        max_comments=max_comments,
                        expected_comments=expected_comments,
                        progress_callback=progress_callback,
                    )
                except WebDriverException as retry_exc:
                    self._discard_driver()
                    raise CommentBrowserError(
                        f"Chrome MIDETA untuk {self.platform} terputus. "
                        "Jendelanya sudah dibuka ulang; jalankan pengambilan komentar sekali lagi."
                    ) from retry_exc
            raise CommentBrowserError(
                f"Chrome MIDETA untuk {self.platform} tidak dapat membaca halaman ini. "
                "Pastikan posting terlihat di Chrome MIDETA, lalu coba lagi."
            ) from exc

    def _collect_once(
        self,
        url: str,
        *,
        max_comments: int,
        expected_comments: int | None,
        progress_callback: Callable[[int, int], None] | None,
    ) -> CommentCollection:
        connector = get_platform_connector(url, self.platform)
        driver = self.start()
        if self.platform == "X":
            self._install_x_response_capture()
        driver.get(url)
        self._wait_for_page()
        if self.platform == "Facebook" and re.search(
            r"facebook\.com/(?:share/)?(?:r|v)/",
            url,
            re.I,
        ):
            try:
                WebDriverWait(driver, min(self.wait_seconds, 8)).until(
                    lambda active: not re.search(
                        r"facebook\.com/(?:share/)?(?:r|v)/",
                        str(active.current_url or ""),
                        re.I,
                    )
                )
                time.sleep(0.8)
            except WebDriverException:
                pass
        current_url = driver.current_url or url
        if self.platform == "Threads":
            current_url = self._resolve_threads_permalink(driver, url)
        if self.platform == "Facebook":
            self._prepare_facebook_comments()
        if self.platform == "X":
            self._prepare_x_comments()
        if self.platform == "Threads":
            target_match = re.search(r"/post/([^/?#]+)", current_url, re.I)
        elif self.platform == "X":
            target_match = re.search(r"/status/(\d+)", current_url, re.I)
        else:
            target_match = None
        target_code = target_match.group(1) if target_match else ""
        if self.platform == "Threads" and not target_code:
            return CommentCollection(
                url=url,
                platform=self.platform,
                status=FieldStatus.NOT_PUBLIC,
                reason="Permalink posting Threads target tidak dapat dibaca. Pastikan URL share masih aktif.",
            )
        if self.platform == "Threads":
            active_permalink = self._activate_threads_target(driver, current_url, target_code)
            if not active_permalink:
                return CommentCollection(
                    url=current_url,
                    platform=self.platform,
                    status=FieldStatus.NOT_PUBLIC,
                    reason="Chrome Threads tidak berada di posting target, sehingga pengambilan dihentikan.",
                )
            current_url = active_permalink
        thread_rows = (
            self._load_conversation(
                target_code,
                current_url,
                max_comments=max_comments,
                progress_callback=progress_callback,
            )
            if self.platform == "Facebook"
            else self._load_conversation(
                target_code,
                max_comments=max_comments,
                expected_comments=expected_comments,
                progress_callback=progress_callback,
            )
            if self.platform == "X"
            else self._load_conversation(
                target_code,
                max_comments=max_comments,
                progress_callback=progress_callback,
            )
        )
        if not isinstance(thread_rows, list):
            thread_rows = []
        target_rows_present = (
            self.platform != "Threads"
            or any(
                str(row.get("code") or "").casefold() == target_code.casefold()
                and bool(row.get("is_target"))
                for row in thread_rows
            )
        )
        structured_comments = (
            connector._platform_comments(driver.page_source, current_url)
            if target_rows_present
            else []
        )
        if self.platform in {"Facebook", "Threads", "X"}:
            dom_comments = self._dom_comments(current_url, thread_rows)
            comments = self._merge_comments(structured_comments, dom_comments)
        else:
            comments = structured_comments or self._dom_comments(current_url)
        comments = comments[:max_comments]
        if progress_callback is not None:
            progress_callback(len(comments), max_comments)
        if not comments:
            login_hint = ""
            if not self.is_logged_in(open_platform=False):
                login_hint = f" Login di Chrome {self.platform}, pastikan posting target terlihat, lalu coba lagi."
            return CommentCollection(
                url=current_url,
                platform=self.platform,
                status=FieldStatus.NOT_PUBLIC,
                reason=f"Posting target atau komentarnya belum dapat dibaca dari percakapan ini.{login_hint}",
            )
        return CommentCollection(
            url=current_url,
            platform=self.platform,
            comments=comments,
            status=FieldStatus.AVAILABLE,
            reason=(
                f"X menampilkan {len(comments):,} dari sekitar {expected_comments:,} balasan. "
                "Sebagian balasan mungkin disembunyikan, dihapus, berasal dari akun privat, atau belum diberikan X ke sesi ini."
                if self.platform == "X" and expected_comments and len(comments) < expected_comments
                else None
            ),
        )
