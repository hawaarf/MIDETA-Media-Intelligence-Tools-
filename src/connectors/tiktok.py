import json
import re
from html import unescape as html_unescape
from typing import Any
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector


class TikTokConnector(BaseConnector):
    platform = "TikTok"
    supports_public_comments = True

    @staticmethod
    def _video_id(url: str) -> str | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part.casefold() in {"video", "photo"} and parts[index + 1].isdigit():
                return parts[index + 1]
        return None

    @staticmethod
    def _caption_value(value) -> str | None:
        if isinstance(value, dict):
            value = value.get("text") or value.get("desc") or value.get("description")
        if not isinstance(value, str):
            return None
        cleaned = html_unescape(value).strip()
        return cleaned or None

    @classmethod
    def _target_video_item(cls, html: str, video_id: str) -> dict[str, Any] | None:
        """Return the richest embedded object for the requested video ID."""
        soup = BeautifulSoup(html, "lxml")
        identifier_keys = ("id", "aweme_id", "awemeId", "item_id", "itemId", "video_id", "videoId")
        candidates: list[tuple[int, dict[str, Any]]] = []
        for payload in cls._embedded_json(soup):
            for node in cls._walk(payload):
                if not any(str(node.get(key) or "") == video_id for key in identifier_keys):
                    continue
                score = len(node)
                if isinstance(node.get("stats"), dict) or isinstance(node.get("statsV2"), dict):
                    score += 50
                if any(cls._caption_value(node.get(key)) for key in ("desc", "description", "caption", "text")):
                    score += 50
                if isinstance(node.get("author"), dict):
                    score += 20
                candidates.append((score, node))
        return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

    @staticmethod
    def _mapping_count(mapping: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, dict):
                value = value.get("count", value.get("total_count"))
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, (int, float)):
                return int(value)
            count = BaseConnector._human_count(str(value))
            if count is not None:
                return count
        return None

    @classmethod
    def _target_caption_from_json(cls, html: str, video_id: str) -> str | None:
        node = cls._target_video_item(html, video_id)
        if node is None:
            return None
        for key in ("desc", "description", "caption", "text"):
            caption = cls._caption_value(node.get(key))
            if caption:
                return caption
        for container_key in ("shareMeta", "seoProps"):
            container = node.get(container_key)
            if not isinstance(container, dict):
                continue
            for key in ("desc", "description", "title"):
                caption = cls._caption_value(container.get(key))
                if caption:
                    return caption
        return None

    @staticmethod
    def _clean_page_title(value: str | None) -> str | None:
        title = html_unescape(value or "").strip()
        title = re.sub(r"^\(\d+\)\s*", "", title)
        title = re.sub(r"\s*[|·-]\s*TikTok\s*$", "", title, flags=re.I).strip()
        generic_titles = {
            "tiktok",
            "tiktok - make your day",
            "make your day",
            "log in | tiktok",
        }
        if not title or title.casefold() in generic_titles:
            return None
        return title

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        video_id = self._video_id(url)
        if video_id:
            exact = self._target_caption_from_json(html, video_id)
            if exact:
                return exact
        if current:
            return current
        soup = BeautifulSoup(html, "lxml")
        title_candidates = (
            self._meta(soup, 'meta[property="og:title"]'),
            self._meta(soup, 'meta[name="twitter:title"]'),
            soup.title.get_text(" ", strip=True) if soup.title else None,
        )
        for candidate in title_candidates:
            caption = self._clean_page_title(candidate)
            if caption:
                return caption
        return None

    def _platform_followers(self, html: str, soup, url: str, author: str | None) -> int | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        username = next((part[1:] for part in parts if part.startswith("@")), "")
        if not username:
            username = (author or "").strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._]+", username):
            return None
        return self._followers_from_profile(f"https://www.tiktok.com/@{username}")
