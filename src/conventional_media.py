# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Conventional news article enrichment for MIDETA."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.support.ui import WebDriverWait

from src.config import DATA_DIR
from src.http_client import CollectionError, fetch_public_html
from src.validators import URLValidationError, validate_public_url


ARTICLE_COLUMNS = (
    "date_publish",
    "month",
    "media_name",
    "media_scope",
    "media_tier",
    "page_link",
    "title",
    "content",
    "journalist_name",
    "tone_article",
    "quote_mention",
)
CHECK_ARTICLE_NOT_AVAILABLE = "[CHECK] article not available"
CHECK_FAILED_TO_PROCESS = "[CHECK] failed to process"
CONVENTIONAL_PROFILE_DIR = DATA_DIR / "browser_profiles" / "conventional_media"
ARTICLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


class ConventionalMediaError(RuntimeError):
    """Raised when an article cannot be collected safely."""


@dataclass
class ArticleResult:
    source_url: str
    date_publish: str = ""
    month: str = ""
    media_name: str = ""
    media_scope: str = ""
    media_tier: str = ""
    title: str = ""
    content: str = ""
    journalist: str = ""
    tone: str = ""
    quote_mention: str = ""
    status: str = "completed"
    reason: str = ""

    def to_row(self) -> dict[str, str]:
        """Return the exact column order requested for CSV/XLSX."""
        values = {
            "date_publish": self.date_publish,
            "month": self.month,
            "media_name": self.media_name,
            "media_scope": self.media_scope,
            "media_tier": self.media_tier,
            "page_link": self.source_url,
            "title": self.title,
            "content": self.content,
            "journalist_name": self.journalist,
            "tone_article": self.tone,
            "quote_mention": self.quote_mention,
        }
        return {column: values[column] for column in ARTICLE_COLUMNS}


GENERIC_MEDIA_SUBDOMAINS = {
    "amp", "artikel", "article", "bisnis", "business", "ekonomi", "finance",
    "health", "internasional", "investasi", "lifestyle", "m", "money", "nasional",
    "news", "otomotif", "regional", "sport", "sports", "tekno", "travel", "www",
}
INDONESIAN_MEDIA_DOMAINS = {
    "antaranews.com", "bisnis.com", "cnbcindonesia.com", "cnnindonesia.com",
    "cyrustimes.com", "detik.com", "gebrak.id", "idntimes.com", "infotren.id",
    "investor.id", "jawapos.com", "kabarnusantara.id", "kompas.com",
    "kontan.co.id", "kumparan.com", "liputan6.com", "mediaindonesia.com",
    "mediakompeten.co.id", "merdeka.com", "metrotvnews.com", "nusantaranews.co",
    "okezone.com", "panrita.news", "papiperjuanganbali.id", "pojokpapua.id",
    "qoo10.co.id", "readers.id", "republika.co.id", "sindonews.com", "stockwatch.id",
    "suara.com", "tempo.co", "thejakartapost.com", "tribunnews.com", "tvonenews.com",
    "viv.co.id", "viva.co.id",
}
REGIONAL_MARKERS = {
    "aceh", "ambon", "bandung", "banjarmasin", "bekasi", "bengkulu", "bogor",
    "depok", "jabar", "jateng", "jatim", "jogja", "kalbar", "kalsel", "kaltim",
    "lampung", "makassar", "malang", "manado", "medan", "muria",
    "papua", "pekanbaru", "pontianak", "purwakarta", "semarang", "solo", "surabaya",
    "sulsel", "sumbar", "sumsel", "tangerang",
}
TIER_ONE_DOMAINS = {
    "antaranews.com", "bisnis.com", "bloomberg.com", "cnbcindonesia.com",
    "cnnindonesia.com", "detik.com", "jawapos.com", "kompas.com", "kontan.co.id",
    "kumparan.com", "liputan6.com",
    "reuters.com", "tempo.co", "thejakartapost.com", "tribunnews.com",
}
TIER_TWO_DOMAINS = {
    "idntimes.com", "investor.id", "mediaindonesia.com", "merdeka.com", "metrotvnews.com",
    "okezone.com", "republika.co.id", "sindonews.com", "suara.com", "tvonenews.com",
}


def _base_domain(hostname: str) -> str:
    labels = hostname.casefold().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    if labels[-2:] in [
        ["co", "id"], ["or", "id"], ["ac", "id"], ["go", "id"],
        ["co", "uk"], ["com", "au"], ["co", "jp"], ["co", "sg"], ["com", "my"],
    ]:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def media_identity(url: str) -> tuple[str, str, str]:
    """Return normalized uppercase name, scope, and editorial tier."""
    host = (urlparse(url).hostname or "").casefold().strip(".")
    if host.startswith("www."):
        host = host[4:]
    base = _base_domain(host)
    labels = host.split(".")
    prefix = labels[: max(0, len(labels) - len(base.split(".")))]
    meaningful_prefix = [part for part in prefix if part not in GENERIC_MEDIA_SUBDOMAINS]
    name = (".".join([*meaningful_prefix, base.split(".")[0], *base.split(".")[1:]]) if meaningful_prefix else base).upper()

    regional = any(marker in host.split(".") or marker in host for marker in REGIONAL_MARKERS)
    if regional:
        scope = "Regional"
    elif base.endswith(".id") or base in INDONESIAN_MEDIA_DOMAINS:
        scope = "National"
    else:
        scope = "Inter"

    if base in TIER_ONE_DOMAINS:
        tier = "Tier 1"
    elif base in TIER_TWO_DOMAINS:
        tier = "Tier 2"
    else:
        tier = "Tier 3"
    return name, scope, tier


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _walk_json(item)
        for key, item in value.items():
            if key == "@graph":
                continue
            if isinstance(item, (dict, list)):
                yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def _json_ld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        nodes.extend(_walk_json(payload))
    return nodes


def _article_node(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    article_types = {"article", "newsarticle", "reportagenewsarticle", "analysisnewsarticle"}
    for node in nodes:
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(item or "").casefold() in article_types for item in types):
            return node
    return {}


def _meta(soup: BeautifulSoup, *selectors: str) -> str:
    for selector in selectors:
        element = soup.select_one(selector)
        if not element:
            continue
        value = element.get("content") or element.get("datetime") or element.get_text(" ", strip=True)
        if value and str(value).strip():
            return re.sub(r"\s+", " ", str(value)).strip()
    return ""


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or "").strip()
    return str(value or "").strip()


def _author_text(value: Any) -> str:
    authors = value if isinstance(value, list) else [value]
    names: list[str] = []
    for author in authors:
        name = _plain_text(author)
        name = re.sub(r"(?i)^\s*(?:oleh|by)\s+", "", name).strip()
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return ", ".join(names)


def _parse_publish_date(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
    if parsed is None:
        return text, ""
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}", parsed.strftime("%B")


IRRELEVANT_NODE_RE = re.compile(
    r"(?:^|[-_\s])(ad|ads|advert|advertisement|banner|breadcrumb|comment|footer|header|menu|nav|newsletter|"
    r"popup|promo|recommend|related|share|sidebar|social|subscribe)(?:$|[-_\s])",
    re.I,
)
IRRELEVANT_TEXT_RE = re.compile(
    r"^(?:advertisement|iklan|baca juga|simak juga|lihat juga|read also|related article|recommended|"
    r"bagikan artikel|share this article|subscribe|berlangganan|follow us)\b",
    re.I,
)


def _clean_candidate(candidate: Tag) -> str:
    for element in candidate.select("script, style, noscript, nav, header, footer, aside, form, iframe, svg, button"):
        element.decompose()
    for element in list(candidate.find_all(True)):
        if getattr(element, "attrs", None) is None:
            continue
        markers = " ".join(
            [str(element.get("id") or ""), *[str(item) for item in (element.get("class") or [])]]
        )
        if markers and IRRELEVANT_NODE_RE.search(markers):
            element.decompose()
    paragraphs = candidate.select("p")
    raw_parts = [paragraph.get_text(" ", strip=True) for paragraph in paragraphs]
    if not raw_parts:
        raw_parts = [candidate.get_text(" ", strip=True)]
    parts: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        text = re.sub(r"\s+", " ", raw).strip(" \t\r\n|•")
        if len(text) < 25 or IRRELEVANT_TEXT_RE.search(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(text)
    return "\n\n".join(parts)


def _extract_dom_content(soup: BeautifulSoup) -> str:
    selectors = (
        "[itemprop='articleBody']", "article", ".article-content", ".article-body",
        ".detail-content", ".entry-content", ".post-content", ".story-content", "main",
    )
    candidates: list[str] = []
    for selector in selectors:
        for element in soup.select(selector):
            # Parse a copy so cleanup does not mutate the source for another selector.
            copied = BeautifulSoup(str(element), "lxml").find()
            if isinstance(copied, Tag):
                text = _clean_candidate(copied)
                if text:
                    candidates.append(text)
    return max(candidates, key=lambda item: len(item.split()), default="")


def _clean_content(text: str) -> str:
    if re.search(r"<[^>]+>", str(text or "")):
        text = BeautifulSoup(str(text), "lxml").get_text("\n", strip=True)
    paragraphs: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\r\n]+", str(text or "")):
        cleaned = re.sub(r"\s+", " ", raw).strip(" ;|")
        if not cleaned or IRRELEVANT_TEXT_RE.search(cleaned):
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append(cleaned)
    return "\n\n".join(paragraphs)


UNAVAILABLE_MARKERS = (
    "404 not found", "article not found", "artikel tidak ditemukan", "content is unavailable",
    "halaman tidak ditemukan", "konten tidak tersedia", "page does not exist", "page not found",
    "story is unavailable", "the page you requested was not found",
)
BLOCKED_MARKERS = (
    "access denied", "enable javascript", "login untuk melanjutkan", "masuk atau daftar",
    "masuk untuk melanjutkan", "please log in", "please sign in", "please wait while your request is being verified",
    "security check", "silakan masuk", "sign in to continue", "subscribe to continue",
    "berlangganan untuk membaca",
)


def _page_state(title: str, body_text: str, content: str) -> str:
    sample = f"{title} {body_text[:1600]}".casefold()
    if any(marker in sample for marker in UNAVAILABLE_MARKERS):
        return "unavailable"
    if any(marker in sample for marker in BLOCKED_MARKERS):
        return "blocked"
    if len(content.split()) < 35:
        return "failed"
    return "available"


NEGATIVE_TERMS = (
    "ancam", "bangkrut", "bencana", "buruk", "ditangkap", "gagal", "gugatan", "jatuh",
    "kecelakaan", "kerugian", "kontroversi", "korupsi", "krisis", "masalah", "meninggal",
    "negatif", "pelanggaran", "pemecatan", "penipuan", "phk", "rugi", "skandal", "turun",
)
POSITIVE_TERMS = (
    "apresiasi", "baik", "berhasil", "bertumbuh", "capaian", "keuntungan", "menang", "naik",
    "peluang", "pemulihan", "peningkatan", "positif", "prestasi", "rekor", "sukses", "tumbuh",
    "untung",
)


def classify_tone(title: str, content: str) -> str:
    text = f"{title} {title} {content}".casefold()
    negative = sum(len(re.findall(rf"\b{re.escape(term)}\w*", text)) for term in NEGATIVE_TERMS)
    positive = sum(len(re.findall(rf"\b{re.escape(term)}\w*", text)) for term in POSITIVE_TERMS)
    if negative > positive * 1.25 and negative:
        return "Negative"
    if positive > negative * 1.25 and positive:
        return "Positive"
    return "Neutral"


PERSON_TITLES_RE = re.compile(
    r"(?i)^(?:(?:presiden|wakil presiden|menteri|wakil menteri|gubernur|wakil gubernur|bupati|"
    r"wali kota|walikota|direktur utama|direktur|komisaris utama|komisaris|ceo|chief executive officer|"
    r"ketua|sekretaris|juru bicara|jubir|kepala|prof(?:esor)?|dr|dokter|ir)\.?\s+)+"
)
NAME_PATTERN = r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+(?:[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]+)){1,4}"
ATTRIBUTION_PATTERNS = (
    re.compile(rf"(?P<name>{NAME_PATTERN})\s*,?\s*(?:mengatakan|menjelaskan|menuturkan|mengungkapkan|menegaskan|ujar|ungkap|tutur|sebut|tambah|jelas)\b"),
    re.compile(rf"\b(?:kata|ujar|menurut|ungkap|tutur|sebut|tambah|jelas)\s+(?P<name>{NAME_PATTERN})"),
)


def _clean_person_name(value: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:-")
    name = PERSON_TITLES_RE.sub("", name).strip(" ,.;:-")
    name = re.sub(r"(?i),?\s+(?:S\.?H\.?|M\.?H\.?|S\.?E\.?|M\.?B\.?A\.?|Ph\.?D\.?)$", "", name).strip()
    return name


def quote_mentions(content: str, article_node: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in ("mentions", "about"):
        values = article_node.get(key, [])
        values = values if isinstance(values, list) else [values]
        for item in values:
            if isinstance(item, dict) and str(item.get("@type") or "").casefold() == "person":
                candidates.append(_plain_text(item))
    for pattern in ATTRIBUTION_PATTERNS:
        candidates.extend(match.group("name") for match in pattern.finditer(content))

    cleaned: list[str] = []
    blocked_words = {"Pemerintah Indonesia", "Republik Indonesia", "Perseroan Terbatas"}
    for candidate in candidates:
        name = _clean_person_name(candidate)
        if not name or name in blocked_words or len(name.split()) > 5:
            continue
        if name.casefold() not in {item.casefold() for item in cleaned}:
            cleaned.append(name)
    return ", ".join(cleaned)


def _failed_result(url: str, marker: str, reason: str = "") -> ArticleResult:
    media_name, media_scope, media_tier = media_identity(url)
    return ArticleResult(
        source_url=url,
        media_name=media_name,
        media_scope=media_scope,
        media_tier=media_tier,
        title=marker,
        content=marker,
        status="unavailable" if marker == CHECK_ARTICLE_NOT_AVAILABLE else "failed",
        reason=reason,
    )


def enrich_article_html(source_url: str, html: str, resolved_url: str | None = None) -> ArticleResult:
    """Extract one article from loaded HTML while retaining the submitted URL."""
    effective_url = resolved_url or source_url
    media_name, media_scope, media_tier = media_identity(effective_url)
    soup = BeautifulSoup(html or "", "lxml")
    nodes = _json_ld_nodes(soup)
    article = _article_node(nodes)
    language = str(
        article.get("inLanguage")
        or (soup.html.get("lang") if soup.html else "")
        or _meta(soup, 'meta[property="og:locale"]')
    ).casefold()
    if media_scope == "Inter" and (language.startswith("id") or "id_id" in language):
        media_scope = "National"
    title = _plain_text(article.get("headline") or article.get("name")) or _meta(
        soup, 'meta[property="og:title"]', 'meta[name="twitter:title"]'
    )
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    structured_content = _plain_text(article.get("articleBody"))
    content = _clean_content(structured_content) or _extract_dom_content(soup)
    body_text = soup.get_text(" ", strip=True)
    state = _page_state(title, body_text, content)
    if state == "unavailable":
        return _failed_result(source_url, CHECK_ARTICLE_NOT_AVAILABLE, "Halaman artikel tidak tersedia atau telah dihapus.")
    if state != "available":
        return _failed_result(source_url, CHECK_FAILED_TO_PROCESS, "Isi artikel tidak dapat dipisahkan dari halaman.")

    published = (
        article.get("datePublished")
        or article.get("dateCreated")
        or _meta(
            soup,
            'meta[property="article:published_time"]',
            'meta[name="pubdate"]',
            'meta[name="publishdate"]',
            'time[datetime]',
        )
    )
    date_publish, month = _parse_publish_date(published)
    journalist = _author_text(article.get("author")) or _meta(
        soup, 'meta[name="author"]', 'meta[property="article:author"]'
    )
    content = _clean_content(content)
    return ArticleResult(
        source_url=source_url,
        date_publish=date_publish,
        month=month,
        media_name=media_name,
        media_scope=media_scope,
        media_tier=media_tier,
        title=re.sub(r"\s+", " ", title).strip(),
        content=content,
        journalist=_author_text(journalist),
        tone=classify_tone(title, content),
        quote_mention=quote_mentions(content, article),
    )


def enrich_public_article(url: str) -> ArticleResult:
    """Collect an article without login, classifying failures for spreadsheet review."""
    try:
        validate_public_url(url)
        html, resolved_url = fetch_public_html(url, user_agent=ARTICLE_USER_AGENT)
        return enrich_article_html(url, html, resolved_url)
    except (CollectionError, URLValidationError) as exc:
        message = str(exc)
        marker = (
            CHECK_ARTICLE_NOT_AVAILABLE
            if re.search(r"HTTP\s+(?:404|410)\b", message, re.I)
            else CHECK_FAILED_TO_PROCESS
        )
        return _failed_result(url, marker, message)
    except Exception as exc:  # Keep a row even when one publisher changes markup.
        return _failed_result(url, CHECK_FAILED_TO_PROCESS, str(exc))


class ConventionalMediaBrowser:
    """Dedicated Chrome session for publications that require authentication."""

    def __init__(self, profile_dir: Path = CONVENTIONAL_PROFILE_DIR, wait_seconds: int = 20):
        self.profile_dir = Path(profile_dir)
        self.wait_seconds = wait_seconds
        self.driver = None

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
        options.page_load_strategy = "eager"
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(self.wait_seconds + 10)
        except WebDriverException as exc:
            self.driver = None
            raise ConventionalMediaError(
                "Chrome artikel MIDETA tidak dapat dibuka. Tutup jendela sesi lama, lalu coba lagi."
            ) from exc
        return self.driver

    def open_session(self, login_url: str = "") -> None:
        driver = self.start()
        target = login_url.strip() or "https://www.google.com/"
        try:
            validate_public_url(target)
            driver.get(target)
        except (URLValidationError, WebDriverException) as exc:
            raise ConventionalMediaError("Halaman login tidak dapat dibuka di Chrome artikel MIDETA.") from exc

    def collect(self, url: str) -> ArticleResult:
        try:
            validate_public_url(url)
            driver = self.start()
            driver.get(url)
            WebDriverWait(driver, self.wait_seconds).until(
                lambda active: active.execute_script("return document.readyState") in {"interactive", "complete"}
            )
            time.sleep(1.0)
            return enrich_article_html(url, driver.page_source, str(driver.current_url or url))
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
                return enrich_article_html(url, driver.page_source, str(driver.current_url or url))
            except Exception as exc:
                return _failed_result(url, CHECK_FAILED_TO_PROCESS, str(exc))
        except (ConventionalMediaError, URLValidationError, WebDriverException) as exc:
            return _failed_result(url, CHECK_FAILED_TO_PROCESS, str(exc))

    def close(self) -> None:
        if self.driver is None:
            return
        try:
            self.driver.quit()
        except WebDriverException:
            pass
        finally:
            self.driver = None
