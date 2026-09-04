"""Comment collection through a dedicated Chrome profile."""
from __future__ import annotations

import atexit
import re
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait

from src.config import DATA_DIR
from src.connectors import get_platform_connector
from src.connectors.base import BaseConnector
from src.models import CommentCollection, FieldStatus, PublicComment


class CommentBrowserError(RuntimeError):
    pass


class CommentBrowserLoginRequired(CommentBrowserError):
    pass


class CommentBrowserCollector:
    LOGIN_URLS = {
        "Threads": "https://www.threads.com/login/",
        "X": "https://x.com/i/flow/login",
    }
    HOME_URLS = {
        "Threads": "https://www.threads.com/",
        "X": "https://x.com/home",
    }
    LOGIN_COOKIES = {
        "Threads": {"sessionid", "ds_user_id"},
        "X": {"auth_token"},
    }

    def __init__(
        self,
        platform: str,
        profile_dir: Path | None = None,
        wait_seconds: int = 20,
        headless: bool = False,
    ):
        if platform not in self.LOGIN_URLS:
            raise ValueError("Browser komentar hanya tersedia untuk Threads dan X.")
        self.platform = platform
        self.profile_dir = Path(profile_dir or DATA_DIR / "browser_profiles" / platform.casefold())
        self.wait_seconds = wait_seconds
        self.headless = headless
        self.driver = None
        atexit.register(self.close)

    @staticmethod
    def _count(value) -> int:
        if value in (None, ""):
            return 0
        match = re.search(r"\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?", str(value), re.I)
        return BaseConnector._human_count(match.group(0)) if match else 0

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
            raise CommentBrowserError(
                f"Chrome MIDETA untuk {self.platform} tidak dapat dibuka. Tutup jendela lama, lalu coba lagi."
            ) from exc
        return self.driver

    def open_login(self) -> bool:
        """Open the saved session, showing login only when it has expired."""
        driver = self.start()
        try:
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
            expected_host = "threads.com" if self.platform == "Threads" else "x.com"
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
        if self.driver is None:
            return
        try:
            self.driver.quit()
        except WebDriverException:
            pass
        finally:
            self.driver = None

    def _wait_for_page(self) -> None:
        WebDriverWait(self.start(), self.wait_seconds).until(
            lambda active: active.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        time.sleep(1.2)

    def _load_conversation(self) -> None:
        driver = self.start()
        for _ in range(12):
            try:
                reached_end = driver.execute_script(
                    """
                    const labels = [
                      'show replies', 'show more replies', 'view replies', 'view more replies',
                      'tampilkan balasan', 'lihat balasan', 'balasan lainnya',
                      'show more', 'view more', 'tampilkan lainnya', 'lihat lainnya'
                    ];
                    for (const node of document.querySelectorAll('button, [role="button"]')) {
                      const text = (node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase();
                      if (labels.some(label => text.includes(label))) node.click();
                    }
                    const endLabels = ['related threads', 'thread terkait', 'threads terkait'];
                    const end = Array.from(document.querySelectorAll('div, span')).find(node => {
                      const text = (node.textContent || '').trim().toLowerCase();
                      return endLabels.includes(text) && !Array.from(node.children).some(child =>
                        (child.textContent || '').trim().toLowerCase() === text
                      );
                    });
                    if (end) {
                      end.scrollIntoView({block: 'end'});
                      return true;
                    }
                    window.scrollBy(0, Math.max(window.innerHeight * 0.85, 600));
                    return false;
                    """
                )
            except WebDriverException:
                break
            time.sleep(0.7)
            if reached_end:
                break

    def _x_dom_rows(self) -> list[dict]:
        return self.start().execute_script(
            r"""
            const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
            const targetTop = articles.length ? articles[0].getBoundingClientRect().top : Number.NEGATIVE_INFINITY;
            const endLabels = ['discover more', 'more tweets', 'relevant people', 'temukan lainnya', 'tweet lainnya'];
            const endTops = Array.from(document.querySelectorAll('div, span'))
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
            const endTop = endTops.length ? Math.min(...endTops) : Number.POSITIVE_INFINITY;

            const targetAnchor = anchors.find(anchor => {
              const href = anchor.href || '';
              const match = href.match(/\/(@[^/]+)\/post\/([^/?#]+)/);
              return Boolean(match && match[2] === targetCode);
            });
            if (!targetAnchor) return [];
            const targetBox = targetAnchor.closest('[data-pressable-container="true"]') || targetAnchor;
            const targetTop = targetBox.getBoundingClientRect().top;
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
              if (top >= endTop || (match[2] !== targetCode && top <= targetTop)) continue;
              seen.add(match[2]);
              const candidates = Array.from(box.querySelectorAll('[dir="auto"]'))
                .map(node => (node.innerText || '').trim())
                .filter(text => text && text !== match[1].slice(1));
              candidates.sort((a, b) => b.length - a.length);
              const iconMetric = labels => {
                const icon = Array.from(box.querySelectorAll('svg')).find(svg =>
                  labels.some(label => (svg.getAttribute('aria-label') || '').toLowerCase().includes(label)));
                if (!icon) return '';
                const parent = icon.closest('button, [role="button"], div');
                return parent ? (parent.getAttribute('aria-label') || parent.innerText || '') : '';
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
                date: box.querySelector('time')?.getAttribute('datetime') || anchor.getAttribute('title') || '',
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

    def _dom_comments(self, url: str) -> list[PublicComment]:
        if self.platform == "X":
            target_match = re.search(r"/status/(\d+)", url)
            target_id = target_match.group(1) if target_match else ""
            target_author_match = re.search(r"x\.com/([^/]+)/status/", url, re.I)
            target_author = target_author_match.group(1) if target_author_match else ""
            rows = self._x_dom_rows()
            comments = []
            for row in rows:
                status_match = re.search(r"/status/(\d+)", row.get("href") or "")
                if not status_match or status_match.group(1) == target_id or not row.get("comment"):
                    continue
                context = str(row.get("context") or "")
                is_parent = not target_author or f"@{target_author}".casefold() in context.casefold()
                comments.append(PublicComment(
                    author=(row.get("author") or "").lstrip("@") or None,
                    comment=str(row["comment"]).strip(),
                    commented_at=row.get("date") or None,
                    likes=self._count(row.get("likes")),
                    reply_count=self._count(row.get("replies")),
                    comment_type="parent" if is_parent else "reply",
                    source_url=url,
                ))
            return comments

        target_match = re.search(r"/post/([^/?#]+)", url, re.I)
        target_code = target_match.group(1) if target_match else ""
        rows = self._threads_dom_rows(target_code)
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

    def collect(self, url: str) -> CommentCollection:
        connector = get_platform_connector(url, self.platform)
        driver = self.start()
        driver.get(url)
        self._wait_for_page()
        self._load_conversation()
        comments = connector._platform_comments(driver.page_source, driver.current_url or url)
        if not comments:
            comments = self._dom_comments(driver.current_url or url)
        if not comments:
            login_hint = ""
            if not self.is_logged_in(open_platform=False):
                login_hint = f" Login di Chrome {self.platform}, pastikan posting target terlihat, lalu coba lagi."
            return CommentCollection(
                url=driver.current_url or url,
                platform=self.platform,
                status=FieldStatus.NOT_PUBLIC,
                reason=f"Posting target atau komentarnya belum dapat dibaca dari percakapan ini.{login_hint}",
            )
        return CommentCollection(
            url=driver.current_url or url,
            platform=self.platform,
            comments=comments,
            status=FieldStatus.AVAILABLE,
        )
