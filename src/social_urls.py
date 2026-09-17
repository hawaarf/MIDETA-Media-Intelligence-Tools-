"""Social-media URL aliases and safe short-link resolution."""
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import MAX_REDIRECTS, REQUEST_TIMEOUT_SECONDS
from src.http_client import USER_AGENT
from src.validators import validate_public_url


PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "Facebook": ("facebook.com",),
    "Instagram": ("instagram.com",),
    "Threads": ("threads.com", "threads.net"),
    "X": ("x.com", "twitter.com"),
    "TikTok": ("tiktok.com",),
    "YouTube": ("youtube.com", "youtube-nocookie.com"),
}

# Domains that do not share the platform's main domain suffix.
PLATFORM_ALIASES: dict[str, str] = {
    "fb.me": "Facebook",
    "www.fb.me": "Facebook",
    "fb.watch": "Facebook",
    "www.fb.watch": "Facebook",
    "instagr.am": "Instagram",
    "www.instagr.am": "Instagram",
    "ig.me": "Instagram",
    "www.ig.me": "Instagram",
    "t.co": "X",
    "www.t.co": "X",
    "youtu.be": "YouTube",
    "www.youtu.be": "YouTube",
}

SHORT_LINK_HOSTS = {
    "fb.me",
    "fb.watch",
    "www.fb.watch",
    "l.facebook.com",
    "lm.facebook.com",
    "ig.me",
    "www.ig.me",
    "l.instagram.com",
    "t.co",
    "www.t.co",
    "vm.tiktok.com",
    "vt.tiktok.com",
    "youtu.be",
    "www.youtu.be",
}

SHORT_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "Facebook": ("/share/",),
    "Instagram": ("/share/",),
    "Threads": ("/share/",),
    "TikTok": ("/t/",),
}


class SocialURLResolutionError(ValueError):
    pass


def _hostname(url: str) -> str:
    return (urlparse(url.strip()).hostname or "").casefold().rstrip(".")


def platform_from_url(url: str) -> str | None:
    """Return a supported platform for official, mobile, and short domains."""
    hostname = _hostname(url)
    if not hostname:
        return None
    alias = PLATFORM_ALIASES.get(hostname)
    if alias:
        return alias
    for platform, domains in PLATFORM_DOMAINS.items():
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            return platform
    return None


def is_short_social_url(url: str, platform: str | None = None) -> bool:
    """Identify native short/share forms that need their destination URL."""
    hostname = _hostname(url)
    if hostname in SHORT_LINK_HOSTS:
        return True
    detected = platform or platform_from_url(url)
    path = urlparse(url).path.casefold()
    return bool(detected and any(path.startswith(prefix) for prefix in SHORT_PATH_PREFIXES.get(detected, ())))


def _response_html(response: requests.Response, limit: int = 512 * 1024) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(32 * 1024):
        if not chunk:
            continue
        remaining = limit - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        if total >= limit:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def _html_destination(html: str, current_url: str) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for selector, attribute in (
        ('meta[property="og:url"]', "content"),
        ('link[rel="canonical"]', "href"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            return urljoin(current_url, str(node.get(attribute)).strip())
    refresh = soup.select_one('meta[http-equiv="refresh" i]')
    if refresh and refresh.get("content"):
        match = re.search(r"\burl\s*=\s*['\"]?([^'\";]+)", str(refresh.get("content")), re.I)
        if match:
            return urljoin(current_url, match.group(1).strip())
    return None


def _checked_destination(url: str, expected_platform: str) -> str:
    checked = validate_public_url(url)
    platform = platform_from_url(checked)
    if platform != expected_platform:
        raise SocialURLResolutionError(
            f"URL pendek tidak mengarah ke posting {expected_platform} yang didukung."
        )
    return checked


@lru_cache(maxsize=2_048)
def resolve_social_url(url: str, expected_platform: str | None = None) -> str:
    """Resolve a native short/share URL while validating every redirect."""
    current = validate_public_url(url)
    platform = platform_from_url(current)
    if expected_platform and platform != expected_platform:
        raise SocialURLResolutionError(
            f"URL ini terdeteksi sebagai {platform or 'platform yang tidak didukung'}, bukan {expected_platform}."
        )
    expected = expected_platform or platform
    if not expected:
        raise SocialURLResolutionError("Platform URL tidak dapat dikenali.")
    if not is_short_social_url(current, expected):
        return current

    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = requests.get(
                current,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            # A logged-in browser may still be able to open the link even when
            # the public resolver is temporarily limited by the platform.
            return current

        try:
            if response.is_redirect or response.is_permanent_redirect:
                target = response.headers.get("location")
                if not target:
                    raise SocialURLResolutionError("URL pendek memberikan pengalihan tanpa tujuan.")
                current = _checked_destination(urljoin(current, target), expected)
                if not is_short_social_url(current, expected):
                    return current
                continue

            if response.status_code >= 400:
                return current

            destination = _html_destination(_response_html(response), current)
            if destination:
                destination = _checked_destination(destination, expected)
                if destination != current:
                    return destination
            if not is_short_social_url(current, expected):
                return current
            return current
        finally:
            response.close()

    return current
