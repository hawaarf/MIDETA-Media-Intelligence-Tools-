from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector
from src.models import PublicComment


class XConnector(BaseConnector):
    platform = "X"
    supports_public_comments = True

    @staticmethod
    def _status_id(url: str) -> str | None:
        parts = [part for part in urlparse(url).path.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part.casefold() == "status" and parts[index + 1].isdigit():
                return parts[index + 1]
        return None

    @staticmethod
    def _number(value, default: int = 0) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _tweet_node(node: dict) -> dict | None:
        candidates = [node]
        tweet_results = node.get("tweet_results")
        if isinstance(tweet_results, dict) and isinstance(tweet_results.get("result"), dict):
            candidates.append(tweet_results["result"])
        if isinstance(node.get("tweet"), dict):
            candidates.append(node["tweet"])
        if isinstance(node.get("result"), dict):
            candidates.append(node["result"])
        for candidate in candidates:
            if isinstance(candidate.get("tweet"), dict):
                candidate = candidate["tweet"]
            legacy = candidate.get("legacy")
            identifier = candidate.get("rest_id") or candidate.get("id_str")
            if isinstance(legacy, dict) and identifier and legacy.get("full_text"):
                return candidate
        return None

    @staticmethod
    def _screen_name(tweet: dict) -> str | None:
        core = tweet.get("core")
        if not isinstance(core, dict):
            return None
        user_results = core.get("user_results")
        result = user_results.get("result") if isinstance(user_results, dict) else None
        if not isinstance(result, dict):
            return None
        legacy = result.get("legacy")
        if isinstance(legacy, dict):
            return legacy.get("screen_name") or legacy.get("name")
        user_core = result.get("core")
        if isinstance(user_core, dict):
            return user_core.get("screen_name") or user_core.get("name")
        return None

    @staticmethod
    def _comment_date(value) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        try:
            return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").isoformat()
        except ValueError:
            return text

    def _platform_comments(self, html: str, final_url: str) -> list[PublicComment]:
        target_id = self._status_id(final_url)
        if not target_id:
            return []
        soup = BeautifulSoup(html, "lxml")
        tweets: dict[str, dict] = {}
        for payload in self._embedded_json(soup):
            for node in self._walk(payload):
                tweet = self._tweet_node(node)
                if tweet:
                    identifier = str(tweet.get("rest_id") or tweet.get("id_str"))
                    tweets.setdefault(identifier, tweet)

        comments = []
        for identifier, tweet in tweets.items():
            if identifier == target_id:
                continue
            legacy = tweet.get("legacy") or {}
            conversation_id = str(legacy.get("conversation_id_str") or "")
            parent_id = str(legacy.get("in_reply_to_status_id_str") or "")
            if conversation_id != target_id or not parent_id:
                continue
            comments.append(
                PublicComment(
                    author=self._screen_name(tweet),
                    comment=str(legacy.get("full_text") or "").strip(),
                    commented_at=self._comment_date(legacy.get("created_at")),
                    likes=self._number(legacy.get("favorite_count")),
                    reply_count=self._number(legacy.get("reply_count")),
                    comment_type="parent" if parent_id == target_id else "reply",
                    source_url=final_url,
                )
            )
        return comments
