"""TikTok enrichment through a dedicated, user-authenticated Chrome profile."""
from __future__ import annotations

import json
import os
import re
import signal
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
import websocket

from src.config import DATA_DIR
from src.connectors.base import BaseConnector
from src.connectors.tiktok import TikTokConnector
from src.dates import social_datetime_iso
from src.models import DataField, FieldStatus, SocialResult


TIKTOK_PROFILE_DIR = DATA_DIR / "browser_profiles" / "tiktok_direct"


class TikTokBrowserError(RuntimeError):
    pass


class TikTokLoginRequired(TikTokBrowserError):
    pass


class TikTokAccessDenied(TikTokBrowserError):
    pass


class ChromeDevToolsSession:
    """Small local Chrome DevTools client used without ChromeDriver/Selenium."""

    def __init__(self, websocket_url: str, timeout: float = 20):
        self.timeout = timeout
        self._message_id = 0
        try:
            self._socket = websocket.create_connection(
                websocket_url,
                timeout=timeout,
                suppress_origin=True,
            )
        except (OSError, websocket.WebSocketException) as exc:
            raise TikTokBrowserError("Sesi Chrome TikTok tidak dapat dihubungkan ke MIDETA.") from exc
        self.command("Page.enable")
        self.command("Runtime.enable")
        self.command("Network.enable")

    def command(self, method: str, params: dict | None = None) -> dict:
        self._message_id += 1
        message_id = self._message_id
        payload = {"id": message_id, "method": method}
        if params:
            payload["params"] = params
        try:
            self._socket.send(json.dumps(payload))
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                self._socket.settimeout(max(0.1, deadline - time.monotonic()))
                response = json.loads(self._socket.recv())
                if response.get("id") != message_id:
                    continue
                if response.get("error"):
                    raise TikTokBrowserError(
                        f"Chrome tidak dapat menjalankan {method}: {response['error'].get('message', 'unknown error')}"
                    )
                return response.get("result") or {}
        except TikTokBrowserError:
            raise
        except (OSError, ValueError, websocket.WebSocketException) as exc:
            raise TikTokBrowserError("Koneksi ke Chrome TikTok terputus.") from exc
        raise TikTokBrowserError("Chrome TikTok terlalu lama merespons.")

    def evaluate(self, expression: str):
        response = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        if response.get("exceptionDetails"):
            raise TikTokBrowserError("Halaman TikTok belum siap dibaca.")
        return (response.get("result") or {}).get("value")

    def navigate(self, url: str) -> None:
        self.command("Page.navigate", {"url": url})

    def page_source(self) -> str:
        return str(self.evaluate("document.documentElement ? document.documentElement.outerHTML : ''") or "")

    def current_url(self) -> str:
        return str(self.evaluate("location.href") or "")

    def page_snapshot(self) -> dict[str, str]:
        value = self.evaluate(
            "({title: document.title || '', body: document.body ? document.body.innerText : '', "
            "source: document.documentElement ? document.documentElement.outerHTML : ''})"
        )
        return value if isinstance(value, dict) else {"title": "", "body": "", "source": ""}

    def cookies(self, urls: list[str]) -> list[dict]:
        return list(self.command("Network.getCookies", {"urls": urls}).get("cookies") or [])

    def ping(self) -> bool:
        return self.evaluate("1") == 1

    def close(self) -> None:
        try:
            self._socket.close()
        except (OSError, websocket.WebSocketException):
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
    source: str = "browser"
    warning: str | None = None


def build_tiktok_browser_result(url: str, metrics: TikTokBrowserMetrics) -> SocialResult:
    if metrics.source == "free":
        note = (
            "TikTok diperiksa tanpa login. Caption dan author memakai metadata publik TikTok; "
            "engagement dan followers memakai layanan gratis Apify jika token tersedia."
        )
    else:
        note = (
            "TikTok diperiksa melalui video dan profil author di browser MIDETA yang sudah login. "
            "Setiap engagement dicocokkan dengan ID video target."
        )
    if metrics.warning:
        note = f"{note} {metrics.warning}"
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
        note=note,
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
        self._session: ChromeDevToolsSession | None = None
        self._chrome_process: subprocess.Popen | None = None
        self._debug_port: int | None = None
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
        if self._session is None:
            return False
        try:
            return self._session.ping()
        except TikTokBrowserError:
            self._session.close()
            self._session = None
            return False

    @staticmethod
    def _chrome_binary() -> str | None:
        candidates = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        )
        return next((str(candidate) for candidate in candidates if candidate and Path(candidate).exists()), None)

    def _chrome_command(self, binary: str, port: int) -> list[str]:
        command = [
            binary,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={self.profile_dir.resolve()}",
            "--profile-directory=Default",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self.headless:
            command.append("--headless=new")
        command.append("https://www.tiktok.com/login")
        return command

    @staticmethod
    def _wait_for_debug_port(port: int, seconds: float = 10) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    return True
            except OSError:
                time.sleep(0.15)
        return False

    @property
    def _active_port_path(self) -> Path:
        return self.profile_dir / "DevToolsActivePort"

    def _active_debug_port(self) -> int | None:
        try:
            first_line = self._active_port_path.read_text(encoding="utf-8").splitlines()[0].strip()
            port = int(first_line)
        except (OSError, ValueError, IndexError):
            return None
        return port if port > 0 and self._wait_for_debug_port(port, seconds=0.4) else None

    def _wait_for_active_debug_port(self, seconds: float = 10) -> int | None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            port = self._active_debug_port()
            if port is not None:
                return port
            time.sleep(0.15)
        return None

    def _legacy_profile_pid(self) -> int | None:
        """Return the old Chrome PID only when it owns this exact MIDETA profile."""
        try:
            lock_target = self.profile_dir.joinpath("SingletonLock").readlink().name
            match = re.search(r"-(\d+)$", lock_target)
            if not match:
                return None
            pid = int(match.group(1))
            process = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        profile_argument = f"--user-data-dir={self.profile_dir.resolve()}"
        return pid if process.returncode == 0 and profile_argument in process.stdout else None

    def _close_legacy_profile(self) -> bool:
        pid = self._legacy_profile_pid()
        if pid is None or pid == os.getpid():
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return False
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.1)
        return True

    @staticmethod
    def _debug_json(port: int, path: str) -> object:
        request = Request(f"http://127.0.0.1:{port}{path}", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise TikTokBrowserError("Chrome TikTok belum siap menerima koneksi lokal.") from exc

    def _attach_session(self, port: int) -> ChromeDevToolsSession:
        targets = self._debug_json(port, "/json/list")
        if not isinstance(targets, list):
            raise TikTokBrowserError("Tab Chrome TikTok tidak ditemukan.")
        pages = [
            item
            for item in targets
            if isinstance(item, dict)
            and item.get("type") == "page"
            and item.get("webSocketDebuggerUrl")
        ]
        target = next(
            (
                item
                for item in pages
                if "tiktok.com" in str(item.get("url") or "").casefold()
            ),
            pages[0] if pages else None,
        )
        if not target:
            raise TikTokBrowserError("Tab Chrome TikTok tidak dapat dihubungkan.")
        return ChromeDevToolsSession(str(target["webSocketDebuggerUrl"]), timeout=self.wait_seconds + 10)

    def start(self) -> ChromeDevToolsSession:
        if self.is_running():
            return self._session
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        reusable_port = self._debug_port or self._active_debug_port()
        if reusable_port is not None:
            try:
                self._session = self._attach_session(reusable_port)
                self._debug_port = reusable_port
                return self._session
            except TikTokBrowserError:
                if self._session is not None:
                    self._session.close()
                self._session = None
                self._debug_port = None
        binary = self._chrome_binary()
        if not binary:
            raise TikTokBrowserError("Google Chrome tidak ditemukan di komputer ini.")
        try:
            self._active_port_path.unlink(missing_ok=True)
            self._chrome_process = subprocess.Popen(
                self._chrome_command(binary, 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._debug_port = self._wait_for_active_debug_port()
            if self._debug_port is None:
                raise TikTokBrowserError(
                    "Sesi TikTok lama masih terbuka dan belum dapat disambungkan. Tutup jendela Chrome TikTok itu satu kali, lalu coba lagi; login yang sudah tersimpan tidak hilang."
                )
            self._session = self._attach_session(self._debug_port)
        except TikTokBrowserError:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise TikTokBrowserError(
                "Chrome TikTok MIDETA tidak dapat dibuka. Tutup jendela Chrome TikTok MIDETA yang lama, lalu coba lagi."
            ) from exc
        return self._session

    def open_login(self) -> None:
        self.start().navigate("https://www.tiktok.com/login")
        self._wait_for_page()

    def is_logged_in(self) -> bool:
        session = self.start()
        try:
            cookies = session.cookies(["https://www.tiktok.com/"])
        except TikTokBrowserError:
            return False
        session_names = {"sessionid", "sessionid_ss", "sid_tt", "sid_guard"}
        logged_in = any(cookie.get("name") in session_names and cookie.get("value") for cookie in cookies)
        if not logged_in and session.current_url().casefold() in {"", "about:blank"}:
            session.navigate("https://www.tiktok.com/login")
        return logged_in

    def close(self) -> None:
        if self._session is None:
            reusable_port = self._debug_port or self._active_debug_port()
            if reusable_port is not None:
                try:
                    self._session = self._attach_session(reusable_port)
                except TikTokBrowserError:
                    self._session = None
        if self._session is None:
            self._close_legacy_profile()
        if self._session is not None:
            try:
                self._session.command("Browser.close")
            except TikTokBrowserError:
                pass
            finally:
                self._session.close()
                self._session = None
        if self._chrome_process is not None and self._chrome_process.poll() is None:
            try:
                self._chrome_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._chrome_process.terminate()
        self._chrome_process = None
        self._debug_port = None

    @staticmethod
    def _page_is_access_denied(source: str, title: str = "", body: str = "") -> bool:
        page = " ".join((source, title, body)).casefold()
        return (
            "access to www.tiktok.com was denied" in page
            or "http error 403" in page
            or ("access denied" in page and "tiktok" in page)
        )

    def _raise_if_access_denied(self) -> None:
        try:
            snapshot = self.start().page_snapshot()
        except TikTokBrowserError:
            return
        if self._page_is_access_denied(snapshot["source"], snapshot["title"], snapshot["body"]):
            raise TikTokAccessDenied(
                "TikTok menolak sesi browser dengan HTTP 403. Antrean dijeda agar akun tidak terus menerima request. "
                "Tutup sesi TikTok, ganti akun atau tunggu pembatasan selesai, lalu coba lagi."
            )

    def _wait_for_page(self) -> None:
        session = self.start()
        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            try:
                if session.evaluate("document.readyState") in {"interactive", "complete"}:
                    break
            except TikTokBrowserError:
                pass
            time.sleep(0.2)
        time.sleep(1.5)

    def _dom_text(self, selectors: tuple[str, ...]) -> str | None:
        selector_json = json.dumps(list(selectors))
        try:
            value = self.start().evaluate(
                f"""
                (() => {{
                for (const selector of {selector_json}) {{
                  const node = document.querySelector(selector);
                  if (!node) continue;
                  const text = (node.textContent || node.innerText || node.getAttribute('aria-label') || '').trim();
                  if (text) return text;
                }}
                return null;
                }})()
                """,
            )
        except TikTokBrowserError:
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
        session = self.start()
        session.navigate(url)
        self._wait_for_page()
        self._raise_if_access_denied()
        if not self.is_logged_in():
            raise TikTokLoginRequired("Login TikTok belum selesai di Chrome MIDETA.")
        current_url = session.current_url()
        if "/login" in current_url.casefold():
            raise TikTokLoginRequired("TikTok mengalihkan halaman ke login. Login kembali lalu lanjutkan proses.")
        source = ""
        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            source = session.page_source()
            if (
                TikTokConnector._target_video_item(source, video_id) is not None
                or self._dom_text(('[data-e2e="browse-video-desc"]',))
            ):
                break
            time.sleep(0.3)
        source_metrics = self._video_metrics_from_source(source or session.page_source(), video_id)
        dom_metrics = self._post_dom_metrics()
        metrics = self._merge(source_metrics, dom_metrics)
        if not metrics.caption:
            source = source or session.page_source()
            soup = BeautifulSoup(source, "lxml")
            description = BaseConnector._meta(
                soup,
                'meta[property="og:description"]',
                'meta[name="description"]',
            )
            metrics.caption = TikTokConnector()._platform_caption(source, url, description)
        return metrics

    def _profile_video_views_from_dom(self, video_id: str) -> int | None:
        try:
            value = self.start().evaluate(
                f"""
                (() => {{
                const videoId = {json.dumps(video_id)};
                const links = [...document.querySelectorAll('a[href]')]
                  .filter(link => (link.getAttribute('href') || '').includes(`/video/${videoId}`));
                for (const link of links) {{
                  const card = link.closest('[data-e2e="user-post-item"]') || link;
                  const count = card.querySelector('[data-e2e="video-views"], strong, span');
                  if (!count) continue;
                  const text = (count.textContent || count.innerText || '').trim();
                  if (text) return text;
                }}
                return null;
                }})()
                """,
            )
        except TikTokBrowserError:
            return None
        return self._count(str(value)) if value else None

    def _profile_metrics(self, username: str, video_id: str) -> tuple[int | None, int | None]:
        cache_key = username.casefold()
        cached = self._followers_cache.get(cache_key)
        followers = cached[1] if cached and time.monotonic() - cached[0] <= 300 else None
        session = self.start()
        session.navigate(f"https://www.tiktok.com/@{username}")
        self._wait_for_page()
        self._raise_if_access_denied()
        if not self.is_logged_in():
            raise TikTokLoginRequired("Sesi TikTok berakhir saat membuka profil author.")
        source = ""
        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            source = session.page_source()
            if (
                self._profile_followers_from_source(source, username) is not None
                or self._dom_text(('[data-e2e="followers-count"]',))
            ):
                break
            time.sleep(0.3)
        source = source or session.page_source()
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
            session = self.start()
            session.navigate(url)
            self._wait_for_page()
            self._raise_if_access_denied()
            if not self.is_logged_in():
                raise TikTokLoginRequired("Login TikTok berakhir saat membuka URL pendek.")
            resolved_url = session.current_url().strip()
            video_id = TikTokConnector._video_id(resolved_url)
            if not video_id:
                raise TikTokBrowserError("URL pendek TikTok belum mengarah ke video atau foto yang dapat dibaca.")
            url = resolved_url
        url_username = self._username_from_url(url)
        post = self._post_metrics(url, video_id)
        post.username = post.username or url_username or self._username(author)
        if not post.username:
            raise TikTokBrowserError("Username TikTok tidak dapat dibaca dari URL atau halaman video.")
        post.followers, profile_views = self._profile_metrics(post.username, video_id)
        if post.views is None:
            post.views = profile_views
        return post
