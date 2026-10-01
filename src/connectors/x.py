# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import json
import re
from datetime import datetime
from functools import lru_cache
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
    def _username_from_url(url: str) -> str | None:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if len(parts) >= 3 and parts[1].casefold() == "status":
            return parts[0].lstrip("@") or None
        return None

    @staticmethod
    def _scalar(block: str, key: str) -> int | None:
        match = re.search(
            rf'(?:"{re.escape(key)}"|{re.escape(key)})\s*:\s*"?(\d+)"?',
            block,
            re.I,
        )
        return int(match.group(1)) if match else None

    def _target_flight_window(self, html: str, url: str) -> str:
        target_id = self._status_id(url)
        if not target_id:
            return ""
        target = re.escape(target_id)
        anchors = list(
            re.finditer(
                rf'(?:rest_id|id_str)\s*:\s*"{target}"|'
                rf'"(?:rest_id|id_str)"\s*:\s*"{target}"',
                html,
                re.I,
            )
        )
        if not anchors:
            return ""
        candidates = [
            html[anchor.start():min(len(html), anchor.start() + 30_000)]
            for anchor in anchors
        ]
        return max(
            candidates,
            key=lambda block: (
                "ApiCounts" in block,
                "ViewCountInfo" in block,
                "UserRelationshipCounts" in block,
            ),
        )

    @staticmethod
    @lru_cache(maxsize=8)
    def _structured_tweets(html: str) -> dict[str, dict]:
        soup = BeautifulSoup(html, "lxml")
        tweets: dict[str, dict] = {}
        for payload in BaseConnector._embedded_json(soup):
            for node in BaseConnector._walk(payload):
                tweet = XConnector._tweet_node(node)
                if tweet:
                    identifier = str(tweet.get("rest_id") or tweet.get("id_str") or "")
                    if identifier:
                        tweets.setdefault(identifier, tweet)
        return tweets

    def _target_tweet(self, html: str, url: str) -> dict | None:
        target_id = self._status_id(url)
        if not target_id:
            return None
        return self._structured_tweets(html).get(target_id)

    @staticmethod
    def _user_result(tweet: dict) -> dict:
        core = tweet.get("core")
        if not isinstance(core, dict):
            return {}
        user_results = core.get("user_results")
        result = user_results.get("result") if isinstance(user_results, dict) else None
        return result if isinstance(result, dict) else {}

    def _metric_source(self, html: str, url: str) -> str:
        tweet = self._target_tweet(html, url)
        if tweet:
            return json.dumps(tweet, ensure_ascii=False)
        return self._target_flight_window(html, url)

    def _platform_author(self, html, soup, url, current):
        tweet = self._target_tweet(html, url)
        if tweet:
            return self._screen_name(tweet) or self._username_from_url(url) or current
        return self._username_from_url(url) or current

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        tweet = self._target_tweet(html, url)
        legacy = tweet.get("legacy") if isinstance(tweet, dict) else None
        caption = legacy.get("full_text") if isinstance(legacy, dict) else None
        return str(caption).strip() if str(caption or "").strip() else current

    def _platform_posted_at(self, html, soup, url, current):
        tweet = self._target_tweet(html, url)
        legacy = tweet.get("legacy") if isinstance(tweet, dict) else None
        created_at = legacy.get("created_at") if isinstance(legacy, dict) else None
        return self._comment_date(created_at) or current

    def _platform_followers(self, html, soup, url, author):
        tweet = self._target_tweet(html, url)
        if tweet:
            user = self._user_result(tweet)
            legacy = user.get("legacy") if isinstance(user.get("legacy"), dict) else {}
            value = legacy.get("followers_count")
            if value is None and isinstance(user.get("relationship_counts"), dict):
                value = user["relationship_counts"].get("followers")
            if value is not None:
                return self._number(value, default=0)

        username = self._username_from_url(url)
        if not username:
            return None
        screen_name = re.search(
            rf'(?:"screen_name"|screen_name)\s*:\s*"{re.escape(username)}"',
            html,
            re.I,
        )
        if not screen_name:
            return None
        window = html[
            max(0, screen_name.start() - 2_000):
            min(len(html), screen_name.start() + 6_000)
        ]
        relationship = re.search(
            r'(?:"__typename"|__typename)\s*:\s*"UserRelationshipCounts"(.{0,800})',
            window,
            re.I | re.S,
        )
        if relationship:
            followers = self._scalar(relationship.group(1), "followers")
            if followers is not None:
                return followers
        legacy = re.search(r'(?:"followers_count"|followers_count)\s*:\s*"?(\d+)"?', window, re.I)
        return int(legacy.group(1)) if legacy else None

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        metrics: dict[str, int] = {}
        tweet = self._target_tweet(html, url)
        legacy = tweet.get("legacy") if isinstance(tweet, dict) else None
        if isinstance(legacy, dict):
            for source_key, output_key in {
                "favorite_count": "likes",
                "reply_count": "comments",
                "bookmark_count": "bookmarks",
            }.items():
                if legacy.get(source_key) is not None:
                    metrics[output_key] = self._number(legacy.get(source_key), default=0)
            retweets = legacy.get("retweet_count")
            quotes = legacy.get("quote_count")
            if retweets is not None or quotes is not None:
                metrics["reposts"] = self._number(retweets) + self._number(quotes)
            views_node = tweet.get("views") if isinstance(tweet, dict) else None
            if isinstance(views_node, dict):
                views = views_node.get("count") or views_node.get("view_count")
            else:
                views = legacy.get("view_count")
            if views is not None:
                metrics["views"] = self._number(views)

        window = self._target_flight_window(html, url)
        if not window:
            return metrics

        counts = re.search(
            r'(?:"__typename"|__typename)\s*:\s*"ApiCounts"(.{0,1_200})',
            window,
            re.I | re.S,
        )
        count_source = counts.group(1) if counts else window[:12_000]
        for source_key, output_key in {
            "favorite_count": "likes",
            "reply_count": "comments",
            "bookmark_count": "bookmarks",
        }.items():
            value = self._scalar(count_source, source_key)
            if value is not None and output_key not in metrics:
                metrics[output_key] = value

        retweets = self._scalar(count_source, "retweet_count")
        quotes = self._scalar(count_source, "quote_count")
        if (retweets is not None or quotes is not None) and "reposts" not in metrics:
            # X shows reposts and quote posts as one number on the repost button.
            metrics["reposts"] = (retweets or 0) + (quotes or 0)

        views = re.search(
            r'(?:"__typename"|__typename)\s*:\s*"ViewCountInfo"(.{0,500})',
            window,
            re.I | re.S,
        )
        if views:
            value = self._scalar(views.group(1), "count")
            if value is not None and "views" not in metrics:
                metrics["views"] = value
        return metrics

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
        tweets = self._structured_tweets(html)

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
