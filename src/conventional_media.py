# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Conventional news article enrichment for MIDETA."""
from __future__ import annotations

import html as html_lib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

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
    "type_mention",
)
CHECK_ARTICLE_NOT_AVAILABLE = "[CHECK] article not available"
CHECK_FAILED_TO_PROCESS = "[CHECK] failed to process"
CONVENTIONAL_PROFILE_DIR = DATA_DIR / "browser_profiles" / "conventional_media"
ARTICLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
_HOST_LOCKS: dict[str, threading.Lock] = {}
_HOST_LOCKS_GUARD = threading.Lock()


def _publisher_lock(url: str) -> threading.Lock:
    """Serialize requests per publisher while allowing different sites in parallel."""
    host = (urlparse(url).hostname or url).casefold()
    with _HOST_LOCKS_GUARD:
        return _HOST_LOCKS.setdefault(host, threading.Lock())


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
    type_mention: str = ""
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
            "type_mention": self.type_mention,
        }
        return {column: values[column] for column in ARTICLE_COLUMNS}


GENERIC_MEDIA_SUBDOMAINS = {
    "amp", "artikel", "article", "bisnis", "business", "digital", "economy", "ekonomi", "finance",
    "health", "internasional", "investasi", "lifestyle", "m", "money", "nasional",
    "en", "id", "inet", "market", "muslim", "news", "otomotif", "regional", "retizen",
    "soccer", "sport", "sports", "tekno", "travel", "www",
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

# Editorial classification is not reliably encoded in a domain name. These
# overrides are based on MIDETA's reviewed conventional-media reference sheet;
# the heuristic below remains the fallback for publishers that are not listed.
REGIONAL_MEDIA_HOSTS = {
    "ambon.antaranews.com", "analisadaily.com", "asarpua.com",
    "balikpapantv.jawapos.com", "balpos.com", "bandungnewsphoto.com",
    "bapenda.sumutprov.go.id", "batamnews.co.id", "beritajateng.tv",
    "beritanusa.com", "beritaprioritas.com", "biroadpim.sumutprov.go.id",
    "bisnis.espos.id", "bitvonline.com", "bolahita.id", "channelsulawesi.id",
    "cirebon.pikiran-rakyat.com", "deskjabar.pikiran-rakyat.com",
    "diskominfo.sumutprov.go.id", "dnaberita.com", "eksisnews.com",
    "fokusmedia.co.id", "forumkeadilansumut.com", "gemadika.com",
    "gerindrasumut.id", "gorontalo.antaranews.com", "greenberita.com",
    "harian.disway.id", "hariansumut.com", "indobalinews.pikiran-rakyat.com",
    "indonesiaweek.com", "infosumut.id", "inilahkoran.id", "inilahsumbar.com",
    "jabar.jpnn.com", "jabar.pikiran-rakyat.com", "jabar.tribunnews.com",
    "jabarekspres.com", "jateng.antaranews.com", "jateng.pikiran-rakyat.com",
    "jateng.tribunnews.com", "jatengnetwork.com", "jatengnow.com",
    "jatim-timur.tribunnews.com", "jatim.tribunnews.com", "javamedia.id",
    "jawapos.com", "joglosemar.inews.id", "kaldera.id", "kaltimpost.jawapos.com",
    "karebanusa.com", "kilasjatim.com", "kitamedan.com", "klikmetro.com",
    "kliksumut.com", "kotabogor.go.id", "kuasakata.com", "kupang.antaranews.com",
    "lensamedan.co.id", "lingkar.news", "lpc-online.com", "matamaluku.com",
    "medan.tribunnews.com", "medandaily.com", "mediadelegasi.id",
    "mediakampung.com", "mediasumutku.co.id", "mistar.id",
    "news.harianjogja.com", "newshanter.com", "nusantaraterkini.co",
    "nusaterkini.com", "opungnews.com", "palembang.tribunnews.com",
    "pancarpos.com", "pantura.inews.id", "pasundanekspres.id",
    "pdiperjuanganbali.id", "pewarta.co", "pikiran-rakyat.com", "pojokpapua.id",
    "politikindonesia.id", "radarbali.jawapos.com", "radarbandung.id",
    "radarbanyuwangi.jawapos.com", "radarjabar.disway.id", "radarmedan.com",
    "ratas.id", "sapos.co.id", "sekretariatdprd.sumutprov.go.id",
    "semarang.viva.co.id", "semarangsatu.com", "sidimpuanpos.com",
    "solo.tribunnews.com", "suaragarut.id", "suaraglobal.id", "suaramerdeka.com",
    "suarasumutonline.id", "sulselpedia.com", "sulteng.antaranews.com",
    "sumbar.antaranews.com", "sumsel.tribunnews.com", "sumut.pikiran-rakyat.com",
    "sumutcyber.com", "sumutpos.jawapos.com", "sumutprov.go.id",
    "surabaya.suaramerdeka.com", "surabaya.tribunnews.com", "teropongjateng.com",
    "topmetro.news", "totabuan.news", "usmtv.id", "wartadewata.com",
}
INTERNATIONAL_MEDIA_DOMAINS = {
    "apnews.com", "bbc.com", "bloomberg.com", "cnn.com", "dealstreetasia.com",
    "ft.com", "nikkei.com", "nytimes.com", "reuters.com", "theguardian.com",
    "washingtonpost.com",
}
TIER_ONE_HOSTS = {
    "ambon.antaranews.com", "analisadaily.com", "antarafoto.com",
    "antaranews.com", "asia.nikkei.com", "balikpapantv.jawapos.com", "balpos.com",
    "beritajateng.tv", "bisnis.espos.id", "bloombergtechnoz.com",
    "cnnindonesia.com", "dealstreetasia.com", "en.tempo.co",
    "gorontalo.antaranews.com", "harian.disway.id", "inet.detik.com",
    "jabar.jpnn.com", "jabar.tribunnews.com", "jabarekspres.com",
    "jateng.antaranews.com", "jateng.tribunnews.com", "jatim-timur.tribunnews.com",
    "jatim.tribunnews.com", "jawapos.com", "kaltimpost.jawapos.com",
    "katadata.co.id", "kompas.com", "kompas.tv", "kompasiana.com",
    "kontan.co.id", "kumparan.com", "kupang.antaranews.com", "liputan6.com",
    "market.bisnis.com", "medan.tribunnews.com", "money.kompas.com",
    "nasional.kompas.com", "news.detik.com", "news.harianjogja.com",
    "palembang.tribunnews.com", "radarbali.jawapos.com", "radarbandung.id",
    "radarbanyuwangi.jawapos.com", "radardepok.com", "radarjabar.disway.id",
    "rri.co.id", "sapos.co.id", "solo.tribunnews.com", "suara.com",
    "sulteng.antaranews.com", "sumbar.antaranews.com", "sumsel.tribunnews.com",
    "sumutpos.jawapos.com", "surabaya.suaramerdeka.com", "surabaya.tribunnews.com",
    "tempo.co", "tribunnews.com", "wartakota.tribunnews.com", "yoursay.suara.com",
}
TIER_TWO_HOSTS = {
    "akurat.co", "batamnews.co.id", "bogordaily.net",
    "cirebon.pikiran-rakyat.com", "deskjabar.pikiran-rakyat.com",
    "digital.okezone.com", "disway.id", "dnaberita.com", "economy.okezone.com",
    "ekonomi.republika.co.id", "emitennews.com", "fortuneidn.com", "gizmologi.id",
    "idxchannel.com", "indobalinews.pikiran-rakyat.com", "inilah.com",
    "inilahkoran.id", "inilahsumbar.com", "investor.id", "investortrust.id",
    "jabar.pikiran-rakyat.com", "jakarta.akurat.co", "jakarta.suaramerdeka.com",
    "jateng.pikiran-rakyat.com", "jatengnetwork.com", "joglosemar.inews.id",
    "kilasjatim.com", "koran-jakarta.com", "kuasakata.com", "marketeers.com",
    "medcom.id", "merdeka.com", "metrotvnews.com", "muslim.okezone.com",
    "news.republika.co.id", "pantura.inews.id", "pasardana.id",
    "pikiran-rakyat.com", "potensibisnis.pikiran-rakyat.com",
    "prfmnews.pikiran-rakyat.com", "republika.co.id", "retizen.republika.co.id",
    "rm.id", "rmol.id", "semarang.viva.co.id", "soccer.viva.co.id",
    "sumut.pikiran-rakyat.com", "tabloidbintang.com", "tirto.id",
    "tvonenews.com", "viva.co.id", "wartaekonomi.co.id",
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

    regional = host in REGIONAL_MEDIA_HOSTS or any(
        marker in host.split(".") or marker in host for marker in REGIONAL_MARKERS
    )
    if regional:
        scope = "Regional"
    elif base in INTERNATIONAL_MEDIA_DOMAINS:
        scope = "Inter"
    else:
        # MIDETA is aimed at Indonesian media monitoring. Treat an unknown
        # publisher as national unless it is in the international catalogue;
        # this avoids mislabelling Indonesian .com/.net outlets as foreign.
        scope = "National"

    if host.endswith("antaranews.com") and urlparse(url).path.startswith("/rilis-pers/"):
        tier = "Tier 3"
    elif host in TIER_ONE_HOSTS or base in TIER_ONE_DOMAINS:
        tier = "Tier 1"
    elif host in TIER_TWO_HOSTS or base in TIER_TWO_DOMAINS:
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
    if not text or re.search(r"(?:^null\b|substitution for tag|^[-+]?\d{2}:\d{2}$)", text, re.I):
        return "", ""
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            for pattern in (
                "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y",
                "%d %b %Y", "%d %B %Y",
            ):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
    if parsed is None:
        return "", ""
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}", parsed.strftime("%B")


MONTH_NAMES = {
    "januari": 1, "january": 1, "februari": 2, "february": 2,
    "maret": 3, "march": 3, "april": 4, "mei": 5, "may": 5,
    "juni": 6, "june": 6, "juli": 7, "july": 7, "agustus": 8,
    "august": 8, "september": 9, "oktober": 10, "october": 10,
    "november": 11, "desember": 12, "december": 12,
}


def _fallback_publish_date(url: str, page_text: str) -> tuple[str, str]:
    """Read a visible article date, then fall back to an explicit URL date."""
    sample = re.sub(r"\s+", " ", str(page_text or ""))[:3000]
    month_pattern = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
    match = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})\b", sample, re.I)
    if match:
        parsed = datetime(int(match.group(3)), MONTH_NAMES[match.group(2).casefold()], int(match.group(1)))
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}", parsed.strftime("%B")
    path = urlparse(url).path
    match = re.search(r"/(20\d{2})/(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/|$)", path)
    if match:
        parsed = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}", parsed.strftime("%B")
    return "", ""


IRRELEVANT_NODE_RE = re.compile(
    r"(?:^|[-_\s])(ad|ads|advert|advertisement|banner|breadcrumb|comment|footer|header|menu|nav|newsletter|"
    r"popup|promo|recommend|related|share|sidebar|social|subscribe)(?:$|[-_\s])",
    re.I,
)
IRRELEVANT_TEXT_RE = re.compile(
    r"^(?:advertisement|iklan|baca juga|simak juga|lihat juga|artikel terkait|berita terkait|"
    r"rekomendasi|pilihan editor|baca selengkapnya|lebih lanjut(?:\s+(?:klik\s+)?di sini)?|"
    r"klik(?:\s+di)?\s+sini|lanjut membaca|read also|read more|related articles?|"
    r"recommended(?: articles?)?|bagikan artikel|share this article|subscribe|berlangganan|follow us)\b",
    re.I,
)
IRRELEVANT_INLINE_RE = re.compile(
    r"\b(?:baca juga|simak juga|lihat juga|artikel terkait|berita terkait|rekomendasi|"
    r"pilihan editor|baca selengkapnya|lebih lanjut\s+(?:klik\s+)?di sini|"
    r"klik(?:\s+di)?\s+sini|lanjut membaca|read also|read more|related articles?|"
    r"recommended(?: articles?)?)\b\s*:?,?",
    re.I,
)


def _strip_irrelevant_tail(value: str) -> str:
    """Remove inline recommendations while retaining surrounding article text."""
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n|•")
    # Structured article bodies can contain several inline cards in one long
    # text node. Remove every card, rather than leaving the second one behind.
    while marker := IRRELEVANT_INLINE_RE.search(text):
        prefix = text[:marker.start()].rstrip(" ;|:–—-")
        if not prefix:
            return ""
        recommendation = text[marker.end():]
        boundary = re.search(r"[.!?](?:\s+|$)", recommendation)
        suffix = recommendation[boundary.end():].strip() if boundary else ""
        text = " ".join(part for part in (prefix, suffix) if part)
    return text


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
        text = _strip_irrelevant_tail(raw)
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
        "[itemprop='articleBody']",
        ".entry-body",
        ".artikel-body",
        ".blog-item-body",
        ".card-isi",
        ".aktual_article",
        ".primary_content",
        ".section-berita",
        ".text-article",
        ".konten",
        ".single-article-text",
        ".left-side-sidebar",
        ".read__content",
        ".detail__content",
        ".txt-article",
        "#article_con",
        ".content-inner",
        ".elementor-widget-theme-post-content",
        ".article-content",
        ".article-body",
        ".detail-content",
        ".entry-content",
        ".post-content",
        ".story-content",
        ".td-post-content",
        ".single-content",
        ".news-text",
        ".paragraph",
        ".warp-desc-news-detail",
        ".article",
        "article",
        "main",
        ".content",
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
        cleaned = _strip_irrelevant_tail(raw).strip(" ;|")
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
    "berlangganan untuk membaca", "register now to unlock premium content",
    "unlock premium content", "already registered? log in",
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


def _clean_title(value: str, media_name: str) -> str:
    """Decode entities and remove publisher chrome without rewriting a headline."""
    title = html_lib.unescape(re.sub(r"\s+", " ", str(value or ""))).strip()
    title = re.sub(
        r"(?i)^portal berita indonesia\s*\|\s*berita hari ini\s*\|\s*",
        "",
        title,
    )
    title = re.sub(r"(?i)\s+halaman\s+\d+(?=\s*(?:[-|–—]|$))", "", title)
    brand_labels = {
        re.sub(r"[^a-z0-9]", "", part.casefold())
        for part in media_name.split(".")
        if part.casefold() not in {"www", "com", "co", "id", "net", "org", "news", "tv"}
    }
    for separator in (" | ", " - ", " – ", " — "):
        if separator not in title:
            continue
        prefix, suffix = title.rsplit(separator, 1)
        suffix_key = re.sub(r"[^a-z0-9]", "", suffix.casefold())
        if suffix_key and any(
            suffix_key == brand or suffix_key in brand or brand in suffix_key
            for brand in brand_labels
        ):
            title = prefix.strip()
            break
    return title.strip(" \t\r\n-|–—")


URL_TITLE_STOPWORDS = {
    "artikel", "berita", "dalam", "dari", "dan", "dengan", "di", "ini", "itu",
    "jadi", "ke", "media", "news", "pada", "untuk", "yang", "the", "and", "of",
    "to", "a", "an", "is", "com", "co", "id", "html", "htm", "read", "detail",
}


def _url_matches_article(url: str, title: str, content: str) -> bool:
    """Reject recycled pages whose current article no longer matches the URL slug."""
    slug = unquote(urlparse(url).path.rstrip("/").split("/")[-1]).casefold()
    slug_tokens = {
        token for token in re.findall(r"[a-z][a-z0-9]{2,}", slug)
        if token not in URL_TITLE_STOPWORDS and not token.isdigit()
    }
    if len(slug_tokens) < 4:
        return True
    article_tokens = set(
        re.findall(r"[a-z][a-z0-9]{2,}", f"{title} {content[:2500]}".casefold())
    )
    brand_tokens = slug_tokens & {"gojek", "goto", "gopay", "tokopedia"}
    if brand_tokens and not brand_tokens & article_tokens:
        return False
    return len(slug_tokens & article_tokens) >= 2


NEGATIVE_TERMS = (
    "ancam", "bangkrut", "bencana", "buruk", "ditangkap", "gagal", "gugatan", "jatuh",
    "kecelakaan", "kerugian", "kontroversi", "korupsi", "krisis", "masalah", "meninggal",
    "negatif", "pelanggaran", "pemecatan", "penipuan", "phk", "rugi", "skandal", "turun",
)
POSITIVE_TERMS = (
    "apresiasi", "baik", "bantuan", "beasiswa", "berhasil", "bertumbuh", "capaian",
    "cuan", "dukung", "efisien", "jaminan", "kesehatan", "keuntungan", "kuat", "laba",
    "manfaat", "menang", "naik", "pelindungan", "perlindungan", "peluang", "pemulihan",
    "pendidikan", "peningkatan", "positif", "prestasi", "profit", "rekor", "sejahtera",
    "semarak", "sukses", "tumbuh", "unggul", "untung",
)


def classify_tone(title: str, content: str) -> str:
    text = f"{title} {title} {title} {content}".casefold()
    negative = sum(len(re.findall(rf"\b{re.escape(term)}\w*", text)) for term in NEGATIVE_TERMS)
    positive = sum(len(re.findall(rf"\b{re.escape(term)}\w*", text)) for term in POSITIVE_TERMS)
    if negative > positive * 1.25 and negative:
        return "Negative"
    if positive > negative * 1.25 and positive:
        return "Positive"
    return "Neutral"


PERSON_TITLES_RE = re.compile(
    r"(?i)^(?:(?:presiden|wakil presiden|menteri perhubungan(?:\s*\(menhub\))?|menhub|menteri|"
    r"wakil menteri|gubernur (?:sumatera utara|sumut)|gubernur|gubsu|"
    r"(?:north sumatra )?governor|wakil gubernur|bupati|"
    r"wali kota|walikota|direktur utama|direktur|komisaris utama|komisaris|ceo|chief executive officer|"
    r"hakim ketua|hakim anggota|majelis hakim|hakim|kapuspenkum kejagung|kapuspenkum|"
    r"ketua umum|ketua|sekretaris|juru bicara pt dki jakarta|juru bicara|jubir|kepala|"
    r"koordinator aksi|koordinator|direktur utama (?:pt )?(?:goto(?: gojek tokopedia)?|gojek)|"
    r"kabid humas|dirlantas|kapolres|kapolda|polda metro jaya|metro jaya|jaya|"
    r"kombes pol|kombes|kompol|akbp|iptu|aiptu|bripka|prof(?:esor)?|dr|dokter|ir|"
    r"dpr ri|dprd dki|dpr|dprd|kspsi|kasbi|agn)\.?\s+)+"
)
NAME_PATTERN = r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+(?:[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]+)){1,4}"
ATTRIBUTION_PATTERNS = (
    re.compile(
        rf"(?P<name>{NAME_PATTERN})\s*,?\s*(?i:mengatakan|menyatakan|menjelaskan|menuturkan|"
        rf"mengungkapkan|menegaskan|menyampaikan|menjawab|berkomentar|ujar|ungkap|tutur|"
        rf"sebut|tambah|papar|jelas|imbuh|said|says|stated|explained|told)\b",
    ),
    re.compile(
        rf"\b(?i:kata|ujar|menurut|ungkap|tutur|sebut|tambah|papar|jelas|imbuh|"
        rf"according to)\s+(?P<name>{NAME_PATTERN})",
    ),
)
MENTION_ACTION_PATTERNS = (
    re.compile(
        rf"(?P<name>{NAME_PATTERN})\s+(?:(?i:has|have|had|is|was)\s+)?"
        rf"(?i:mendorong|memastikan|menilai|mengapresiasi|menyoroti|"
        rf"meminta|mendukung|meninjau|memimpin|menghadiri|mengumumkan|meresmikan|menyebut|"
        rf"menegaskan|backs|backed|supports|supported|urges|urged|asks|asked|ensures|"
        rf"highlighted|announced)\b"
    ),
)
SINGLE_NAME_ATTRIBUTION_PATTERNS = (
    re.compile(
        r"\b(?P<name>[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,})\s+(?i:mengatakan|menyatakan|"
        r"menjelaskan|menuturkan|mengungkapkan|menegaskan|menyampaikan|ujar|ungkap|tutur|"
        r"sebut|tambah|papar|jelas|imbuh|said|says|stated|explained|told)\b"
    ),
    re.compile(
        r"\b(?i:kata|ujar|menurut|ungkap|tutur|sebut|tambah|papar|jelas|imbuh)\s+"
        r"(?P<name>[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]{2,})\b"
    ),
)
PERSON_NAME_ALIASES = {
    "bobby": "Bobby Nasution",
    "hans": "Hans Patuwo",
    "hans pakuwo": "Hans Patuwo",
    "pakuwo": "Hans Patuwo",
    "gojek hans patuwo": "Hans Patuwo",
    "goto hans patuwo": "Hans Patuwo",
    "muhammad bobby afif nasution": "Bobby Nasution",
    "muhammad bobby nasution": "Bobby Nasution",
    "sumatera utara muhammad bobby afif nasution": "Bobby Nasution",
    "utara muhammad bobby afif nasution": "Bobby Nasution",
    "gubsu bobby nasution": "Bobby Nasution",
}


def _clean_person_name(value: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:-")
    name = PERSON_TITLES_RE.sub("", name).strip(" ,.;:-")
    name = re.sub(
        r"(?i)^(?:pt\s+)?(?:goto(?:\s+gojek\s+tokopedia)?|gojek)\s+",
        "",
        name,
    ).strip(" ,.;:-")
    name = re.sub(
        r"(?i)^partai\s+(?:demokrasi indonesia perjuangan|gerakan indonesia raya|golongan karya|"
        r"kebangkitan bangsa|keadilan sejahtera|amanat nasional|nasional demokrat|"
        r"persatuan pembangunan|solidaritas indonesia|demokrat|gerindra|golkar|nasdem|"
        r"hanura|perindo|buruh)\s+",
        "",
        name,
    ).strip(" ,.;:-")
    name = re.sub(r"^(?:(?:[A-Z]{2,})(?:\s+|$))+", "", name).strip(" ,.;:-")
    name = re.sub(r"(?i)^(?:dki\s+)?jakarta\s+(?=[A-ZÀ-ÖØ-Ý])", "", name).strip(" ,.;:-")
    name = re.sub(r"(?i),?\s+(?:S\.?H\.?|M\.?H\.?|S\.?E\.?|M\.?B\.?A\.?|Ph\.?D\.?)$", "", name).strip()
    name = PERSON_NAME_ALIASES.get(name.casefold(), name)
    non_person_words = {
        "aksi", "alasan", "anak", "asosiasi", "badan", "berita", "buruh", "company", "dana", "dampak",
        "bpjs", "country", "demokrat", "direktur", "dirlantas", "dpr", "dprd", "federasi",
        "foundation", "gerindra", "gojek", "goto", "governor", "gubernur", "gubsu",
        "anggota", "eks", "golkar", "hakim", "hanura", "hukum", "indonesia", "instansi", "jalan", "jaya",
        "kejagung", "kebijakan", "kementerian", "koalisi", "kombes", "komisi", "konfederasi",
        "kapuspenkum", "kepesertaan", "kesehatan", "ketua", "krakatau", "lembaga",
        "mahkamah", "majelis", "manajemen", "manager", "massa", "maxim", "media", "metro",
        "ministry", "nasdem", "negara", "organisasi", "pejabat", "perkuat", "putusan",
        "partai", "pekerja", "pemerintah", "perindo", "perjuangan", "perseroan", "perusahaan", "polisi",
        "polda", "penopang", "redaksi", "republik", "rasuna", "ruu", "saham", "serikat", "sumber", "tim", "tuntutan",
        "kesaksian",
        "union", "utama", "yayasan",
    }
    name_words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", name.casefold())
    if (
        not name_words
        or any(part in non_person_words for part in name_words)
        or re.search(r"\d|https?://|www\.", name, re.I)
    ):
        return ""
    return name


def _same_person_name(first: str, second: str) -> bool:
    first_key = first.casefold()
    second_key = second.casefold()
    if first_key == second_key:
        return True
    first_parts = first_key.split()
    second_parts = second_key.split()
    is_prefix = first_key.startswith(f"{second_key} ") or second_key.startswith(f"{first_key} ")
    if min(len(first_parts), len(second_parts)) >= 2 and is_prefix:
        return True
    short_parts = first_parts if len(first_parts) < len(second_parts) else second_parts
    if len(short_parts) == 1 and len(short_parts[0]) >= 4:
        long_parts = second_parts if short_parts is first_parts else first_parts
        return short_parts[0] in long_parts
    return False


def _mention_details(content: str, article_node: dict[str, Any], title: str = "") -> list[tuple[str, str]]:
    candidates: list[str] = []
    for key in ("mentions", "about"):
        values = article_node.get(key, [])
        values = values if isinstance(values, list) else [values]
        for item in values:
            if isinstance(item, dict) and str(item.get("@type") or "").casefold() == "person":
                candidates.append(_plain_text(item))
    direct_candidates = [
        _clean_person_name(match.group("name"))
        for pattern in ATTRIBUTION_PATTERNS
        for match in pattern.finditer(content)
    ]
    single_direct_candidates = [
        _clean_person_name(match.group("name"))
        for pattern in SINGLE_NAME_ATTRIBUTION_PATTERNS
        for match in pattern.finditer(content)
    ]
    action_candidates = [
        _clean_person_name(match.group("name"))
        for pattern in MENTION_ACTION_PATTERNS
        for match in pattern.finditer(f"{title}. {content}")
    ]
    candidates.extend(action_candidates)
    candidates.extend(direct_candidates)
    candidates.extend(single_direct_candidates)
    direct_names = [name for name in direct_candidates if name]
    direct_aliases = [name for name in single_direct_candidates if name]

    cleaned: list[tuple[str, str]] = []
    seen: set[str] = set()
    blocked_words = {"Pemerintah Indonesia", "Republik Indonesia", "Perseroan Terbatas"}
    for candidate in candidates:
        name = _clean_person_name(candidate)
        if not name or name in blocked_words or len(name.split()) > 5:
            continue
        key = name.casefold()
        mention_type = "direct" if (
            any(_same_person_name(name, direct) for direct in direct_names)
            or any(alias.casefold() in name.casefold().split() for alias in direct_aliases)
        ) else "indirect"
        matched_index = next(
            (index for index, (saved_name, _) in enumerate(cleaned) if _same_person_name(name, saved_name)),
            None,
        )
        if matched_index is not None:
            saved_name, saved_type = cleaned[matched_index]
            preferred_name = name if len(name.split()) > len(saved_name.split()) else saved_name
            preferred_type = "direct" if "direct" in (mention_type, saved_type) else "indirect"
            cleaned[matched_index] = (preferred_name, preferred_type)
            continue
        if key not in seen:
            seen.add(key)
            cleaned.append((name, mention_type))
    return cleaned


def quote_mentions(content: str, article_node: dict[str, Any], title: str = "") -> str:
    return ", ".join(name for name, _ in _mention_details(content, article_node, title))


def type_mentions(content: str, article_node: dict[str, Any], title: str = "") -> str:
    return ", ".join(
        f"{name} ({mention_type})"
        for name, mention_type in _mention_details(content, article_node, title)
    )


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
    if not title:
        title = _meta(soup, "article h1", ".entry-title", ".post-title", "h1")
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    title = _clean_title(title, media_name)

    structured_content = _clean_content(_plain_text(article.get("articleBody")))
    dom_content = _extract_dom_content(soup)
    content = max(
        (structured_content, dom_content),
        key=lambda item: len(item.split()),
    )
    body_text = soup.get_text(" ", strip=True)
    state = _page_state(title, body_text, content)
    if state == "unavailable":
        return _failed_result(source_url, CHECK_ARTICLE_NOT_AVAILABLE, "Halaman artikel tidak tersedia atau telah dihapus.")
    if state != "available":
        return _failed_result(source_url, CHECK_FAILED_TO_PROCESS, "Isi artikel tidak dapat dipisahkan dari halaman.")
    if not _url_matches_article(effective_url, title, content):
        return _failed_result(
            source_url,
            CHECK_FAILED_TO_PROCESS,
            "Konten halaman tidak sesuai dengan URL artikel. Halaman kemungkinan telah diganti penerbit.",
        )

    published = (
        article.get("datePublished")
        or article.get("dateCreated")
        or _meta(
            soup,
            'meta[property="article:published_time"]',
            'meta[name="pubdate"]',
            'meta[name="publishdate"]',
            'meta[name="date"]',
            'meta[itemprop="datePublished"]',
            'meta[property="og:published_time"]',
            '.blog-date',
            '.date-cont',
            'time.entry-date[datetime]',
            'time.published[datetime]',
            'time[datetime]',
        )
    )
    date_publish, month = _parse_publish_date(published)
    if not date_publish:
        date_publish, month = _fallback_publish_date(effective_url, f"{title} {content}")
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
        title=title,
        content=content,
        journalist=_author_text(journalist),
        tone=classify_tone(title, content),
        quote_mention=quote_mentions(content, article, title),
        type_mention=type_mentions(content, article, title),
    )


def _enrich_public_article_unlocked(url: str) -> ArticleResult:
    """Collect an article without login, classifying failures for spreadsheet review."""
    try:
        validate_public_url(url)
        try:
            html, resolved_url = fetch_public_html(url, user_agent=ARTICLE_USER_AGENT)
        except CollectionError as exc:
            if not re.search(r"(?:HTTP\s+5\d\d|tidak dapat dihubungi)", str(exc), re.I):
                raise
            time.sleep(0.6)
            html, resolved_url = fetch_public_html(url, user_agent=ARTICLE_USER_AGENT)
        result = enrich_article_html(url, html, resolved_url)
        if result.status == "failed" and result.reason.startswith("Isi artikel"):
            # Some publishers intermittently return a shell page while their
            # article cache is warming. One bounded retry is enough; rows are
            # still preserved as failed when the second response is unchanged.
            time.sleep(0.4)
            try:
                fresh_html, fresh_resolved_url = fetch_public_html(
                    url,
                    user_agent=ARTICLE_USER_AGENT,
                )
                fresh_result = enrich_article_html(url, fresh_html, fresh_resolved_url)
                if fresh_result.status != "failed":
                    return fresh_result
                html, resolved_url, result = fresh_html, fresh_resolved_url, fresh_result
            except CollectionError:
                pass
        parsed = urlparse(resolved_url)
        if (
            result.status == "failed"
            and (parsed.hostname or "").casefold().endswith("jawapos.com")
            and not parsed.path.startswith("/amp/")
        ):
            amp_url = parsed._replace(
                path=f"/amp{parsed.path}",
                query="",
                fragment="",
            ).geturl()
            amp_html, amp_resolved_url = fetch_public_html(amp_url, user_agent=ARTICLE_USER_AGENT)
            amp_result = enrich_article_html(url, amp_html, amp_resolved_url)
            if amp_result.status == "completed":
                return amp_result
        if result.status == "failed":
            page = BeautifulSoup(html, "lxml")
            amp_link = page.select_one('link[rel="amphtml"][href]')
            amp_url = urljoin(resolved_url, str(amp_link.get("href") or "").strip()) if amp_link else ""
            if amp_url:
                try:
                    amp_html, amp_resolved_url = fetch_public_html(
                        amp_url,
                        user_agent=ARTICLE_USER_AGENT,
                    )
                    amp_result = enrich_article_html(url, amp_html, amp_resolved_url)
                    if amp_result.status == "completed":
                        return amp_result
                except (CollectionError, URLValidationError):
                    pass
        return result
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


def enrich_public_article(url: str) -> ArticleResult:
    """Collect one public article without overlapping requests to the same publisher."""
    with _publisher_lock(url):
        return _enrich_public_article_unlocked(url)


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
