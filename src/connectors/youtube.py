# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""YouTube post metadata from the public watch-page hydration payload."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector
from src.dates import social_datetime_iso
from src.social_urls import canonical_social_url


class YouTubeConnector(BaseConnector):
    platform = "YouTube"
    supports_public_comments = True

    @staticmethod
    def _video_id(url: str) -> str | None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").casefold()
        parts = [part for part in parsed.path.split("/") if part]
        if hostname in {"youtu.be", "www.youtu.be"} and parts:
            return parts[0]
        if parts and parts[0].casefold() in {"shorts", "live", "embed"} and len(parts) > 1:
            return parts[1]
        return (parse_qs(parsed.query).get("v") or [None])[0]

    @staticmethod
    def _text(value: Any) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        if not isinstance(value, dict):
            return None
        direct = value.get("simpleText")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        runs = value.get("runs")
        if isinstance(runs, list):
            text = "".join(
                str(run.get("text") or "")
                for run in runs
                if isinstance(run, dict)
            ).strip()
            if text:
                return text
        return None

    @classmethod
    def _number(cls, value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = cls._text(value) if isinstance(value, dict) else str(value).strip()
        return cls._human_count(text) if text else None

    @staticmethod
    @lru_cache(maxsize=8)
    def _payloads(html: str) -> list[Any]:
        return list(BaseConnector._embedded_json(BeautifulSoup(html, "lxml")))

    @classmethod
    def _target_player_nodes(cls, html: str, url: str) -> Iterable[dict]:
        target = cls._video_id(url)
        if not target:
            return
        for payload in cls._payloads(html):
            for node in cls._walk(payload):
                details = node.get("videoDetails")
                if isinstance(details, dict) and str(details.get("videoId") or "") == target:
                    yield node

    @classmethod
    def _target_details(cls, html: str, url: str) -> dict:
        for node in cls._target_player_nodes(html, url):
            details = node.get("videoDetails")
            if isinstance(details, dict):
                return details
        return {}

    @classmethod
    def _renderer_values(cls, html: str, renderer_key: str) -> Iterable[dict]:
        for payload in cls._payloads(html):
            for node in cls._walk(payload):
                renderer = node.get(renderer_key)
                if isinstance(renderer, dict):
                    yield renderer

    @classmethod
    def _microformat(cls, html: str, url: str) -> dict:
        for node in cls._target_player_nodes(html, url):
            microformat = node.get("microformat")
            if isinstance(microformat, dict):
                renderer = microformat.get("playerMicroformatRenderer")
                if isinstance(renderer, dict):
                    return renderer
        return {}

    @classmethod
    def _count_by_label(cls, renderer: Any, *labels: str) -> int | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        for node in cls._walk(renderer):
            for key in ("label", "simpleText", "title", "text"):
                value = node.get(key)
                if not isinstance(value, str):
                    continue
                match = re.search(
                    rf"(\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+(?:{label_pattern})\b",
                    value,
                    re.I,
                )
                if match:
                    return cls._human_count(match.group(1))
                reverse_match = re.search(
                    rf"(?:{label_pattern})\D{{0,30}}(\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?)\b",
                    value,
                    re.I,
                )
                if reverse_match:
                    return cls._human_count(reverse_match.group(1))
        return None

    @classmethod
    def _like_count(cls, renderer: Any) -> int | None:
        """Read old and current YouTube like-button representations."""
        labelled = cls._count_by_label(renderer, "likes", "like", "suka")
        if labelled is not None:
            return labelled
        for node in cls._walk(renderer):
            for key in ("likeCount", "like_count"):
                if key in node:
                    count = cls._number(node.get(key))
                    if count is not None:
                        return count
            for key, value in node.items():
                folded = str(key).casefold()
                if "likebutton" not in folded and "segmentedlike" not in folded:
                    continue
                if not isinstance(value, dict):
                    continue
                for button_node in cls._walk(value):
                    for text_key in (
                        "defaultText",
                        "title",
                        "accessibilityText",
                        "label",
                    ):
                        if text_key not in button_node:
                            continue
                        count = cls._number(button_node.get(text_key))
                        if count is not None:
                            return count
        return None

    @classmethod
    def _comment_count(cls, renderer: Any) -> int | None:
        labelled = cls._count_by_label(renderer, "comments", "comment", "komentar")
        if labelled is not None:
            return labelled
        for node in cls._walk(renderer):
            for key in ("commentCount", "comment_count", "countText"):
                if key in node:
                    count = cls._number(node.get(key))
                    if count is not None:
                        return count
            for key, value in node.items():
                if "commentbutton" not in str(key).casefold() or not isinstance(value, dict):
                    continue
                for button_node in cls._walk(value):
                    for text_key in ("text", "title", "accessibilityText", "label"):
                        if text_key not in button_node:
                            continue
                        count = cls._number(button_node.get(text_key))
                        if count is not None:
                            return count
        return None

    def enrich(self, url: str, *, include_platform_profile: bool = True):
        """Read Shorts through the equivalent watch route, preserving input URL."""
        processing_url = canonical_social_url(url, "YouTube") or url
        result = super().enrich(
            processing_url,
            include_platform_profile=include_platform_profile,
        )
        result.url = url
        return result

    def _metric_source(self, html: str, url: str) -> str:
        """Keep generic metric regexes inside the exact target video object."""
        details = self._target_details(html, url)
        return json.dumps(details, ensure_ascii=False) if details else ""

    def _platform_author(self, html, soup, url, current):
        details = self._target_details(html, url)
        microformat = self._microformat(html, url)
        return (
            str(details.get("author") or "").strip()
            or str(microformat.get("ownerChannelName") or "").strip()
            or current
        )

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        description = self._target_details(html, url).get("shortDescription")
        return str(description).strip() if str(description or "").strip() else current

    def _platform_posted_at(self, html, soup, url, current):
        microformat = self._microformat(html, url)
        for key in ("publishDate", "uploadDate"):
            normalized = social_datetime_iso(microformat.get(key))
            if normalized:
                return normalized
        return current

    def _platform_followers(self, html, soup, url, author):
        for renderer in self._renderer_values(html, "videoSecondaryInfoRenderer"):
            for node in self._walk(renderer):
                if "subscriberCountText" in node:
                    count = self._number(node.get("subscriberCountText"))
                    if count is not None:
                        return count
        for payload in self._payloads(html):
            for node in self._walk(payload):
                if "subscriberCountText" in node:
                    count = self._number(node.get("subscriberCountText"))
                    if count is not None:
                        return count
        return None

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        metrics: dict[str, int] = {}
        views = self._number(self._target_details(html, url).get("viewCount"))
        if views is not None:
            metrics["views"] = views

        for renderer_key in ("videoPrimaryInfoRenderer", "reelPlayerOverlayRenderer"):
            for renderer in self._renderer_values(html, renderer_key):
                likes = self._like_count(renderer)
                if likes is not None:
                    metrics["likes"] = likes
                    break
            if "likes" in metrics:
                break

        # YouTube often emits an explicit "0 Comments"/"0 Komentar" label
        # instead of an API-style numeric field. Zero is valid data here.
        for renderer_key in (
            "commentsHeaderRenderer",
            "commentsEntryPointHeaderRenderer",
            "reelPlayerOverlayRenderer",
        ):
            for renderer in self._renderer_values(html, renderer_key):
                comments = self._comment_count(renderer)
                if comments is not None:
                    metrics["comments"] = comments
                    break
            if "comments" in metrics:
                break
        return metrics
