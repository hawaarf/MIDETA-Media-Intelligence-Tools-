"""Comment collection through a dedicated Chrome profile."""
from __future__ import annotations

import atexit
import re
import time
from pathlib import Path
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait

from src.config import DATA_DIR, MAX_COMMENTS_PER_URL
from src.connectors import get_platform_connector
from src.connectors.base import BaseConnector
from src.dates import relative_social_date_iso, social_date_iso
from src.models import CommentCollection, FieldStatus, PublicComment


class CommentBrowserError(RuntimeError):
    pass


class CommentBrowserLoginRequired(CommentBrowserError):
    pass


class CommentBrowserCollector:
    RUNTIME_VERSION = 4
    THREADS_MAX_SCROLL_ROUNDS = 240
    FACEBOOK_MAX_SCROLL_ROUNDS = 240
    X_MAX_SCROLL_ROUNDS = 240
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
            updates = {key: value for key, value in row.items() if value not in (None, "")}
            if stored[code].get("comment_type") == "reply" and updates.get("comment_type") == "parent":
                updates.pop("comment_type")
            stored[code].update(updates)
        return added

    def _load_conversation(
        self,
        target_code: str = "",
        url: str = "",
        max_comments: int = MAX_COMMENTS_PER_URL,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict]:
        driver = self.start()
        thread_rows: dict[str, dict] = {}
        stable_rounds = 0
        idle_rounds = 0
        previous_scroll = None
        previous_height = None
        reported_count = -1
        if self.platform == "Threads":
            max_rounds = self.THREADS_MAX_SCROLL_ROUNDS
        elif self.platform == "Facebook":
            max_rounds = self.FACEBOOK_MAX_SCROLL_ROUNDS
        elif self.platform == "X":
            max_rounds = self.X_MAX_SCROLL_ROUNDS
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
                    added += self._merge_thread_rows(thread_rows, self._x_dom_rows())
                except WebDriverException:
                    pass
            if report_progress() >= max_comments:
                break
            try:
                state = driver.execute_script(
                    r"""
                    const platform = arguments[0];
                    const labels = [
                      'show replies', 'show more replies', 'view replies', 'view more replies',
                      'tampilkan balasan', 'lihat balasan', 'balasan lainnya',
                      'view previous comments', 'view more comments', 'see more comments', 'load more comments',
                      'lihat komentar sebelumnya', 'lihat komentar lainnya', 'muat komentar lainnya',
                      'tampilkan komentar lainnya'
                    ];
                    let clicked = 0;
                    for (const node of document.querySelectorAll('button, [role="button"]')) {
                      const text = (node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase();
                      const replyLoader =
                        /^(show|view|see|load|tampilkan|lihat|muat).*?(repl|balasan|comments?|komentar).*$/i.test(text) ||
                        /^\d[\d.,]*\s+(?:more\s+|lainnya\s+)?(?:replies|balasan|comments?|komentar)\b/i.test(text);
                      const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
                      if (visible && (labels.some(label => text.includes(label)) || replyLoader)) {
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
                      height
                    };
                    """,
                    self.platform,
                )
            except WebDriverException:
                break
            time.sleep(1.1 if isinstance(state, dict) and state.get("clicked") else 0.7)

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
                    added += self._merge_thread_rows(thread_rows, self._x_dom_rows())
                except WebDriverException:
                    pass

            if report_progress() >= max_comments:
                break

            state = state if isinstance(state, dict) else {"reachedEnd": bool(state)}
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
            if idle_rounds >= self.IDLE_STABLE_ROUNDS:
                break
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
                const controls = Array.from(document.querySelectorAll('button, [role="button"], a'));
                const commentButton = controls.find(node => {
                  const text = `${node.getAttribute('aria-label') || ''} ${node.innerText || ''}`
                    .replace(/\s+/g, ' ').trim();
                  const visible = Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
                  return visible && (
                    /\b\d[\d.,]*\s*(?:comments?|komentar)\b/i.test(text) ||
                    /^(?:comments?|komentar)$/i.test(text)
                  ) && !/(most relevant|paling relevan|top comments|komentar teratas)/i.test(text);
                });
                if (!commentButton) return false;
                commentButton.click();
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
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> CommentCollection:
        connector = get_platform_connector(url, self.platform)
        driver = self.start()
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
        if self.platform == "Facebook":
            self._prepare_facebook_comments()
        if self.platform == "Threads":
            target_match = re.search(r"/post/([^/?#]+)", current_url, re.I)
        elif self.platform == "X":
            target_match = re.search(r"/status/(\d+)", current_url, re.I)
        else:
            target_match = None
        target_code = target_match.group(1) if target_match else ""
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
                progress_callback=progress_callback,
            )
        )
        if not isinstance(thread_rows, list):
            thread_rows = []
        structured_comments = connector._platform_comments(driver.page_source, current_url)
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
        )
