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
    THREADS_MAX_SCROLL_ROUNDS = 180
    OTHER_MAX_SCROLL_ROUNDS = 30
    END_STABLE_ROUNDS = 3
    IDLE_STABLE_ROUNDS = 8
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
            stored[code].update({key: value for key, value in row.items() if value not in (None, "")})
        return added

    def _load_conversation(self, target_code: str = "") -> list[dict]:
        driver = self.start()
        thread_rows: dict[str, dict] = {}
        stable_rounds = 0
        idle_rounds = 0
        previous_scroll = None
        previous_height = None
        max_rounds = self.THREADS_MAX_SCROLL_ROUNDS if self.platform == "Threads" else self.OTHER_MAX_SCROLL_ROUNDS
        for _ in range(max_rounds):
            added = 0
            if self.platform == "Threads" and target_code:
                try:
                    added += self._merge_thread_rows(thread_rows, self._threads_dom_rows(target_code))
                except WebDriverException:
                    pass
            try:
                state = driver.execute_script(
                    """
                    const labels = [
                      'show replies', 'show more replies', 'view replies', 'view more replies',
                      'tampilkan balasan', 'lihat balasan', 'balasan lainnya',
                      'show more', 'view more', 'see more',
                      'tampilkan lainnya', 'lihat lainnya', 'lihat komentar lainnya'
                    ];
                    let clicked = 0;
                    for (const node of document.querySelectorAll('button, [role="button"]')) {
                      const text = (node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase();
                      const replyLoader = /^(show|view|see|load|tampilkan|lihat).*?(repl|balasan|komentar|more|lain)/i.test(text);
                      if (labels.some(label => text.includes(label)) || replyLoader) {
                        node.click();
                        clicked += 1;
                      }
                    }
                    const endLabels = ['related threads', 'thread terkait', 'threads terkait'];
                    const end = Array.from(document.querySelectorAll('div, span')).find(node => {
                      const text = (node.textContent || '').trim().toLowerCase();
                      return endLabels.includes(text) && !Array.from(node.children).some(child =>
                        (child.textContent || '').trim().toLowerCase() === text
                      );
                    });
                    const reachedEnd = Boolean(end && end.getBoundingClientRect().top <= window.innerHeight * 1.1);
                    window.scrollBy(0, Math.max(window.innerHeight * 0.85, 600));
                    return {
                      reachedEnd,
                      clicked,
                      scrollY: window.scrollY,
                      height: document.documentElement.scrollHeight
                    };
                    """
                )
            except WebDriverException:
                break
            time.sleep(0.7)

            if self.platform == "Threads" and target_code:
                try:
                    added += self._merge_thread_rows(thread_rows, self._threads_dom_rows(target_code))
                except WebDriverException:
                    pass

            state = state if isinstance(state, dict) else {"reachedEnd": bool(state)}
            scroll_position = state.get("scrollY")
            page_height = state.get("height")
            moved = previous_scroll is None or scroll_position != previous_scroll
            grew = previous_height is None or page_height != previous_height
            clicked = bool(state.get("clicked"))
            stable_rounds = stable_rounds + 1 if added == 0 else 0
            idle_rounds = idle_rounds + 1 if not (added or moved or grew or clicked) else 0
            previous_scroll = scroll_position
            previous_height = page_height

            if state.get("reachedEnd") and stable_rounds >= self.END_STABLE_ROUNDS:
                break
            if idle_rounds >= self.IDLE_STABLE_ROUNDS:
                break
        return list(thread_rows.values())

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
            const pagePath = decodeURIComponent(window.location.pathname || '');
            const pageMatch = pagePath.match(/\/@[^/]+\/post\/([^/?#]+)/);
            if (!targetAnchor && (!pageMatch || pageMatch[1] !== targetCode)) return [];
            const targetBox = targetAnchor
              ? (targetAnchor.closest('[data-pressable-container="true"]') || targetAnchor)
              : null;
            const targetTop = targetBox ? targetBox.getBoundingClientRect().top : Number.NEGATIVE_INFINITY;
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

    def _dom_comments(self, url: str, thread_rows: list[dict] | None = None) -> list[PublicComment]:
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
        seen: set[tuple[str, str]] = set()
        text_authors: dict[str, set[str]] = {}
        for group in groups:
            for comment in group:
                text = " ".join(str(comment.comment or "").split()).casefold()
                author = str(comment.author or "").strip().lstrip("@").casefold()
                if not text:
                    continue
                authors = text_authors.get(text, set())
                if (author, text) in seen or (not author and authors) or (author and "" in authors):
                    continue
                seen.add((author, text))
                text_authors.setdefault(text, set()).add(author)
                merged.append(comment)
        return merged

    def collect(self, url: str) -> CommentCollection:
        connector = get_platform_connector(url, self.platform)
        driver = self.start()
        driver.get(url)
        self._wait_for_page()
        current_url = driver.current_url or url
        target_match = re.search(r"/post/([^/?#]+)", current_url, re.I) if self.platform == "Threads" else None
        target_code = target_match.group(1) if target_match else ""
        thread_rows = self._load_conversation(target_code)
        if not isinstance(thread_rows, list):
            thread_rows = []
        structured_comments = connector._platform_comments(driver.page_source, current_url)
        if self.platform == "Threads":
            dom_comments = self._dom_comments(current_url, thread_rows)
            comments = self._merge_comments(structured_comments, dom_comments)
        else:
            comments = structured_comments or self._dom_comments(current_url)
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
        )
