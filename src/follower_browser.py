# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Follower totals from social profile pages in saved Chrome sessions."""
from __future__ import annotations

import atexit
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait

from src.config import DATA_DIR
from src.connectors.base import BaseConnector


FOLLOWER_PLATFORMS = (
    "Instagram",
    "Facebook",
    "TikTok",
    "Threads",
    "X",
    "YouTube",
    "LinkedIn",
)


class FollowerBrowserError(RuntimeError):
    pass


class FollowerLoginRequired(FollowerBrowserError):
    pass


class FollowerProfileUnavailable(FollowerBrowserError):
    pass


class ProfileFollowersCollector:
    """Read one profile at a time without sharing credentials with MIDETA."""

    RUNTIME_VERSION = 2
    LOGIN_URLS = {
        "Instagram": "https://www.instagram.com/accounts/login/",
        "Facebook": "https://www.facebook.com/login/",
        "TikTok": "https://www.tiktok.com/login",
        "Threads": "https://www.threads.com/login/",
        "X": "https://x.com/i/flow/login",
        "YouTube": "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/",
        "LinkedIn": "https://www.linkedin.com/login",
    }
    HOME_URLS = {
        "Instagram": "https://www.instagram.com/",
        "Facebook": "https://www.facebook.com/",
        "TikTok": "https://www.tiktok.com/",
        "Threads": "https://www.threads.com/",
        "X": "https://x.com/home",
        "YouTube": "https://www.youtube.com/",
        "LinkedIn": "https://www.linkedin.com/feed/",
    }
    LOGIN_COOKIES = {
        "Instagram": {"sessionid"},
        "Facebook": {"c_user"},
        "TikTok": {"sessionid", "sessionid_ss", "sid_tt"},
        "Threads": {"sessionid", "ds_user_id"},
        "X": {"auth_token"},
        "YouTube": {"SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "SID", "__Secure-3PSID"},
        "LinkedIn": {"li_at"},
    }
    PLATFORM_HOSTS = {
        "Instagram": ("instagram.com",),
        "Facebook": ("facebook.com", "fb.com"),
        "TikTok": ("tiktok.com",),
        "Threads": ("threads.com", "threads.net"),
        "X": ("x.com", "twitter.com"),
        "YouTube": ("youtube.com", "youtu.be"),
        "LinkedIn": ("linkedin.com",),
    }
    PROFILE_DIR_NAMES = {
        # Reuse MIDETA's existing saved sessions where those platforms already
        # have browser-based enrichment or comment collection.
        "Instagram": "instagram",
        "Facebook": "facebook",
        "TikTok": "tiktok_followers",
        "Threads": "threads",
        "X": "x",
        "YouTube": "youtube_followers",
        "LinkedIn": "linkedin_followers",
    }
    PROFILE_SELECTORS = {
        "Instagram": ("header", "main"),
        "Facebook": ("[role='main']", "main"),
        "TikTok": ("[data-e2e='user-profile']", "main"),
        "Threads": ("main", "[role='main']"),
        "X": ("[data-testid='primaryColumn']", "main"),
        "YouTube": ("#page-header", "#channel-header", "main"),
        "LinkedIn": ("main", ".scaffold-layout__main"),
    }
    COUNT_LABELS = {
        "Instagram": ("followers?", "pengikut"),
        "Facebook": ("followers?", "pengikut"),
        "TikTok": ("followers?", "pengikut"),
        "Threads": ("followers?", "pengikut"),
        "X": ("followers?", "pengikut"),
        "YouTube": ("subscribers?", "pelanggan"),
        "LinkedIn": ("followers?", "pengikut"),
    }
    JSON_COUNT_KEYS = {
        "Instagram": ("follower_count", "followers_count"),
        "Facebook": ("follower_count", "followers_count"),
        "TikTok": ("followerCount", "follower_count", "fans"),
        "Threads": ("follower_count", "followers_count"),
        "X": ("followers_count",),
        "YouTube": ("subscriberCount",),
        "LinkedIn": ("followerCount", "follower_count"),
    }

    def __init__(
        self,
        platform: str,
        profile_dir: Path | None = None,
        wait_seconds: int = 20,
        headless: bool = False,
    ):
        if platform not in FOLLOWER_PLATFORMS:
            raise ValueError(f"Followers Checker belum mendukung platform {platform}.")
        self.platform = platform
        self.profile_dir = Path(
            profile_dir
            or DATA_DIR / "browser_profiles" / self.PROFILE_DIR_NAMES[platform]
        )
        self.wait_seconds = wait_seconds
        self.headless = headless
        self.driver = None
        atexit.register(self.close)

    def is_running(self) -> bool:
        if self.driver is None:
            return False
        try:
            handles = self.driver.window_handles
            if not handles:
                self._discard_driver()
                return False
            try:
                current = self.driver.current_window_handle
            except (InvalidSessionIdException, NoSuchWindowException, WebDriverException):
                current = None
            if current not in handles:
                self.driver.switch_to.window(handles[-1])
            return True
        except (InvalidSessionIdException, NoSuchWindowException, WebDriverException):
            self._discard_driver()
            return False

    def _discard_driver(self) -> None:
        driver, self.driver = self.driver, None
        if driver is None:
            return
        try:
            driver.quit()
        except WebDriverException:
            pass

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
            raise FollowerBrowserError(
                f"Chrome MIDETA untuk {self.platform} tidak dapat dibuka. Tutup jendela lama, lalu coba lagi."
            ) from exc
        return self.driver

    def _wait_for_page(self) -> None:
        WebDriverWait(self.start(), self.wait_seconds).until(
            lambda active: active.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        time.sleep(1.1)

    def open_login(self) -> bool:
        """Show the platform login immediately and keep the session on disk."""
        driver = self.start()
        try:
            driver.get(self.LOGIN_URLS[self.platform])
            return self.is_logged_in(open_platform=False)
        except WebDriverException as exc:
            raise FollowerBrowserError(
                f"Sesi Chrome MIDETA untuk {self.platform} tidak dapat dibuka."
            ) from exc

    def is_logged_in(self, *, open_platform: bool = True) -> bool:
        driver = self.start()
        if open_platform:
            current_host = urlparse(str(getattr(driver, "current_url", "") or "")).netloc.casefold()
            if not any(host in current_host for host in self.PLATFORM_HOSTS[self.platform]):
                try:
                    driver.get(self.HOME_URLS[self.platform])
                    self._wait_for_page()
                except WebDriverException:
                    return False
        try:
            cookies = driver.get_cookies()
        except WebDriverException:
            return False
        names = {str(cookie.get("name") or "") for cookie in cookies if cookie.get("value")}
        return bool(names & self.LOGIN_COOKIES[self.platform])

    def close(self) -> None:
        self._discard_driver()

    @classmethod
    def platform_from_url(cls, url: str) -> str | None:
        """Detect a supported platform from its host, including invalid post URLs."""
        try:
            host = urlparse(str(url or "").strip()).netloc.casefold().split(":", 1)[0]
        except ValueError:
            return None
        return next(
            (
                platform
                for platform in FOLLOWER_PLATFORMS
                if any(
                    host == valid or host.endswith(f".{valid}")
                    for valid in cls.PLATFORM_HOSTS[platform]
                )
            ),
            None,
        )

    @classmethod
    def account_name_from_url(cls, platform: str | None, url: str) -> str:
        """Return a stable account handle/slug even when the profile is unavailable."""
        if platform not in FOLLOWER_PLATFORMS:
            return "Tidak tersedia"
        parsed = urlparse(str(url or "").strip())
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if platform == "Facebook":
            profile_id = parse_qs(parsed.query).get("id", [""])[0]
            if profile_id:
                return profile_id
            if parts and parts[0].casefold() in {"people", "pages"} and len(parts) > 1:
                return parts[1]
            return parts[0] if parts else "Tidak tersedia"
        if platform in {"Instagram", "TikTok", "Threads", "X"}:
            return parts[0].lstrip("@") if parts else "Tidak tersedia"
        if platform == "YouTube":
            if parts and parts[0].startswith("@"):
                return parts[0].lstrip("@")
            return parts[1] if len(parts) > 1 and parts[0].casefold() in {"channel", "c", "user"} else "Tidak tersedia"
        if platform == "LinkedIn":
            return parts[1] if len(parts) > 1 else "Tidak tersedia"
        return "Tidak tersedia"

    @classmethod
    def is_profile_url(cls, platform: str, url: str) -> bool:
        """Accept account/channel URLs while rejecting individual post URLs."""
        try:
            parsed = urlparse(str(url or "").strip())
        except ValueError:
            return False
        host = parsed.netloc.casefold().split(":", 1)[0]
        if parsed.scheme not in {"http", "https"} or not any(
            host == valid or host.endswith(f".{valid}")
            for valid in cls.PLATFORM_HOSTS.get(platform, ())
        ):
            return False
        parts = [part for part in parsed.path.split("/") if part]
        lowered = [part.casefold() for part in parts]
        if platform == "Instagram":
            return len(parts) == 1 and lowered[0] not in {"p", "reel", "reels", "stories", "explore", "accounts"}
        if platform == "TikTok":
            return len(parts) == 1 and parts[0].startswith("@")
        if platform == "Threads":
            return len(parts) == 1 and parts[0].startswith("@")
        if platform == "X":
            return len(parts) == 1 and lowered[0] not in {"home", "search", "explore", "i", "compose", "settings"}
        if platform == "YouTube":
            return bool(parts) and (parts[0].startswith("@") or lowered[0] in {"channel", "c", "user"})
        if platform == "LinkedIn":
            return len(parts) >= 2 and lowered[0] in {"company", "in", "school", "showcase"}
        if platform == "Facebook":
            post_markers = {"share", "reel", "watch", "posts", "videos", "groups", "permalink.php"}
            return bool(parts or parsed.query) and not any(part in post_markers for part in lowered)
        return False

    @staticmethod
    def _count_from_labeled_text(text: str, labels: tuple[str, ...]) -> int | None:
        if not text:
            return None
        normalized = re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()
        label_pattern = "|".join(labels)
        number = r"\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?"
        patterns = (
            rf"(?P<count>{number})\s*(?:{label_pattern})\b",
            rf"(?:{label_pattern})\s*[:\-]?\s*(?P<count>{number})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized, re.I)
            if match:
                return BaseConnector._human_count(match.group("count"))
        return None

    @classmethod
    def extract_follower_count(
        cls,
        platform: str,
        source: str,
        visible_sections: list[str] | tuple[str, ...] = (),
    ) -> int | None:
        """Prefer the visible profile header, then use structured page data."""
        labels = cls.COUNT_LABELS[platform]
        for text in visible_sections:
            value = cls._count_from_labeled_text(text, labels)
            if value is not None:
                return value

        # A full app payload can contain recommendations and the signed-in
        # viewer. Only TikTok and YouTube have sufficiently stable target-page
        # payloads for a fallback after the visible profile header was tried.
        if platform == "YouTube":
            labeled_source = cls._count_from_labeled_text(source[:500_000], labels)
            if labeled_source is not None:
                return labeled_source

        if platform not in {"TikTok", "YouTube"}:
            return None
        for key in cls.JSON_COUNT_KEYS[platform]:
            match = re.search(
                rf'["\']{re.escape(key)}["\']\s*:\s*(?:\{{[^{{}}]{{0,180}}?["\'](?:count|value)["\']\s*:\s*)?["\']?(\d[\d.,]*)',
                source,
                re.I,
            )
            if match:
                return BaseConnector._human_count(match.group(1))
        return None

    def _visible_profile_sections(self) -> list[str]:
        selectors = list(self.PROFILE_SELECTORS[self.platform])
        try:
            values = self.driver.execute_script(
                r"""
                const selectors = arguments[0] || [];
                const values = [];
                for (const selector of selectors) {
                  for (const node of document.querySelectorAll(selector)) {
                    const text = String(node.innerText || node.textContent || '').trim();
                    if (text && text.length <= 12000) values.push(text);
                  }
                }
                for (const selector of ['meta[property="og:description"]', 'meta[name="description"]']) {
                  const content = document.querySelector(selector)?.content || '';
                  if (content) values.unshift(content);
                }
                const labels = /(followers?|pengikut|subscribers?|pelanggan)/i;
                for (const node of document.querySelectorAll('a, span, div')) {
                  const text = String(node.innerText || node.textContent || '').trim();
                  if (text && text.length <= 220 && labels.test(text)) values.push(text);
                }
                return [...new Set(values)].slice(0, 12);
                """,
                selectors,
            )
        except WebDriverException:
            values = []
        return [str(value) for value in values] if isinstance(values, list) else []

    def collect_profile_followers(self, url: str) -> int | None:
        if not self.is_profile_url(self.platform, url):
            raise FollowerProfileUnavailable(
                f"URL bukan profil {self.platform}. Gunakan URL akun, bukan URL posting."
            )
        if not self.is_logged_in():
            raise FollowerLoginRequired(f"Login {self.platform} diperlukan.")
        driver = self.start()
        try:
            driver.get(str(url).strip())
            self._wait_for_page()
            if not self.is_logged_in(open_platform=False):
                raise FollowerLoginRequired(f"Sesi {self.platform} sudah tidak aktif.")
            current_host = urlparse(str(getattr(driver, "current_url", "") or "")).netloc.casefold()
            if not any(host in current_host for host in self.PLATFORM_HOSTS[self.platform]):
                raise FollowerProfileUnavailable("Profil dialihkan keluar dari platform tujuan.")
            source = str(driver.page_source or "")
            sections = self._visible_profile_sections()
        except (FollowerLoginRequired, FollowerProfileUnavailable):
            raise
        except WebDriverException as exc:
            raise FollowerBrowserError(f"Profil {self.platform} tidak dapat diproses.") from exc

        page_text = " ".join(sections).casefold()
        unavailable_markers = (
            "page isn't available",
            "page is not available",
            "halaman ini tidak tersedia",
            "this account doesn't exist",
            "akun ini tidak tersedia",
            "couldn't find this account",
            "profile not found",
            "channel does not exist",
        )
        if any(marker in page_text for marker in unavailable_markers):
            raise FollowerProfileUnavailable("Profil tidak tersedia atau sudah dihapus.")
        return self.extract_follower_count(self.platform, source, sections)
