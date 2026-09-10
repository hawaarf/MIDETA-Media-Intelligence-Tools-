"""Keyword-based Threads post discovery through a logged-in Chrome session."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from src.comment_browser import CommentBrowserCollector, CommentBrowserError
from src.config import DATA_DIR


THREADS_TRACKER_PROFILE_DIR = DATA_DIR / "browser_profiles" / "threads_tracker"


class ThreadsTrackerError(CommentBrowserError):
    pass


class ThreadsTrackerLoginRequired(ThreadsTrackerError):
    pass


class ThreadsTrackerCollector(CommentBrowserCollector):
    MAX_SCROLL_ROUNDS = 80
    STABLE_ROUNDS = 6

    def __init__(
        self,
        profile_dir: Path = THREADS_TRACKER_PROFILE_DIR,
        wait_seconds: int = 20,
        headless: bool = False,
    ):
        super().__init__(
            "Threads",
            profile_dir=profile_dir,
            wait_seconds=wait_seconds,
            headless=headless,
        )

    @staticmethod
    def search_url(keyword: str) -> str:
        query = urlencode({"q": keyword.strip(), "serp_type": "recent"})
        return f"https://www.threads.com/search?{query}"

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def normalize_row(cls, raw: dict) -> dict | None:
        url = str(raw.get("url") or "").strip()
        match = re.search(r"https?://(?:www\.)?threads\.(?:com|net)/@([^/]+)/post/([^/?#]+)", url, re.I)
        if not match:
            return None
        author, code = match.groups()
        canonical_url = f"https://www.threads.com/@{author}/post/{code}"
        likes = cls._count(raw.get("likes"))
        comments = cls._count(raw.get("comments"))
        reposts = cls._count(raw.get("reposts"))
        shares = cls._count(raw.get("shares"))
        posted_at = cls._parse_datetime(raw.get("posted_at"))
        caption = " ".join(str(raw.get("caption") or "").split())
        caption = re.sub(r"\s+\d+\s*/\s*\d+\s*$", "", caption)
        caption = re.sub(r"\s+(?:Translate|Terjemahkan)\s*$", "", caption, flags=re.I)
        return {
            "URL": canonical_url,
            "Tanggal posting": posted_at.isoformat() if posted_at else "Tidak tersedia",
            "Author": author,
            "Caption": caption or "Tidak tersedia",
            "Likes": likes,
            "Comments": comments,
            "Reposts": reposts,
            "Shares": shares,
            "Total engagement": likes + comments + reposts + shares,
        }

    @staticmethod
    def merge_rows(stored: dict[str, dict], rows: list[dict]) -> int:
        added = 0
        for raw in rows:
            row = ThreadsTrackerCollector.normalize_row(raw)
            if not row:
                continue
            url = row["URL"]
            if url not in stored:
                stored[url] = row
                added += 1
                continue
            previous = stored[url]
            for key, value in row.items():
                if value not in (None, "", "Tidak tersedia"):
                    previous[key] = value
        return added

    @classmethod
    def filter_and_sort(
        cls,
        rows: list[dict],
        period: str,
        order: str,
        *,
        now: datetime | None = None,
    ) -> list[dict]:
        if period not in {"recent", "7d", "all"}:
            raise ValueError("Rentang waktu Threads Tracker tidak dikenal.")
        if order not in {"highest", "lowest", "newest"}:
            raise ValueError("Urutan Threads Tracker tidak dikenal.")
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        cutoff = None
        if period == "recent":
            cutoff = reference.astimezone(timezone.utc) - timedelta(hours=24)
        elif period == "7d":
            cutoff = reference.astimezone(timezone.utc) - timedelta(days=7)

        filtered = []
        for row in rows:
            posted_at = cls._parse_datetime(row.get("Tanggal posting"))
            if cutoff is not None and (posted_at is None or posted_at < cutoff):
                continue
            filtered.append(row)

        def timestamp(row: dict) -> float:
            posted_at = cls._parse_datetime(row.get("Tanggal posting"))
            return posted_at.timestamp() if posted_at else float("-inf")

        if order == "highest":
            return sorted(
                filtered,
                key=lambda row: (int(row.get("Total engagement") or 0), timestamp(row)),
                reverse=True,
            )
        if order == "lowest":
            return sorted(
                filtered,
                key=lambda row: (int(row.get("Total engagement") or 0), -timestamp(row)),
            )
        return sorted(filtered, key=timestamp, reverse=True)

    def _dom_rows(self) -> list[dict]:
        return self.start().execute_script(
            r"""
            const anchors = Array.from(document.querySelectorAll('a[href*="/post/"]'));
            const rows = [];
            const seen = new Set();
            const uiText = /^(translate|terjemahkan|follow|ikuti|more|lainnya)$/i;

            const metric = (box, labels) => {
              const icon = Array.from(box.querySelectorAll('svg')).find(svg => {
                const label = (svg.getAttribute('aria-label') || '').trim().toLowerCase();
                return labels.some(candidate => label.includes(candidate));
              });
              if (!icon) return '';
              let holder = icon.closest('button, [role="button"]') || icon.parentElement;
              for (let level = 0; holder && level < 3; level++, holder = holder.parentElement) {
                const label = holder.getAttribute?.('aria-label') || '';
                const text = (holder.innerText || '').trim();
                if (/\d/.test(label) || /\d/.test(text)) return `${label} ${text}`.trim();
              }
              return '';
            };

            for (const anchor of anchors) {
              const href = anchor.href || '';
              const match = href.match(/\/(@[^/]+)\/post\/([^/?#]+)/);
              if (!match || seen.has(match[2]) || /\/media(?:[/?#]|$)/i.test(href)) continue;
              let box = anchor.closest('[data-pressable-container="true"]');
              if (!box) {
                box = anchor;
                for (let level = 0; level < 8 && box.parentElement; level++) {
                  box = box.parentElement;
                  const labels = Array.from(box.querySelectorAll('svg'))
                    .map(svg => (svg.getAttribute('aria-label') || '').toLowerCase());
                  if (labels.some(label => label.includes('like') || label.includes('suka'))) break;
                }
              }
              if (!box) continue;
              seen.add(match[2]);
              const author = match[1].slice(1);
              const time = box.querySelector('time');
              const candidates = Array.from(box.querySelectorAll('[dir="auto"]'))
                .map(node => (node.innerText || '').trim())
                .filter(text => text && text.toLowerCase() !== author.toLowerCase() && !uiText.test(text))
                .filter(text => !/^\d+[smhdw]$/i.test(text) && !/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(text));
              candidates.sort((a, b) => b.length - a.length);
              rows.push({
                url: href,
                author,
                posted_at: time?.getAttribute('datetime') || '',
                caption: candidates[0] || '',
                likes: metric(box, ['like', 'suka']),
                comments: metric(box, ['reply', 'comment', 'balas', 'komentar']),
                reposts: metric(box, ['repost', 'posting ulang']),
                shares: metric(box, ['share', 'bagikan'])
              });
            }
            return rows;
            """
        )

    def search(
        self,
        keyword: str,
        period: str = "recent",
        order: str = "highest",
        limit: int = 50,
    ) -> tuple[str, list[dict]]:
        keyword = " ".join(str(keyword or "").split())
        if not keyword:
            raise ThreadsTrackerError("Masukkan keyword yang ingin dicari.")
        limit = max(10, min(int(limit), 200))
        if not self.is_logged_in():
            raise ThreadsTrackerLoginRequired(
                "Threads Tracker memerlukan login. Buka sesi Threads Tracker, login, lalu periksa kembali."
            )

        driver = self.start()
        url = self.search_url(keyword)
        try:
            driver.get(url)
            self._wait_for_page()
            WebDriverWait(driver, self.wait_seconds).until(
                lambda active: active.find_elements(By.XPATH, "//a[contains(@href, '/post/')]")
                or "no results" in active.find_element(By.TAG_NAME, "body").text.casefold()
            )
        except WebDriverException:
            pass
        if "/login" in str(driver.current_url or "").casefold():
            raise ThreadsTrackerLoginRequired(
                "Sesi Threads Tracker sudah berakhir. Login kembali, lalu ulangi pencarian."
            )

        stored: dict[str, dict] = {}
        stable_rounds = 0
        previous_height = -1
        for _ in range(self.MAX_SCROLL_ROUNDS):
            try:
                added = self.merge_rows(stored, self._dom_rows())
                height = int(driver.execute_script("return document.documentElement.scrollHeight") or 0)
            except WebDriverException as exc:
                raise ThreadsTrackerError("Halaman pencarian Threads berhenti merespons.") from exc
            stable_rounds = stable_rounds + 1 if added == 0 and height == previous_height else 0
            matching_rows = self.filter_and_sort(list(stored.values()), period, order)
            if len(matching_rows) >= limit or stable_rounds >= self.STABLE_ROUNDS:
                break
            previous_height = height
            driver.execute_script("window.scrollBy(0, Math.max(window.innerHeight * 0.85, 700))")
            time.sleep(0.7)

        return url, self.filter_and_sort(list(stored.values()), period, order)[:limit]
