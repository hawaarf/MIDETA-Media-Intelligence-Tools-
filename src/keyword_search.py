# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Best-effort public keyword discovery for TikTok and Threads.

The collector intentionally uses the platforms' own public search pages.  It
does not import browser cookies, bypass login, or claim full social-listening
coverage.  A small Boolean parser is applied locally so the exported rows obey
the user's query even when a platform only accepts one search phrase at a time.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import html as html_module
import re
import time
from typing import Any, Callable, Iterable
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from src.config import (
    MAX_KEYWORD_RESULTS,
    MAX_KEYWORD_TERMS,
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT_SECONDS,
)
from src.connectors.base import BaseConnector
from src.comment_browser import (
    CommentBrowserCollector,
    CommentBrowserError,
    CommentBrowserLoginRequired,
)
from src.dates import parse_social_datetime
from src.tiktok_browser import (
    TikTokAccessDenied,
    TikTokBrowserCollector,
    TikTokBrowserError,
    TikTokLoginRequired,
)


JAKARTA_TZ = ZoneInfo("Asia/Jakarta")
SUPPORTED_PLATFORMS = ("TikTok", "Threads")
THREADS_MODES = {
    "Top + Recent": ("Top", "Recent"),
    "Teratas": ("Top",),
    "Terbaru": ("Recent",),
}


class KeywordSearchError(RuntimeError):
    """Raised for invalid queries or a search that cannot start safely."""


@dataclass(frozen=True, slots=True)
class QueryToken:
    kind: str
    value: str = ""


@dataclass(slots=True)
class BooleanQuery:
    """Parsed Boolean query with local matching and positive seed terms."""

    source: str
    tree: tuple

    def matches(self, text: str) -> bool:
        searchable = re.sub(r"\s+", " ", str(text or "")).casefold()

        def evaluate(node: tuple) -> bool:
            operator = node[0]
            if operator == "TERM":
                return node[1].casefold() in searchable
            if operator == "NOT":
                return not evaluate(node[1])
            if operator == "AND":
                return evaluate(node[1]) and evaluate(node[2])
            if operator == "OR":
                return evaluate(node[1]) or evaluate(node[2])
            return False

        return evaluate(self.tree)

    def positive_terms(self) -> list[str]:
        terms: list[str] = []

        def visit(node: tuple, negated: bool = False) -> None:
            operator = node[0]
            if operator == "TERM":
                if not negated and node[1].casefold() not in {term.casefold() for term in terms}:
                    terms.append(node[1])
                return
            if operator == "NOT":
                visit(node[1], not negated)
                return
            visit(node[1], negated)
            visit(node[2], negated)

        visit(self.tree)
        return terms


def _lex_query(source: str) -> list[QueryToken]:
    tokens: list[QueryToken] = []
    position = 0
    while position < len(source):
        character = source[position]
        if character.isspace():
            position += 1
            continue
        if character in "()":
            tokens.append(QueryToken(character))
            position += 1
            continue
        if character in {'"', "'"}:
            quote = character
            position += 1
            value: list[str] = []
            while position < len(source) and source[position] != quote:
                if source[position] == "\\" and position + 1 < len(source):
                    position += 1
                value.append(source[position])
                position += 1
            if position >= len(source):
                raise KeywordSearchError("Tanda kutip pada keyword belum ditutup.")
            position += 1
            cleaned = re.sub(r"\s+", " ", "".join(value)).strip()
            if cleaned:
                tokens.append(QueryToken("TERM", cleaned))
            continue

        end = position
        while end < len(source) and not source[end].isspace() and source[end] not in "()":
            end += 1
        value = source[position:end].strip()
        upper = value.upper()
        tokens.append(QueryToken(upper if upper in {"AND", "OR", "NOT"} else "TERM", value))
        position = end
    return tokens


def _with_implicit_and(tokens: list[QueryToken]) -> list[QueryToken]:
    expanded: list[QueryToken] = []
    previous: QueryToken | None = None
    for token in tokens:
        previous_can_end = previous is not None and previous.kind in {"TERM", ")"}
        current_can_start = token.kind in {"TERM", "(", "NOT"}
        if previous_can_end and current_can_start:
            expanded.append(QueryToken("AND"))
        expanded.append(token)
        previous = token
    return expanded


class _QueryParser:
    def __init__(self, tokens: list[QueryToken]):
        self.tokens = tokens
        self.position = 0

    def current(self) -> QueryToken | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def accept(self, kind: str) -> QueryToken | None:
        token = self.current()
        if token and token.kind == kind:
            self.position += 1
            return token
        return None

    def parse(self) -> tuple:
        tree = self.parse_or()
        if self.current() is not None:
            raise KeywordSearchError("Susunan operator Boolean belum valid.")
        return tree

    def parse_or(self) -> tuple:
        left = self.parse_and()
        while self.accept("OR"):
            left = ("OR", left, self.parse_and())
        return left

    def parse_and(self) -> tuple:
        left = self.parse_not()
        while self.accept("AND"):
            left = ("AND", left, self.parse_not())
        return left

    def parse_not(self) -> tuple:
        if self.accept("NOT"):
            return ("NOT", self.parse_not())
        return self.parse_primary()

    def parse_primary(self) -> tuple:
        if term := self.accept("TERM"):
            return ("TERM", term.value)
        if self.accept("("):
            value = self.parse_or()
            if not self.accept(")"):
                raise KeywordSearchError("Kurung pada keyword belum lengkap.")
            return value
        raise KeywordSearchError("Keyword atau frasa diperlukan setelah operator Boolean.")


def parse_boolean_query(value: str) -> BooleanQuery:
    """Parse phrases and AND/OR/NOT operators using familiar precedence."""
    source = re.sub(r"\s+", " ", str(value or "")).strip()
    if not source:
        raise KeywordSearchError("Masukkan minimal satu keyword.")

    # Plain text is treated as one phrase. Boolean syntax or explicit quotes
    # switches to the parser and supports implicit AND between adjacent terms.
    has_syntax = bool(re.search(r"[()\"']|\b(?:AND|OR|NOT)\b", source, re.I))
    tokens = _lex_query(source) if has_syntax else [QueryToken("TERM", source)]
    if not tokens:
        raise KeywordSearchError("Masukkan minimal satu keyword.")
    tree = _QueryParser(_with_implicit_and(tokens)).parse()
    query = BooleanQuery(source=source, tree=tree)
    terms = query.positive_terms()
    if not terms:
        raise KeywordSearchError("Query harus memiliki minimal satu keyword yang dicari, bukan hanya NOT.")
    if len(terms) > MAX_KEYWORD_TERMS:
        raise KeywordSearchError(
            f"Maksimal {MAX_KEYWORD_TERMS} keyword/frasa positif dalam satu pencarian."
        )
    return query


def _clean_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("text") or value.get("content") or value.get("description")
    if isinstance(value, list):
        parts = [_clean_text(item) for item in value]
        value = " ".join(part for part in parts if part)
    if value in (None, ""):
        return ""
    return re.sub(r"\s+", " ", html_module.unescape(str(value))).strip()


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _nested_mappings(mapping: dict[str, Any], *keys: str) -> Iterable[dict[str, Any]]:
    yield mapping
    for key in keys:
        child = mapping.get(key)
        if isinstance(child, dict):
            yield child


def _metric(mapping: dict[str, Any], *keys: str) -> int | None:
    for candidate in _nested_mappings(mapping, "stats", "statsV2", "statistics", "text_post_app_info"):
        for key in keys:
            if key not in candidate:
                continue
            value = candidate[key]
            if isinstance(value, dict):
                value = _first(value, "count", "total_count", "value")
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                return int(value)
            parsed = BaseConnector._human_count(str(value))
            if parsed is not None:
                return parsed
    return None


def _author(mapping: dict[str, Any]) -> str:
    for key in ("author", "user", "owner"):
        user = mapping.get(key)
        if isinstance(user, dict):
            value = _first(user, "uniqueId", "unique_id", "username", "handle", "name", "full_name")
            if value:
                return _clean_text(value).lstrip("@")
    value = _first(mapping, "author_name", "authorName", "username", "uniqueId")
    return _clean_text(value).lstrip("@")


def _posted_datetime(mapping: dict[str, Any]) -> datetime | None:
    for candidate in _nested_mappings(mapping, "video", "post", "item"):
        value = _first(
            candidate,
            "taken_at",
            "created_at",
            "createTime",
            "create_time",
            "timestamp",
            "publish_time",
            "datePublished",
        )
        parsed = parse_social_datetime(value)
        if parsed:
            return parsed.astimezone(JAKARTA_TZ)
    return None


def _threads_caption(post: dict[str, Any]) -> str:
    value = _first(post, "caption", "text", "description")
    caption = _clean_text(value)
    app_info = post.get("text_post_app_info")
    if not caption and isinstance(app_info, dict):
        caption = _clean_text(
            _first(app_info, "text", "caption", "text_fragments", "fragments")
        )
    return caption


def _threads_rows(source: str, search_type: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    soup = BeautifulSoup(source, "lxml")
    for payload in BaseConnector._embedded_json(soup):
        for node in BaseConnector._walk(payload):
            post = node.get("post") if isinstance(node.get("post"), dict) else node
            if not isinstance(post, dict):
                continue
            code = _clean_text(_first(post, "code", "shortcode", "media_code"))
            if not re.fullmatch(r"[A-Za-z0-9_-]{5,40}", code):
                continue
            author = _author(post)
            caption = _threads_caption(post)
            if not author or not caption:
                continue
            url = f"https://www.threads.com/@{author}/post/{code}"
            row = {
                "Platform": "Threads",
                "Date Publish": _posted_datetime(post),
                "Author": author,
                "Content": caption,
                "URL": url,
                "Views": _metric(post, "view_count", "view_counts", "views_count", "play_count"),
                "Likes": _metric(post, "like_count", "likeCount", "likes_count"),
                "Comments": _metric(
                    post,
                    "direct_reply_count",
                    "reply_count",
                    "replies_count",
                    "comment_count",
                ),
                "Shares": _metric(post, "reshare_count", "share_count", "shares_count"),
                "Reposts": _metric(post, "repost_count", "reposts_count"),
                "Search Type": search_type,
            }
            current = rows.get(url)
            if current is None or _row_richness(row) > _row_richness(current):
                rows[url] = row
    return list(rows.values())


def _tiktok_caption(item: dict[str, Any]) -> str:
    for key in ("desc", "description", "caption", "text", "title"):
        value = _clean_text(item.get(key))
        if value:
            return value
    return ""


def _tiktok_rows(source: str) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    soup = BeautifulSoup(source, "lxml")
    identifier_keys = ("id", "aweme_id", "awemeId", "item_id", "itemId", "video_id", "videoId")
    for payload in BaseConnector._embedded_json(soup):
        for node in BaseConnector._walk(payload):
            if not isinstance(node, dict):
                continue
            post_id = _clean_text(_first(node, *identifier_keys))
            if not re.fullmatch(r"\d{10,30}", post_id):
                continue
            author = _author(node)
            caption = _tiktok_caption(node)
            if not author or not caption:
                continue
            is_photo = bool(
                node.get("imagePost")
                or node.get("image_post_info")
                or node.get("photoMode")
                or node.get("isPhoto")
            )
            post_type = "photo" if is_photo else "video"
            url = f"https://www.tiktok.com/@{author}/{post_type}/{post_id}"
            row = {
                "Platform": "TikTok",
                "Date Publish": _posted_datetime(node),
                "Author": author,
                "Content": caption,
                "URL": url,
                "Views": _metric(node, "playCount", "play_count", "viewCount", "view_count"),
                "Likes": _metric(node, "diggCount", "digg_count", "likeCount", "like_count"),
                "Comments": _metric(node, "commentCount", "comment_count"),
                "Shares": _metric(node, "shareCount", "share_count"),
                "Reposts": _metric(node, "repostCount", "repost_count"),
                "Search Type": "Video",
            }
            current = rows.get(url)
            if current is None or _row_richness(row) > _row_richness(current):
                rows[url] = row
    return list(rows.values())


def _tiktok_date_from_post_id(post_id: str) -> datetime | None:
    """Read the creation timestamp encoded in a modern TikTok snowflake ID."""
    try:
        parsed = datetime.fromtimestamp(int(post_id) >> 32, tz=timezone.utc).astimezone(JAKARTA_TZ)
    except (OSError, OverflowError, TypeError, ValueError):
        return None
    current_year = datetime.now(JAKARTA_TZ).year
    return parsed if 2016 <= parsed.year <= current_year + 1 else None


class TikTokKeywordBrowserCollector(TikTokBrowserCollector):
    """Read visible TikTok search cards through the saved local session."""

    def search(self, term: str, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = min(max(1, int(limit)), MAX_KEYWORD_RESULTS)
        if not self.is_logged_in():
            raise KeywordSearchError(
                "TikTok menahan hasil publik. Login di Sesi TikTok Keyword Search, lalu jalankan lagi."
            )
        session = self.start()
        session.navigate(_search_url("TikTok", term, "Video"))
        self._wait_for_page()
        try:
            self._raise_if_access_denied()
        except TikTokAccessDenied as exc:
            raise KeywordSearchError(str(exc)) from exc

        cards: dict[str, dict[str, Any]] = {}
        unchanged_rounds = 0
        previous_count = -1
        max_scrolls = min(80, max(12, (safe_limit // 8) + 8))
        card_script = """
        (() => {
          const results = [];
          const links = [...document.querySelectorAll('a[href*="/video/"], a[href*="/photo/"]')];
          for (const link of links) {
            let card = link;
            let best = link;
            for (let depth = 0; depth < 7 && card; depth += 1, card = card.parentElement) {
              const text = (card.innerText || card.textContent || '').trim();
              if (text.length >= 8 && text.length <= 2400) best = card;
              if (card.matches && card.matches('[data-e2e*="search"], [data-e2e="user-post-item"]')) {
                best = card;
                break;
              }
            }
            const description = best.querySelector && best.querySelector(
              '[data-e2e="search-card-desc"], [data-e2e="video-desc"], [data-e2e*="desc"]'
            );
            const text = ((description && (description.innerText || description.textContent)) ||
              best.innerText || best.textContent || '').trim();
            const authorLink = best.querySelector && best.querySelector('a[href^="/@"]');
            results.push({
              url: link.href || link.getAttribute('href') || '',
              text,
              author_url: authorLink ? (authorLink.href || authorLink.getAttribute('href') || '') : ''
            });
          }
          return results;
        })()
        """

        for _ in range(max_scrolls):
            try:
                visible = session.evaluate(card_script)
            except TikTokBrowserError as exc:
                raise KeywordSearchError(f"Sesi TikTok Keyword Search terputus: {exc}") from exc
            if isinstance(visible, list):
                for item in visible:
                    if not isinstance(item, dict):
                        continue
                    parsed = urlparse(str(item.get("url") or ""))
                    parts = [part for part in parsed.path.split("/") if part]
                    if len(parts) < 3 or not parts[0].startswith("@"):
                        continue
                    if parts[1] not in {"video", "photo"} or not parts[2].isdigit():
                        continue
                    author = parts[0].lstrip("@")
                    post_id = parts[2]
                    url = f"https://www.tiktok.com/@{author}/{parts[1]}/{post_id}"
                    content = _clean_text(item.get("text"))
                    if not content:
                        continue
                    cards[url] = {
                        "Platform": "TikTok",
                        "Date Publish": _tiktok_date_from_post_id(post_id),
                        "Author": author,
                        "Content": content,
                        "URL": url,
                        "Views": None,
                        "Likes": None,
                        "Comments": None,
                        "Shares": None,
                        "Reposts": None,
                        "Search Type": "Video · sesi TikTok",
                    }
            if len(cards) >= safe_limit:
                break
            if len(cards) == previous_count:
                unchanged_rounds += 1
            else:
                unchanged_rounds = 0
                previous_count = len(cards)
            if unchanged_rounds >= 5:
                break
            session.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.0)
        return list(cards.values())[:safe_limit]


class ThreadsKeywordBrowserCollector(CommentBrowserCollector):
    """Read visible Threads search cards through the saved local session."""

    def __init__(self, *args, **kwargs):
        super().__init__("Threads", *args, **kwargs)

    def search(
        self,
        term: str,
        limit: int = 200,
        search_type: str = "Recent",
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(1, int(limit)), MAX_KEYWORD_RESULTS)
        if not self.is_logged_in():
            raise KeywordSearchError(
                "Threads tidak mengirim hasil keyword publik. Login di Sesi Threads Keyword Search, "
                "lalu jalankan lagi."
            )
        driver = self.start()
        try:
            driver.get(_search_url("Threads", term, search_type))
            self._wait_for_page()
        except CommentBrowserError as exc:
            raise KeywordSearchError(f"Sesi Threads Keyword Search terputus: {exc}") from exc
        except Exception as exc:
            raise KeywordSearchError("Halaman pencarian Threads tidak dapat dibuka.") from exc

        cards: dict[str, dict[str, Any]] = {}
        unchanged_rounds = 0
        previous_count = -1
        max_scrolls = min(80, max(12, (safe_limit // 8) + 8))
        card_script = r"""
        (() => {
          const output = [];
          const links = [...document.querySelectorAll('a[href*="/post/"]')];
          for (const link of links) {
            const rawHref = link.href || link.getAttribute('href') || '';
            if (!/\/\@[^/]+\/post\/[A-Za-z0-9_-]+/.test(rawHref)) continue;
            let card = link;
            let best = link;
            for (let depth = 0; depth < 12 && card; depth += 1, card = card.parentElement) {
              const text = (card.innerText || card.textContent || '').trim();
              const postLinks = card.querySelectorAll ? card.querySelectorAll('a[href*="/post/"]').length : 0;
              if (text.length >= 8 && text.length <= 4000 && postLinks <= 2) best = card;
              if (card.tagName === 'ARTICLE') {
                best = card;
                break;
              }
            }
            const text = (best.innerText || best.textContent || '').trim();
            const time = best.querySelector && best.querySelector('time');
            const controls = best.querySelectorAll ? [...best.querySelectorAll('[aria-label]')] : [];
            const labels = controls.map(node => node.getAttribute('aria-label') || '').filter(Boolean);
            output.push({
              url: rawHref,
              text,
              datetime: time ? (time.dateTime || time.getAttribute('datetime') || '') : '',
              labels
            });
          }
          return output;
        })()
        """

        for _ in range(max_scrolls):
            try:
                visible = driver.execute_script(card_script)
            except Exception as exc:
                raise KeywordSearchError(f"Sesi Threads Keyword Search terputus: {exc}") from exc
            if isinstance(visible, list):
                for item in visible:
                    if not isinstance(item, dict):
                        continue
                    match = re.search(
                        r"/(?:@)([^/?#]+)/post/([A-Za-z0-9_-]+)",
                        str(item.get("url") or ""),
                        re.I,
                    )
                    if not match:
                        continue
                    author, code = match.groups()
                    url = f"https://www.threads.com/@{author}/post/{code}"
                    content = _clean_threads_browser_text(item.get("text"), author)
                    if not content:
                        continue
                    labels = item.get("labels") if isinstance(item.get("labels"), list) else []
                    cards[url] = {
                        "Platform": "Threads",
                        "Date Publish": parse_social_datetime(item.get("datetime")),
                        "Author": author,
                        "Content": content,
                        "URL": url,
                        "Views": _metric_from_labels(labels, "view", "tayangan"),
                        "Likes": _metric_from_labels(labels, "like", "suka"),
                        "Comments": _metric_from_labels(labels, "repl", "balas", "komentar"),
                        "Shares": _metric_from_labels(labels, "share", "bagikan"),
                        "Reposts": _metric_from_labels(labels, "repost", "posting ulang"),
                        "Search Type": f"{search_type} · sesi Threads",
                    }
            if len(cards) >= safe_limit:
                break
            if len(cards) == previous_count:
                unchanged_rounds += 1
            else:
                unchanged_rounds = 0
                previous_count = len(cards)
            if unchanged_rounds >= 5:
                break
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            except Exception as exc:
                raise KeywordSearchError(f"Sesi Threads Keyword Search terputus: {exc}") from exc
            time.sleep(1.0)
        return list(cards.values())[:safe_limit]


def _metric_from_labels(labels: Iterable[Any], *needles: str) -> int | None:
    for raw_label in labels:
        label = _clean_text(raw_label)
        if not any(needle.casefold() in label.casefold() for needle in needles):
            continue
        match = re.search(r"\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?", label, re.I)
        if match:
            return BaseConnector._human_count(match.group(0))
    return None


def _clean_threads_browser_text(value: Any, author: str) -> str:
    """Remove common Threads card chrome while retaining the post body."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(value or "").splitlines()]
    ignored = {
        author.casefold(),
        f"@{author}".casefold(),
        "follow",
        "following",
        "ikuti",
        "mengikuti",
        "translate",
        "terjemahkan",
    }
    kept: list[str] = []
    for line in lines:
        folded = line.casefold()
        if not line or folded in ignored:
            continue
        if re.fullmatch(r"(?:\d+[.,]?\d*\s*){1,5}", line):
            continue
        kept.append(line)
    return " ".join(kept).strip()


def parse_search_page(platform: str, source: str, search_type: str = "Top") -> list[dict[str, Any]]:
    """Parse public search hydration without executing page JavaScript."""
    if platform == "TikTok":
        return _tiktok_rows(source)
    if platform == "Threads":
        return _threads_rows(source, search_type)
    raise KeywordSearchError(f"Platform {platform} belum didukung Keyword Search.")


def _row_richness(row: dict[str, Any]) -> int:
    metrics = sum(row.get(key) is not None for key in ("Views", "Likes", "Comments", "Shares", "Reposts"))
    return metrics * 20 + len(str(row.get("Content") or "")) + (30 if row.get("Date Publish") else 0)


def _safe_public_search_html(url: str, platform: str) -> str:
    """Load a fixed platform search endpoint without credentials or cookies."""
    allowed_host = "tiktok.com" if platform == "TikTok" else "threads.com"
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    if hostname != allowed_host and not hostname.endswith(f".{allowed_host}"):
        raise KeywordSearchError("Tujuan pencarian publik tidak valid.")

    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    }
    try:
        from curl_cffi import requests as curl_requests

        response = curl_requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            impersonate="chrome",
            allow_redirects=True,
        )
        status_code = response.status_code
        content = response.content
        final_url = response.url
    except Exception:
        import requests

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
            status_code = response.status_code
            content = response.content
            final_url = response.url
        except requests.RequestException as exc:
            raise KeywordSearchError(f"{platform} tidak dapat dihubungi: {exc}") from exc

    final_host = (urlparse(str(final_url)).hostname or "").casefold()
    if final_host != allowed_host and not final_host.endswith(f".{allowed_host}"):
        raise KeywordSearchError(f"{platform} mengarahkan pencarian ke tujuan yang tidak dikenali.")
    if status_code in {401, 403, 429}:
        raise KeywordSearchError(
            f"{platform} membatasi pencarian publik (HTTP {status_code}). Coba lagi nanti."
        )
    if status_code >= 400:
        raise KeywordSearchError(f"{platform} mengembalikan HTTP {status_code}.")
    if len(content) > MAX_RESPONSE_BYTES:
        raise KeywordSearchError(f"Halaman hasil {platform} melebihi batas ukuran aman.")
    return content.decode("utf-8", errors="replace")


def _search_url(platform: str, term: str, search_type: str) -> str:
    encoded = quote_plus(term)
    if platform == "TikTok":
        return f"https://www.tiktok.com/search/video?q={encoded}"
    serp_type = "recent" if search_type == "Recent" else "default"
    return f"https://www.threads.com/search?q={encoded}&serp_type={serp_type}"


@dataclass(slots=True)
class KeywordSearchResult:
    query: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    requests_made: int = 0
    request_failures: int = 0
    warning: str = ""


class KeywordSearchCollector:
    """Collect and normalize bounded public search results in parallel."""

    def __init__(
        self,
        *,
        fetcher: Callable[[str, str], str] | None = None,
        tiktok_browser_searcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
        threads_browser_searcher: Callable[
            [str, int, str], list[dict[str, Any]]
        ]
        | None = None,
        max_workers: int = 4,
    ):
        self.fetcher = fetcher or _safe_public_search_html
        self.tiktok_browser_searcher = tiktok_browser_searcher
        self.threads_browser_searcher = threads_browser_searcher
        self.max_workers = min(max(1, int(max_workers)), 6)

    def collect(
        self,
        query_value: str,
        platforms: list[str],
        start_date: date,
        end_date: date,
        *,
        search_mode: str = "Top + Recent",
        max_results: int = 200,
        progress_callback: Callable[[dict[str, int]], None] | None = None,
    ) -> KeywordSearchResult:
        if start_date > end_date:
            raise KeywordSearchError("Tanggal awal tidak boleh melewati tanggal akhir.")
        if not platforms:
            raise KeywordSearchError("Pilih minimal satu platform.")
        unsupported = [platform for platform in platforms if platform not in SUPPORTED_PLATFORMS]
        if unsupported:
            raise KeywordSearchError(f"Platform belum didukung: {', '.join(unsupported)}.")
        if search_mode not in THREADS_MODES:
            raise KeywordSearchError("Mode hasil Threads tidak dikenali.")

        boolean_query = parse_boolean_query(query_value)
        terms = boolean_query.positive_terms()
        safe_limit = min(max(1, int(max_results)), MAX_KEYWORD_RESULTS)
        tasks: list[tuple[str, str, str, str]] = []
        for platform in platforms:
            if platform == "TikTok" and self.tiktok_browser_searcher is not None:
                continue
            if platform == "Threads" and self.threads_browser_searcher is not None:
                continue
            modes = THREADS_MODES[search_mode] if platform == "Threads" else ("Video",)
            for term in terms:
                for result_type in modes:
                    tasks.append((platform, term, result_type, _search_url(platform, term, result_type)))

        result = KeywordSearchResult(query=boolean_query.source)
        discovered: dict[str, dict[str, Any]] = {}
        warnings: set[str] = set()
        completed = 0
        browser_terms = terms if "TikTok" in platforms and self.tiktok_browser_searcher else []
        thread_browser_tasks = (
            [(term, result_type) for term in terms for result_type in THREADS_MODES[search_mode]]
            if "Threads" in platforms and self.threads_browser_searcher
            else []
        )
        total_operations = len(tasks) + len(browser_terms) + len(thread_browser_tasks)

        def accept_rows(rows: list[dict[str, Any]], term: str) -> None:
            for row in rows:
                searchable = f"{row.get('Author', '')} {row.get('Content', '')}"
                if not boolean_query.matches(searchable):
                    continue
                published = row.get("Date Publish")
                if isinstance(published, datetime):
                    published_date = published.date()
                    if not start_date <= published_date <= end_date:
                        continue
                matched = [seed for seed in terms if seed.casefold() in searchable.casefold()]
                row["Matched Keyword"] = ", ".join(matched) or term
                existing = discovered.get(row["URL"])
                if existing is None:
                    discovered[row["URL"]] = row
                    continue
                combined = {
                    item.strip()
                    for item in f"{existing.get('Matched Keyword', '')},{row['Matched Keyword']}".split(",")
                    if item.strip()
                }
                if _row_richness(row) > _row_richness(existing):
                    discovered[row["URL"]] = row
                    existing = row
                existing["Matched Keyword"] = ", ".join(
                    item for item in terms if item in combined
                )
                types = {
                    item.strip()
                    for item in f"{existing.get('Search Type', '')},{row.get('Search Type', '')}".split(",")
                    if item.strip()
                }
                existing["Search Type"] = " + ".join(sorted(types))

        def report_progress() -> None:
            if progress_callback:
                progress_callback(
                    {
                        "completed": completed,
                        "total": total_operations,
                        "discovered": len(discovered),
                    }
                )

        if tasks:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
                future_map = {
                    executor.submit(self.fetcher, url, platform): (platform, term, result_type)
                    for platform, term, result_type, url in tasks
                }
                result.requests_made = len(future_map)
                for future in as_completed(future_map):
                    platform, term, result_type = future_map[future]
                    completed += 1
                    try:
                        source = future.result()
                        rows = parse_search_page(platform, source, result_type)
                    except Exception as exc:
                        result.request_failures += 1
                        warnings.add(str(exc))
                        rows = []
                    accept_rows(rows, term)
                    report_progress()

        for term in browser_terms:
            completed += 1
            result.requests_made += 1
            try:
                browser_rows = self.tiktok_browser_searcher(term, safe_limit)
            except (KeywordSearchError, TikTokBrowserError, TikTokLoginRequired) as exc:
                result.request_failures += 1
                warnings.add(str(exc))
                browser_rows = []
            accept_rows(browser_rows, term)
            report_progress()

        for term, result_type in thread_browser_tasks:
            completed += 1
            result.requests_made += 1
            try:
                browser_rows = self.threads_browser_searcher(term, safe_limit, result_type)
            except (KeywordSearchError, CommentBrowserError, CommentBrowserLoginRequired) as exc:
                result.request_failures += 1
                warnings.add(str(exc))
                browser_rows = []
            accept_rows(browser_rows, term)
            report_progress()

        ordered = sorted(
            discovered.values(),
            key=lambda row: (
                row.get("Date Publish") is not None,
                row.get("Date Publish") or datetime.min.replace(tzinfo=JAKARTA_TZ),
                sum(
                    value if isinstance(value, int) else 0
                    for value in (
                        row.get("Likes"),
                        row.get("Comments"),
                        row.get("Shares"),
                        row.get("Reposts"),
                    )
                ),
            ),
            reverse=True,
        )[:safe_limit]

        collected_at = datetime.now(JAKARTA_TZ).isoformat(timespec="seconds")
        result.rows = []
        for index, row in enumerate(ordered, 1):
            published = row.get("Date Publish")
            row["Date Publish"] = published.date().isoformat() if isinstance(published, datetime) else "Cek"
            for key in ("Views", "Likes", "Comments", "Shares", "Reposts"):
                if row.get(key) is None:
                    row[key] = "Cek"
            row["Status"] = (
                "Ditemukan dari hasil publik"
                if published is not None
                else "Ditemukan; tanggal tidak dapat dibaca"
            )
            row["Waktu Pengambilan"] = collected_at
            row["No"] = index
            result.rows.append(row)

        general_warning = (
            "Keyword Search memakai halaman hasil publik TikTok/Threads yang jumlahnya dibatasi dan dapat berubah. "
            "Hasil adalah discovery/sampel, bukan seluruh mention seperti layanan social-listening berlisensi."
        )
        if warnings:
            limited = " | ".join(sorted(warnings)[:3])
            result.warning = f"{general_warning} Catatan sumber: {limited}"
        else:
            result.warning = general_warning
        return result
