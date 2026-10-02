# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Conventional news article enrichment for MIDETA."""
from __future__ import annotations

import csv
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
from zoneinfo import ZoneInfo

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
SWA_CRAWLING_NOTICE = "dilarang craweling"
CONVENTIONAL_PROFILE_DIR = DATA_DIR / "browser_profiles" / "conventional_media"
CONVENTIONAL_MEDIA_CATALOG_PATH = (
    Path(__file__).resolve().parent / "data" / "conventional_media_tiering.tsv"
)
ARTICLE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)
_HOST_LOCKS: dict[str, threading.Lock] = {}
_HOST_LOCKS_GUARD = threading.Lock()


def _load_conventional_media_catalog() -> dict[str, tuple[str, str, str]]:
    """Load the reviewed domain identity and tier catalogue shipped with MIDETA."""
    if not CONVENTIONAL_MEDIA_CATALOG_PATH.exists():
        return {}
    catalog: dict[str, tuple[str, str, str]] = {}
    with CONVENTIONAL_MEDIA_CATALOG_PATH.open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"domain", "media_name", "media_scope", "media_tier"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Database conventional media memiliki header yang tidak valid.")
        for line_number, row in enumerate(reader, start=2):
            domain = str(row.get("domain") or "").casefold().strip().strip(".")
            if domain.startswith("www."):
                domain = domain[4:]
            if not domain:
                continue
            if domain in catalog:
                raise ValueError(
                    f"Domain conventional media duplikat pada baris {line_number}: {domain}"
                )
            media_name = str(row.get("media_name") or "").strip() or domain.upper()
            media_scope = str(row.get("media_scope") or "").strip()
            media_tier = str(row.get("media_tier") or "").strip()
            if media_tier not in {"Tier 1", "Tier 2", "Tier 3"}:
                raise ValueError(
                    f"Tier conventional media tidak valid pada baris {line_number}: {media_tier}"
                )
            catalog[domain] = (media_name, media_scope, media_tier)
    return catalog


CONVENTIONAL_MEDIA_CATALOG = _load_conventional_media_catalog()


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
    catalog_identity = CONVENTIONAL_MEDIA_CATALOG.get(host)
    if catalog_identity is not None:
        name, scope, tier = catalog_identity
        if host.endswith("antaranews.com") and urlparse(url).path.startswith("/rilis-pers/"):
            tier = "Tier 3"
        return name, scope, tier

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
        scope = "International"
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


def _article_node(nodes: list[dict[str, Any]], expected_url: str = "") -> dict[str, Any]:
    """Choose the article node that belongs to the submitted URL.

    News sites often include JSON-LD for recommendations after the primary
    story. Taking the first ``NewsArticle`` can therefore attach another
    article's date to the requested row.
    """
    article_types = {"article", "newsarticle", "reportagenewsarticle", "analysisnewsarticle"}
    articles: list[dict[str, Any]] = []
    for node in nodes:
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(item or "").casefold() in article_types for item in types):
            articles.append(node)
    if not articles:
        return {}

    expected = urlparse(expected_url)
    expected_host = (expected.hostname or "").casefold().removeprefix("www.")
    expected_path = unquote(expected.path).rstrip("/")

    def node_urls(node: dict[str, Any]) -> list[str]:
        values: list[Any] = [node.get("url"), node.get("@id"), node.get("mainEntityOfPage")]
        urls: list[str] = []
        for value in values:
            if isinstance(value, dict):
                value = value.get("@id") or value.get("url")
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())
        return urls

    def score(node: dict[str, Any]) -> int:
        value = 0
        for candidate_url in node_urls(node):
            parsed = urlparse(candidate_url)
            candidate_host = (parsed.hostname or "").casefold().removeprefix("www.")
            candidate_path = unquote(parsed.path).rstrip("/")
            if expected_path and candidate_path == expected_path:
                value += 100
            elif expected_path and (
                candidate_path.endswith(expected_path) or expected_path.endswith(candidate_path)
            ):
                value += 60
            if expected_host and candidate_host == expected_host:
                value += 10
        if _plain_text(node.get("articleBody")):
            value += 15
        if _plain_text(node.get("headline") or node.get("name")):
            value += 5
        if node.get("datePublished"):
            value += 2
        return value

    return max(articles, key=score)


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


def _format_publish_date(parsed: datetime) -> tuple[str, str]:
    if parsed.tzinfo is not None:
        try:
            parsed = parsed.astimezone(ZoneInfo("Asia/Jakarta"))
        except (KeyError, ValueError):
            pass
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}", parsed.strftime("%B")


def _parse_publish_date(value: Any) -> tuple[str, str]:
    text = html_lib.unescape(str(value or "")).strip().lstrip("<")
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
        month_pattern = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
        match = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})\b", text, re.I)
        if match:
            parsed = datetime(
                int(match.group(3)),
                MONTH_NAMES[match.group(2).casefold()],
                int(match.group(1)),
            )
        if parsed is None:
            match = re.search(r"\b(0?[1-9]|[12]\d|3[01])[/-](0?[1-9]|1[0-2])[/-](20\d{2})\b", text)
            if match:
                try:
                    parsed = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
                except ValueError:
                    parsed = None
        if parsed is None:
            match = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b", text)
            if match:
                try:
                    parsed = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                except ValueError:
                    parsed = None
    return _format_publish_date(parsed) if parsed is not None else ("", "")


MONTH_NAMES = {
    "januari": 1, "january": 1, "februari": 2, "february": 2,
    "maret": 3, "march": 3, "april": 4, "mei": 5, "may": 5,
    "juni": 6, "june": 6, "juli": 7, "july": 7, "agu": 8, "agt": 8, "agustus": 8,
    "august": 8, "september": 9, "oktober": 10, "october": 10,
    "november": 11, "des": 12, "desember": 12, "december": 12,
}


def _url_publish_date(url: str) -> tuple[str, str]:
    """Read only unambiguous calendar dates encoded in an article URL."""
    path = unquote(urlparse(url).path)
    patterns = (
        # Syndication URLs: /info/t-2608221600.html -> 22 Aug 2026.
        (r"/info/t-(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{4}(?:\.html)?(?:/|$)", "yymmdd"),
        # Bisnis-style URLs: /read/20260813/9/...
        (r"/read/(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:/|$)", "yyyymmdd"),
        (r"/(20\d{2})/(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/|$)", "yyyymmdd"),
    )
    for pattern, kind in patterns:
        match = re.search(pattern, path, re.I)
        if not match:
            continue
        year = 2000 + int(match.group(1)) if kind == "yymmdd" else int(match.group(1))
        try:
            return _format_publish_date(datetime(year, int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    return "", ""


def _visible_publish_date(soup: BeautifulSoup, *, include_modified: bool = False) -> tuple[str, str]:
    selectors = [
        'time[itemprop="datePublished"][datetime]',
        'time.published[datetime]',
        'time.entry-date[datetime]',
        '.blog-date',
        '.date-cont',
        '.published-date',
        '.publish-date',
        '.article-date',
        '.post-date',
        '.entry-date',
        '.news-date',
        '.detail-date',
        '[class*="date-publish"]',
        '[class*="publish-date"]',
    ]
    if include_modified:
        selectors.insert(0, 'time[itemprop="dateModified"][datetime]')
    for selector in selectors:
        for element in soup.select(selector):
            parsed = _parse_publish_date(
                element.get("datetime") or element.get("content") or element.get_text(" ", strip=True)
            )
            if parsed[0]:
                return parsed
    return "", ""


def _date_distance(first: tuple[str, str], second: tuple[str, str]) -> int | None:
    if not first[0] or not second[0]:
        return None
    try:
        first_date = datetime.strptime(first[0], "%b %d, %Y")
        second_date = datetime.strptime(second[0], "%b %d, %Y")
    except ValueError:
        return None
    return abs((first_date - second_date).days)


def _extract_publish_date(
    soup: BeautifulSoup,
    article: dict[str, Any],
    url: str,
    contextual_text: str,
) -> tuple[str, str]:
    """Resolve publication date from strongest to weakest article evidence."""
    encoded = _url_publish_date(url)
    if encoded[0]:
        return encoded

    host = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    # ANTARA currently exposes a recycled datePublished value in JSON-LD on
    # some regional pages while the article header time remains correct.
    visible = _visible_publish_date(soup, include_modified=host.endswith("antaranews.com"))
    if visible[0]:
        return visible

    structured_values = (
        article.get("datePublished"),
        _meta(soup, 'meta[property="article:published_time"]'),
        _meta(soup, 'meta[name="pubdate"]'),
        _meta(soup, 'meta[name="publishdate"]'),
        _meta(soup, 'meta[itemprop="datePublished"]'),
        _meta(soup, 'meta[property="og:published_time"]'),
    )
    structured = next(
        (parsed for value in structured_values if (parsed := _parse_publish_date(value))[0]),
        ("", ""),
    )
    contextual = _parse_publish_date(re.sub(r"\s+", " ", contextual_text or "")[:1600])
    distance = _date_distance(structured, contextual)
    if contextual[0] and (not structured[0] or (distance is not None and distance >= 45)):
        return contextual
    if structured[0]:
        return structured

    for weak_value in (
        article.get("dateCreated"),
        _meta(soup, 'meta[name="date"]'),
    ):
        parsed = _parse_publish_date(weak_value)
        if parsed[0]:
            return parsed
    return "", ""


def _fallback_publish_date(url: str, page_text: str) -> tuple[str, str]:
    """Read a visible article date, then fall back to an explicit URL date."""
    encoded = _url_publish_date(url)
    if encoded[0]:
        return encoded
    sample = re.sub(r"\s+", " ", str(page_text or ""))[:3000]
    month_pattern = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
    match = re.search(rf"\b(\d{{1,2}})\s+({month_pattern})\s+(20\d{{2}})\b", sample, re.I)
    if match:
        parsed = datetime(int(match.group(3)), MONTH_NAMES[match.group(2).casefold()], int(match.group(1)))
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}", parsed.strftime("%B")
    return "", ""


IRRELEVANT_NODE_RE = re.compile(
    r"(?:^|[-_\s])(ad|ads|advert|advertisement|banner|breadcrumb|caption|comment|footer|header|menu|nav|newsletter|"
    r"popup|promo|recommend|related|share|sidebar|social|subscribe)(?:$|[-_\s])",
    re.I,
)
IRRELEVANT_TEXT_RE = re.compile(
    r"^(?:advertisement|iklan|baca juga|simak juga|lihat juga|artikel terkait|berita terkait|"
    r"rekomendasi|pilihan editor|baca selengkapnya|lebih lanjut(?:\s+(?:klik\s+)?di sini)?|"
    r"klik(?:\s+di)?\s+sini|lanjut membaca|read also|read more|related articles?|"
    r"recommended(?: articles?)?|bagikan artikel|share this article|subscribe|berlangganan|follow us|"
    r"reporter\s*:|editor\s*:|penulis\s*:|author\s*:)\b",
    re.I,
)
PROMOTIONAL_SENTENCE_RE = re.compile(
    r"\b(?:portal\s+\S+\s+dapat\s+diakses\s+melalui|pendaftaran\s+program\b|"
    r"informasi\s+pembelajaran\b.*?\btersedia\s+melalui\b).*?"
    r"(?:\.(?=\s+[A-ZÀ-ÖØ-Ý“])|\.$|$)",
    re.I | re.S,
)
IRRELEVANT_INLINE_RE = re.compile(
    r"\b(?:baca juga|simak juga|lihat juga|artikel terkait|berita terkait|rekomendasi|"
    r"pilihan editor|baca selengkapnya|lebih lanjut\s+(?:klik\s+)?di sini|"
    r"klik(?:\s+di)?\s+sini|lanjut membaca|read also|read more|related articles?|"
    r"recommended(?: articles?)?)\b\s*:?,?",
    re.I,
)
IRRELEVANT_TAIL_RE = re.compile(
    r"\b(?:berlangganan\s+selanjutnya|baca\s+artikel\s+selanjutnya|artikel\s+selanjutnya|"
    r"baca\s+berita\s+lainnya|berita\s+lainnya|artikel\s+lainnya|memuat\s+berita\s+terbaru|"
    r"isi\s+komentar\s+sepenuhnya\s+adalah\s+tanggung\s+jawab|"
    r"pewarta\s*:|copyright\s*[©\u00a9]|dilarang\s+keras\s+mengambil\s+konten|"
    r"dilarang\s+mengambil\s+dan/atau\s+menayangkan\s+ulang|"
    r"disclaimer\s*:\s*this\s+article\s+was\s+automatically\s+rewritten|"
    r"follow\s+channel\s+telegram|cek\s+berita\s+dan\s+artikel\s+(?:lainnya|yang\s+lain)|"
    r"temukan\s+berita\s+terkini|dapatkan\s+update\s+berita|nyaman\s+tanpa\s+iklan|"
    r"cek\s+berita\s+teknologi|mau\s+berita\s+menarik\s+lainnya|"
    r"update\s+berita\s+dan\s+artikel|silakan\s+baca\s+konten\s+menarik\s+lainnya|"
    r"read\s+full\s+article(?:\s+on\b)?|teks\s+foto\s*:|"
    r"make\s+the\s+article\s+one\s+line\s+only(?:remove\s+remaining\s+article\s+headings)?|"
    r"remove\s+remaining\s+article\s+headings|"
    r"tag\s*:|sumber\s*:\s*berita\s+bisnis\s+hari\s+terbaru)(?=\s|[:|–—.!?-]|$)",
    re.I,
)
RAW_JSON_TAIL_RE = re.compile(r"\{\s*[\"']title[\"']\s*:\s*[\"']", re.I)
COPYRIGHT_TAIL_RE = re.compile(r"(?:©|\u00a9)\s*(?:19|20)\d{2}\s+konten\s+oleh\b", re.I)
BYLINE_ONLY_RE = re.compile(
    r"^(?:(?:reporter|editor|penulis|author)\s*:\s*[^|\n]{2,100}"
    r"(?:\s*\|\s*)?)+$",
    re.I,
)


def _strip_irrelevant_tail(value: str) -> str:
    """Remove inline recommendations while retaining surrounding article text."""
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n|•")
    if BYLINE_ONLY_RE.fullmatch(text):
        return ""
    text = PROMOTIONAL_SENTENCE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Publisher footers and next-article modules are terminal: everything
    # after the first marker belongs to navigation, legal copy, or another
    # story rather than to the submitted article.
    if marker := IRRELEVANT_TAIL_RE.search(text):
        text = text[:marker.start()].rstrip(" ;|:–—-.")
    for tail_pattern in (RAW_JSON_TAIL_RE, COPYRIGHT_TAIL_RE):
        if marker := tail_pattern.search(text):
            text = text[:marker.start()].rstrip(" ;|:–—-.")
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
    # Lowercase parenthetical signatures and production notes at the very end
    # belong to the byline/credit, not the article body.
    text = re.sub(
        r"\s*\(\s*[a-zà-öø-ÿ][a-zà-öø-ÿ .'’-]{2,50}\s*\)\s*$",
        "",
        text,
    ).rstrip()
    return text


def _clean_candidate(candidate: Tag) -> str:
    for element in candidate.select(
        "script, style, noscript, nav, header, footer, aside, form, iframe, svg, button, figure, figcaption"
    ):
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
        terminal_marker = IRRELEVANT_TAIL_RE.search(re.sub(r"\s+", " ", raw))
        text = _strip_irrelevant_tail(raw)
        if len(text) < 25 or IRRELEVANT_TEXT_RE.search(text):
            if terminal_marker:
                break
            continue
        key = text.casefold()
        if key in seen:
            if terminal_marker:
                break
            continue
        seen.add(key)
        parts.append(text)
        if terminal_marker:
            break
    return "\n\n".join(parts)


def _extract_dom_content(soup: BeautifulSoup) -> str:
    selectors = (
        "[itemprop='articleBody']",
        "#berita_content_sub",
        "#sub_content",
        "#berita_panel",
        ".berita_content_sub",
        ".sub_content",
        ".news-detail-content",
        ".news-detail",
        ".berita_panel",
        ".c-detail.read",
        ".bodyArticleWrapper",
        ".mainBody",
        ".owl-carousel .item",
        ".entry-body",
        ".artikel-body",
        ".blog-item-body",
        ".card-isi",
        ".aktual_article",
        ".tmpt-desk-kon",
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
    for selector in selectors:
        candidates: list[str] = []
        for element in soup.select(selector):
            # Parse a copy so cleanup does not mutate the source for another selector.
            copied = BeautifulSoup(str(element), "lxml").find()
            if isinstance(copied, Tag):
                text = _clean_candidate(copied)
                if text:
                    candidates.append(text)
        # Selectors are ordered from article-specific to generic. Returning
        # the first usable wrapper prevents a large page/footer container from
        # winning only because it contains more words.
        usable = [item for item in candidates if len(item.split()) >= 35]
        if usable:
            return max(usable, key=lambda item: len(item.split()))
    return ""


def _recover_embedded_article_content(value: str) -> str:
    """Recover article copy accidentally embedded as a JSON-like text suffix.

    A few publishers concatenate an unfinished teaser with a serialized editor
    payload. The payload is not always valid JSON because quotes inside the
    article are left unescaped, so recover its ``content`` value conservatively
    instead of exporting the object or leaving a cut-off sentence.
    """
    text = str(value or "")
    marker = RAW_JSON_TAIL_RE.search(text)
    if not marker:
        return text
    payload = text[marker.start():]
    content_marker = re.search(r"[\"']content[\"']\s*:\s*[\"']", payload, re.I)
    if not content_marker:
        return text[:marker.start()]
    recovered = payload[content_marker.end():].strip()
    recovered = re.sub(r"[\"']\s*}\s*$", "", recovered).strip()
    recovered = recovered.replace(r"\n", "\n").replace(r'\"', '"')
    if len(recovered.split()) >= 35:
        return recovered
    return text[:marker.start()]


def _clean_content(text: str) -> str:
    text = _recover_embedded_article_content(str(text or ""))
    if re.search(r"<[^>]+>", str(text or "")):
        text = BeautifulSoup(str(text), "lxml").get_text("\n", strip=True)
    paragraphs: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\r\n]+", str(text or "")):
        terminal_marker = IRRELEVANT_TAIL_RE.search(re.sub(r"\s+", " ", raw))
        cleaned = _strip_irrelevant_tail(raw).strip(" ;|")
        if not cleaned or IRRELEVANT_TEXT_RE.search(cleaned):
            if terminal_marker:
                break
            continue
        key = cleaned.casefold()
        if key in seen:
            if terminal_marker:
                break
            continue
        seen.add(key)
        paragraphs.append(cleaned)
        if terminal_marker:
            break
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
NAVIGATION_ONLY_RE = re.compile(
    r"\b(?:related|latest\s+news|berita\s+terkait|artikel\s+terkait|foto\s+lainnya)\b",
    re.I,
)


def _page_state(title: str, body_text: str, content: str) -> str:
    sample = f"{title} {body_text[:1600]}".casefold()
    if any(marker in sample for marker in UNAVAILABLE_MARKERS):
        return "unavailable"
    if any(marker in sample for marker in BLOCKED_MARKERS):
        return "blocked"
    if len(content.split()) < 35:
        return "failed"
    # Some JavaScript-first publishers return only the headline and a short
    # carousel of related links to non-browser clients. Do not mislabel that
    # navigation shell as successfully extracted article copy.
    if len(content.split()) < 120 and NAVIGATION_ONLY_RE.search(content):
        return "failed"
    return "available"


def _clean_title(value: str, media_name: str) -> str:
    """Decode entities and remove publisher chrome without rewriting a headline."""
    title = html_lib.unescape(re.sub(r"\s+", " ", str(value or ""))).strip()
    title = re.split(
        r"(?i)\s+(?:artikel\s+ini\s+adalah\s+bagian\s+dari\b|baca\s+selengkapnya\s+di\s*:)",
        title,
        maxsplit=1,
    )[0].strip()
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
    "ambles", "ancam", "anjlok", "bangkrut", "bencana", "buruk", "ditangkap", "gagal", "gugatan", "jatuh",
    "decline", "downturn", "drop", "kecelakaan", "kerugian", "kontroversi", "korupsi", "krisis", "masalah", "meninggal",
    "melemah", "merosot", "musnah", "negatif", "pelanggaran", "pemecatan", "penipuan", "phk",
    "plummet", "rugi", "selling pressure", "skandal", "tekanan", "tergerus", "terkoreksi", "terpangkas", "tertekan", "turun",
)
POSITIVE_TERMS = (
    "apresiasi", "baik", "bantuan", "beasiswa", "berhasil", "bertumbuh", "capaian",
    "cuan", "dukung", "efisien", "euforia", "gain", "growth", "improve", "jaminan", "kesehatan", "keuntungan", "kuat", "laba", "lonjak", "menarik",
    "manfaat", "membaik", "melompat", "menang", "menguat", "murah", "naik", "opportunity", "pelindungan", "perlindungan", "peluang", "pemulihan",
    "pendidikan", "peningkatan", "positif", "prestasi", "profit", "rekor", "sejahtera",
    "semarak", "stabil", "strong", "sukses", "support", "tumbuh", "unggul", "untung",
)
TONE_GENERIC_ACRONYMS = {
    "ARA", "ARB", "BEI", "CEO", "DCF", "EBITDA", "FTSE", "GEIS", "IHSG", "LQ45",
    "MSCI", "OJK", "PBV", "PER", "RUPS", "RUPSLB", "SOTP",
}


def classify_tone(title: str, content: str) -> str:
    # Financial roundups often mix winners and losers. When the headline names
    # tickers, score paragraphs about those subjects so another company's rally
    # does not overwrite the submitted article's actual focus.
    focus_terms = {
        token
        for token in re.findall(r"\b[A-Z][A-Z0-9]{1,7}\b", str(title or ""))
        if token not in TONE_GENERIC_ACRONYMS and not token.isdigit()
    }
    focused_content = str(content or "")
    if focus_terms:
        sentences = re.split(r"(?<=[.!?])\s*|[\r\n]+", focused_content)
        matching = [
            sentence
            for sentence in sentences
            if any(re.search(rf"\b{re.escape(term)}\b", sentence, re.I) for term in focus_terms)
        ]
        if matching:
            focused_content = " ".join(matching)
    text = f"{title} {title} {title} {focused_content}".casefold()
    negative = sum(len(re.findall(rf"\b{re.escape(term)}\w*", text)) for term in NEGATIVE_TERMS)
    positive = sum(len(re.findall(rf"\b{re.escape(term)}\w*", text)) for term in POSITIVE_TERMS)
    if negative > positive * 1.35 and negative:
        return "Negative"
    if positive > negative * 1.35 and positive:
        return "Positive"
    return "Neutral"


PERSON_TITLES_RE = re.compile(
    r"(?i)^(?:(?:presiden|wakil presiden|menteri perhubungan(?:\s*\(menhub\))?|menhub|menteri|"
    r"wakil menteri|gubernur (?:sumatera utara|sumut)|gubernur|gubsu|"
    r"(?:north sumatra )?governor|wakil gubernur|bupati|"
    r"wali kota|walikota|direktur dan sekretaris perusahaan|direktur utama|direktur|"
    r"komisaris utama|komisaris|analis(?:\s+dari)?|analyst|tim analis|ceo|chief executive officer|"
    r"president director|president of|country manager|country head|head of|chief of|founder|co-founder|"
    r"rektor|wakil rektor|dekan|asisten deputi|deputi|pemilik|pelaku usaha|"
    r"mitra pengemudi|mitra merchant|mitra instruktur|mitra penerima beasiswa|mitra naik kelas|mitra|"
    r"hakim ketua|hakim anggota|majelis hakim|hakim|kapuspenkum kejagung|kapuspenkum|"
    r"ketua umum|ketua|sekretaris|juru bicara pt dki jakarta|juru bicara|jubir|kepala|"
    r"koordinator aksi|koordinator|direktur utama (?:pt )?(?:goto(?: gojek tokopedia)?|gojek)|"
    r"kabid humas|dirlantas|kapolres|kapolda|polda metro jaya|metro jaya|jaya|"
    r"kombes pol|kombes|kompol|akbp|iptu|aiptu|bripka|prof(?:esor)?|dr|dokter|ir|"
    r"dpr ri|dprd dki|dpr|dprd|kspsi|kasbi|agn|prof(?:esor)?|dr|ir)\.?\s+)+"
)
PERSON_TOKEN = r"(?:[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,}|[A-Z]\.)"
PERSON_SEQUENCE = rf"{PERSON_TOKEN}(?:\s+{PERSON_TOKEN}){{0,11}}"
CAPITAL_SEQUENCE_RE = re.compile(PERSON_SEQUENCE)
SPEECH_AFTER_NAME_RE = re.compile(
    r"\b(?:mengatakan|menyatakan|menjelaskan|menuturkan|mengungkapkan|menegaskan|"
    r"menyampaikan|menyebutkan|menjawab|berkomentar|said|says|stated|explained|told)\b",
    re.I,
)
SPEECH_BEFORE_NAME_RE = re.compile(
    r"\b(?:kata|ujar|menurut|ungkap|tutur|sebut|tambah|papar|jelas|imbuh|according\s+to)\b",
    re.I,
)
MENTION_ACTION_RE = re.compile(
    r"\b(?:mendorong|memastikan|menilai|mengapresiasi|menyoroti|meminta|mendukung|"
    r"meninjau|memimpin|menghadiri|mengumumkan|meresmikan|menyebut|backs|backed|"
    r"supports|supported|urges|urged|asks|asked|ensures|highlighted|announced)\b",
    re.I,
)
PERSON_ROLE_PATTERN = (
    r"(?:ceo|chief\s+(?:executive\s+officer|of|marketing|public|partnership)|"
    r"president(?:\s+director|\s+of)?|country\s+(?:manager|head|marketing)|"
    r"head\s+of|founder|co-founder|menteri|wakil\s+menteri|deputi|asisten\s+deputi|"
    r"rektor|wakil\s+rektor|dekan|direktur(?:\s+utama)?|komisaris(?:\s+utama)?|"
    r"gubernur|wakil\s+gubernur|bupati|wali\s*kota|ketua(?:\s+umum)?|sekretaris|"
    r"analis|analyst|tim\s+analis|"
    r"juru\s+bicara|koordinator|pemilik|pelaku\s+usaha|"
    r"mitra(?:\s+(?:pengemudi|merchant|instruktur|penerima\s+beasiswa|naik\s+kelas))?)"
)
PERSON_ROLE_RE = re.compile(rf"\b{PERSON_ROLE_PATTERN}\b", re.I)
FORMAL_ROLE_RE = re.compile(
    r"\b(?:ceo|chief\s+(?:executive\s+officer|of|marketing|public|partnership)|"
    r"president(?:\s+director|\s+of)?|country\s+(?:manager|head|marketing)|head\s+of|"
    r"founder|co-founder|menteri|wakil\s+menteri|deputi|asisten\s+deputi|rektor|"
    r"wakil\s+rektor|dekan|direktur(?:\s+utama)?|komisaris(?:\s+utama)?|gubernur|"
    r"wakil\s+gubernur|bupati|wali\s*kota|ketua(?:\s+umum)?|sekretaris|analis|analyst|"
    r"tim\s+analis|juru\s+bicara|"
    r"koordinator|pemilik)\b",
    re.I,
)
ACADEMIC_SUFFIX_PATTERN = r"(?:S\.?E\.?|S\.?H\.?|M\.?H\.?|M\.?B\.?A\.?|M\.?Si\.?|L{2}\.?M\.?|Ph\.?D\.?)"
PERSON_BEFORE_ROLE_RE = re.compile(
    rf"(?P<name>{PERSON_SEQUENCE})(?:\s*,\s*(?i:{ACADEMIC_SUFFIX_PATTERN}))*\s*,\s*"
    rf"(?P<role>(?i:{PERSON_ROLE_PATTERN}))\b"
)
SPEECH_NAME_LIST_RE = re.compile(
    rf"\b(?i:kata|ujar|menurut|ungkap|tutur|sebut|tambah|papar|jelas|imbuh|according\s+to)\s+"
    rf"(?P<names>{PERSON_SEQUENCE}(?:\s*,\s*{PERSON_SEQUENCE})*(?:\s+(?i:dan|and)\s+{PERSON_SEQUENCE})?)"
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
    "ali mukti-yanto": "Ali Muktiyanto",
}


def _clean_person_name(value: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:-")
    name = re.sub(
        r"(?i)^(?:(?:prof|dr|ir)\.?\s+)+|(?:,?\s+(?:S\.?E\.?|S\.?H\.?|M\.?H\.?|"
        r"M\.?B\.?A\.?|M\.?Si\.?|L{2}\.?M\.?|Ph\.?D\.?))+$",
        "",
        name,
    ).strip(" ,.;:-")
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
    # Two-letter prefixes such as "RA Koesoemohadiani" can be personal
    # initials. Strip only longer organization acronyms here; known two-letter
    # organizations are rejected by the word filter below.
    name = re.sub(r"^(?:(?:[A-Z]{3,})(?:\s+|$))+", "", name).strip(" ,.;:-")
    name = re.sub(r"(?i)^(?:dki\s+)?jakarta\s+(?=[A-ZÀ-ÖØ-Ý])", "", name).strip(" ,.;:-")
    name = re.sub(r"(?i),?\s+(?:S\.?H\.?|M\.?H\.?|S\.?E\.?|M\.?B\.?A\.?|Ph\.?D\.?)$", "", name).strip()
    name = PERSON_NAME_ALIASES.get(name.casefold(), name)
    non_person_words = {
        "aksi", "alasan", "anak", "asosiasi", "badan", "berita", "bursa", "buruh", "company", "dana", "dampak",
        "analis", "analyst", "bank", "bpjs", "country", "demokrat", "deutsche", "direktur", "dirlantas", "dki", "dpr", "dprd", "federasi",
        "foundation", "gerindra", "gojek", "goto", "governor", "gubernur", "gubsu", "grab", "grabacademy",
        "anggota", "eks", "golkar", "hakim", "hanura", "hukum", "indonesia", "instansi", "jalan", "jaya",
        "jasa", "karbon", "kejagung", "kebijakan", "kementerian", "keuangan", "koalisi", "kombes", "komisi", "konfederasi", "kecil",
        "kapuspenkum", "kepesertaan", "kesehatan", "ketua", "krakatau", "lembaga",
        "mahkamah", "majelis", "manajemen", "manager", "massa", "maxim", "media", "menengah", "menteri", "merchant", "metro", "mikro", "mitra", "morgan",
        "ministry", "nasdem", "negara", "ojk", "organisasi", "pejabat", "perkuat", "putusan",
        "otoritas", "partai", "pasar", "pekerja", "pemerintah", "pengawas", "perindo", "perjuangan", "perseroan", "perusahaan", "phillip", "polisi", "pt",
        "polda", "penopang", "redaksi", "rektor", "republik", "rasuna", "ruu", "saham", "sekuritas", "serikat", "sumber", "tbk", "tim", "tuntutan",
        "kesaksian",
        "union", "universitas", "usaha", "utama", "yayasan", "terbuka", "senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu",
        "buka", "lebih", "banyak", "pilihan", "kelas", "chief", "executive", "officer", "head", "president",
        "padepokan", "pencak", "silat", "tmii", "ekosistem", "berkelanjutan", "menyambut", "hut", "peluang", "tanpa", "batas",
        "pengemudi", "driver", "instructor", "partners", "partner", "scholarships", "grabcar", "traktir", "resource", "center",
        "bonus", "hari", "raya", "kerja", "sama", "pengembangan", "ketenagakerjaan", "penerima", "beasiswa",
        "pembinaan", "penyelenggaraan", "pelatihan", "vokasi", "transportasi", "peraturan", "taman", "mini", "benih", "baik",
        "tahun", "penjara", "zona", "bisnis", "melalui", "selamanya", "bersatu", "sambut", "kota", "makassar", "medium", "enterprises",
        "jawa", "tengah", "barat", "timur", "utara", "selatan", "bali", "solo", "surabaya", "jakarta", "bandung",
        "foto", "daily", "mie", "aceh", "nyata", "kompas", "rp", "citra", "edukasi", "perawatan", "luka",
        "bidang", "riset", "peningkatan", "produktivitas", "serta", "senada", "justru", "menurutnya", "pertama", "kedua",
    }
    name_words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", name.casefold())
    if (
        not name_words
        or any(part in non_person_words for part in name_words)
        or re.search(r"\d|https?://|www\.", name, re.I)
    ):
        return ""
    return name


def _best_person_name(fragment: str, *, from_end: bool) -> str:
    """Return the most plausible full name next to a role or attribution."""
    normalized = re.sub(
        r"(?i)\b(?:prof|dr|ir|S\.?E|S\.?H|M\.?H|M\.?B\.?A|M\.?Si|L{2}\.?M|Ph\.?D)\.?\b",
        " ",
        fragment,
    )
    chunks = list(CAPITAL_SEQUENCE_RE.finditer(normalized))
    if from_end:
        chunks.reverse()
    for chunk in chunks:
        tokens = re.findall(PERSON_TOKEN, chunk.group(0))
        max_size = min(5, len(tokens))
        for size in range(max_size, 1, -1):
            selected = tokens[-size:] if from_end else tokens[:size]
            name = _clean_person_name(" ".join(selected))
            if len(name.split()) >= 2:
                return name
    for chunk in chunks:
        tokens = re.findall(PERSON_TOKEN, chunk.group(0))
        if not tokens:
            continue
        name = _clean_person_name(tokens[-1] if from_end else tokens[0])
        if name:
            return name
    return ""


def _clause_before(text: str, position: int, limit: int = 220) -> str:
    start = max(0, position - limit)
    fragment = text[start:position]
    fragment = re.sub(
        r"(?i)\b(?:prof|dr|ir|S\.?E|S\.?H|M\.?H|M\.?B\.?A|M\.?Si|L{2}\.?M|Ph\.?D)\.?",
        lambda match: match.group(0).replace(".", ""),
        fragment,
    )
    boundary = max(fragment.rfind(mark) for mark in (".", "!", "?", "\n", ";"))
    return fragment[boundary + 1:]


def _clause_after(text: str, position: int, limit: int = 180) -> str:
    fragment = text[position:position + limit]
    boundaries = [index for mark in (".", "!", "?", "\n", ";") if (index := fragment.find(mark)) >= 0]
    return fragment[:min(boundaries)] if boundaries else fragment


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
    candidates: list[tuple[int, str, str, bool]] = []
    for key in ("mentions", "about"):
        values = article_node.get(key, [])
        values = values if isinstance(values, list) else [values]
        for item in values:
            if isinstance(item, dict) and str(item.get("@type") or "").casefold() == "person":
                candidates.append((-1, _plain_text(item), "indirect", True))

    # Names followed by a role are highly reliable and also capture people in
    # photo captions. They are indirect unless an attribution below proves
    # that the same person is quoted.
    for match in PERSON_BEFORE_ROLE_RE.finditer(content):
        role = match.group("role").casefold()
        trusted_single = not role.startswith("mitra")
        candidates.append(
            (match.start(), _best_person_name(match.group("name"), from_end=True), "indirect", trusted_single)
        )

    # Some captions and leads put the role first without an attribution verb,
    # e.g. "Chief Executive Officer Grab Indonesia Neneng Goenadi dalam ...".
    for match in FORMAL_ROLE_RE.finditer(content):
        fragment = content[match.start():match.start() + 180]
        fragment = re.split(
            r"(?i)\b(?:mengatakan|menyatakan|menjelaskan|menuturkan|mengungkapkan|"
            r"menegaskan|menyampaikan|menyebutkan|menjawab|berkomentar|dalam|bersama|"
            r"turut|saat|pada|yang|said|says|stated|explained|told)\b|[;.!?\n]",
            fragment,
            maxsplit=1,
        )[0]
        candidates.append((match.start(), _best_person_name(fragment, from_end=True), "indirect", False))

    for match in SPEECH_AFTER_NAME_RE.finditer(content):
        candidates.append((match.start(), _best_person_name(_clause_before(content, match.start()), from_end=True), "direct", False))
    for match in SPEECH_NAME_LIST_RE.finditer(content):
        for offset, raw_name in enumerate(
            re.split(r"\s*,\s*|\s+(?i:dan|and)\s+", match.group("names"))
        ):
            candidates.append((match.start() + offset, raw_name, "direct", True))
    for match in SPEECH_BEFORE_NAME_RE.finditer(content):
        candidates.append((match.start(), _best_person_name(_clause_after(content, match.end()), from_end=False), "direct", False))
    for match in MENTION_ACTION_RE.finditer(f"{title}. {content}"):
        candidates.append((match.start(), _best_person_name(_clause_before(f"{title}. {content}", match.start()), from_end=True), "indirect", False))

    prepared: list[tuple[int, str, str, bool]] = []
    for position, raw_name, mention_type, trusted_single in candidates:
        name = _clean_person_name(raw_name)
        if name and len(name.split()) <= 5:
            prepared.append((position, name, mention_type, trusted_single))

    full_names = [name for _, name, _, _ in prepared if len(name.split()) >= 2]

    def canonical_name(name: str, trusted_single: bool) -> str:
        if len(name.split()) >= 2:
            matches = [full for full in full_names if _same_person_name(name, full)]
            return max(matches, key=lambda item: len(item.split()), default=name)
        matches = [full for full in full_names if name.casefold() in full.casefold().split()]
        if matches:
            return max(matches, key=lambda item: len(item.split()))
        return name if trusted_single else ""

    cleaned: list[tuple[str, str]] = []
    for _, raw_name, mention_type, trusted_single in sorted(prepared, key=lambda item: item[0]):
        name = canonical_name(raw_name, trusted_single)
        if not name:
            continue
        matched_index = next(
            (index for index, (saved_name, _) in enumerate(cleaned) if _same_person_name(name, saved_name)),
            None,
        )
        if matched_index is None:
            cleaned.append((name, mention_type))
            continue
        saved_name, saved_type = cleaned[matched_index]
        preferred_name = name if len(name.split()) > len(saved_name.split()) else saved_name
        preferred_type = "direct" if "direct" in (mention_type, saved_type) else "indirect"
        cleaned[matched_index] = (preferred_name, preferred_type)
    return cleaned


def quote_mentions(content: str, article_node: dict[str, Any], title: str = "") -> str:
    return ", ".join(name for name, _ in _mention_details(content, article_node, title))


def type_mentions(content: str, article_node: dict[str, Any], title: str = "") -> str:
    return ", ".join(
        f"{name} ({mention_type})"
        for name, mention_type in _mention_details(content, article_node, title)
    )


def _failed_result(
    url: str,
    marker: str,
    reason: str = "",
    *,
    date_publish: str = "",
    month: str = "",
    identity_url: str = "",
) -> ArticleResult:
    effective_url = identity_url or url
    media_name, media_scope, media_tier = media_identity(effective_url)
    if not date_publish:
        date_publish, month = _url_publish_date(effective_url)
    return ArticleResult(
        source_url=url,
        date_publish=date_publish,
        month=month,
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
    host = (urlparse(effective_url).hostname or "").casefold().removeprefix("www.")
    is_swa = host == "swa.co.id" or host.endswith(".swa.co.id")
    soup = BeautifulSoup(html or "", "lxml")
    nodes = _json_ld_nodes(soup)
    article = _article_node(nodes, effective_url)
    language = str(
        article.get("inLanguage")
        or (soup.html.get("lang") if soup.html else "")
        or _meta(soup, 'meta[property="og:locale"]')
    ).casefold()
    if host not in CONVENTIONAL_MEDIA_CATALOG and media_scope in {"Inter", "International"} and (
        language.startswith("id") or "id_id" in language
    ):
        media_scope = "National"
    title = _plain_text(article.get("headline") or article.get("name")) or _meta(
        soup, 'meta[property="og:title"]', 'meta[name="twitter:title"]'
    )
    if not title:
        title = _meta(
            soup,
            "#sub_content h1",
            ".news-detail-content h1",
            ".entry-content h1",
            "article h1",
            ".entry-title",
            ".post-title",
            "h1",
        )
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    title = _clean_title(title, media_name)

    structured_content = _clean_content(_plain_text(article.get("articleBody")))
    dom_content = _extract_dom_content(soup)
    if is_swa:
        # SWA explicitly prohibits automated crawling in the returned page.
        # Keep the row and its public metadata, but never export that notice as
        # if it were article copy or attempt to work around the restriction.
        content = SWA_CRAWLING_NOTICE
    else:
        content = structured_content if len(structured_content.split()) >= 35 else dom_content
    body_text = soup.get_text(" ", strip=True)
    date_publish, month = _extract_publish_date(
        soup,
        article,
        effective_url,
        "",
    )
    if not is_swa:
        state = _page_state(title, body_text, content)
        if state == "unavailable":
            return _failed_result(
                source_url,
                CHECK_ARTICLE_NOT_AVAILABLE,
                "Halaman artikel tidak tersedia atau telah dihapus.",
                date_publish=date_publish,
                month=month,
                identity_url=effective_url,
            )
        if state != "available":
            return _failed_result(
                source_url,
                CHECK_FAILED_TO_PROCESS,
                "Isi artikel tidak dapat dipisahkan dari halaman.",
                date_publish=date_publish,
                month=month,
                identity_url=effective_url,
            )
        if not _url_matches_article(effective_url, title, content):
            return _failed_result(
                source_url,
                CHECK_FAILED_TO_PROCESS,
                "Konten halaman tidak sesuai dengan URL artikel. Halaman kemungkinan telah diganti penerbit.",
                date_publish=date_publish,
                month=month,
                identity_url=effective_url,
            )
        contextual_date, contextual_month = _extract_publish_date(
            soup,
            article,
            effective_url,
            f"{title} {content}",
        )
        if contextual_date:
            date_publish, month = contextual_date, contextual_month
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
        tone=classify_tone(title, content) if not is_swa else "",
        quote_mention=quote_mentions(content, article, title) if not is_swa else "",
        type_mention=type_mentions(content, article, title) if not is_swa else "",
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
            # article cache is warming or one backend serves an empty shell.
            # Use a small bounded backoff; failed rows remain in place when all
            # attempts return the same unusable response.
            for retry_delay in (0.4, 0.8):
                time.sleep(retry_delay)
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
                    continue
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
