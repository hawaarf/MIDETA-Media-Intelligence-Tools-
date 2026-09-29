# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Social-media URL aliases and safe short-link resolution."""
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

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


def canonical_social_url(url: str, platform: str | None = None) -> str | None:
    """Return a clean, stable post URL without changing how it is enriched.

    The function is deliberately local and deterministic: it removes tracking
    parameters and normalizes known post shapes, but it never opens the URL.
    Short/share redirects are handled separately by :func:`modified_social_url`.
    """
    value = str(url or "").strip()
    detected = platform or platform_from_url(value)
    if not value or detected not in PLATFORM_DOMAINS:
        return None

    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    folded = [part.casefold() for part in parts]

    if detected == "Threads":
        for index, part in enumerate(folded[:-1]):
            if part == "post" and index > 0 and parts[index - 1].startswith("@"):
                return f"https://www.threads.com/{parts[index - 1]}/post/{parts[index + 1]}"

    if detected == "Instagram":
        for index, part in enumerate(folded[:-1]):
            if part in {"p", "reel", "reels", "tv"}:
                post_type = "reel" if part == "reels" else part
                return f"https://www.instagram.com/{post_type}/{parts[index + 1]}/"

    if detected == "TikTok":
        for index, part in enumerate(folded[:-1]):
            if part in {"video", "photo"} and index > 0 and parts[index - 1].startswith("@"):
                return f"https://www.tiktok.com/{parts[index - 1]}/{part}/{parts[index + 1]}"

    if detected == "X":
        for index, part in enumerate(folded[:-1]):
            if part == "status" and index > 0:
                return f"https://x.com/{parts[index - 1].lstrip('@')}/status/{parts[index + 1]}"

    if detected == "YouTube":
        hostname = (parsed.hostname or "").casefold()
        query = parse_qs(parsed.query)
        video_id = None
        if hostname in {"youtu.be", "www.youtu.be"} and parts:
            video_id = parts[0]
        elif folded and folded[0] in {"shorts", "live", "embed"} and len(parts) > 1:
            video_id = parts[1]
        elif folded and folded[0] == "watch":
            video_id = (query.get("v") or [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    if detected == "Facebook":
        if len(parts) >= 4 and folded[0] == "groups" and folded[2] in {"posts", "permalink"}:
            return f"https://www.facebook.com/groups/{parts[1]}/posts/{parts[3]}"
        if len(parts) >= 2 and folded[0] in {"reel", "reels"}:
            return f"https://www.facebook.com/reel/{parts[1]}"
        for index, part in enumerate(folded[:-1]):
            if part in {"posts", "videos"} and index > 0:
                return "https://www.facebook.com/" + "/".join(parts[: index + 2])
        if folded and folded[0] in {"permalink.php", "watch", "photo.php", "story.php"}:
            allowed = {
                key: values[-1]
                for key, values in query.items()
                if key in {"v", "id", "fbid", "story_fbid"} and values
            }
            clean_query = urlencode(allowed)
            return urlunparse(("https", "www.facebook.com", f"/{parts[0]}", "", clean_query, ""))

    # A supported direct URL that has no more specific post shape still gets a
    # stable HTTPS host, no fragment, and no campaign/tracking parameters.
    canonical_hosts = {
        "Facebook": "www.facebook.com",
        "Instagram": "www.instagram.com",
        "Threads": "www.threads.com",
        "X": "x.com",
        "TikTok": "www.tiktok.com",
        "YouTube": "www.youtube.com",
    }
    return urlunparse(("https", canonical_hosts[detected], parsed.path or "/", "", "", ""))


def modified_social_url(
    original_url: str,
    resolved_url: str | None = None,
    platform: str | None = None,
) -> str | None:
    """Build the export-only Modified Link while preserving the source URL.

    ``resolved_url`` should be the connector's final/canonical page when it is
    available. If it is still a short/share form, resolution is attempted as a
    best effort. Any failure returns a clean direct input (when possible) or
    ``None``; enrichment data and the original URL remain untouched.
    """
    detected = platform or platform_from_url(original_url)
    if not detected:
        return None
    candidate = str(resolved_url or original_url).strip()
    if platform_from_url(candidate) != detected:
        candidate = original_url
    if is_short_social_url(candidate, detected):
        try:
            candidate = resolve_social_url(original_url, expected_platform=detected)
        except (SocialURLResolutionError, ValueError):
            candidate = original_url
    if is_short_social_url(candidate, detected):
        return None
    return canonical_social_url(candidate, detected)


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
