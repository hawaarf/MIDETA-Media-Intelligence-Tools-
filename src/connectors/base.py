"""Conservative best-effort connector base class."""
from __future__ import annotations
import json
import re
from abc import ABC
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Iterable
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup
from src.http_client import CollectionError, fetch_public_html
from src.models import CommentCollection, DataField, FieldStatus, PublicComment, SocialResult
from src.validators import validate_public_url


@lru_cache(maxsize=128)
def _fetch_public_profile_html(url: str) -> str:
    html, _ = fetch_public_html(url)
    return html

class BaseConnector(ABC):
    platform = "Unknown"
    supports_public_comments = False

    @staticmethod
    def _field(value: Any, missing: FieldStatus = FieldStatus.NOT_PUBLIC) -> DataField:
        if value not in (None, "", []):
            return DataField(value=value, status=FieldStatus.AVAILABLE)
        return DataField(value=None, status=missing)

    @staticmethod
    def _meta(soup: BeautifulSoup, *selectors: str) -> str | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if node and node.get("content"):
                return str(node["content"]).strip()
        return None

    @staticmethod
    def _json_objects(soup: BeautifulSoup) -> Iterable[Any]:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                yield json.loads(script.get_text(strip=True))
            except (json.JSONDecodeError, TypeError):
                continue

    @staticmethod
    def _walk(value: Any) -> Iterable[dict]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from BaseConnector._walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from BaseConnector._walk(child)

    @staticmethod
    def _comment_nodes(value: Any, nested: bool = False) -> Iterable[tuple[dict, str]]:
        if isinstance(value, dict):
            is_comment = str(value.get("@type", "")).lower() == "comment"
            if is_comment:
                yield value, "reply" if nested else "parent"
            for child in value.values():
                yield from BaseConnector._comment_nodes(child, nested or is_comment)
        elif isinstance(value, list):
            for child in value:
                yield from BaseConnector._comment_nodes(child, nested)

    @staticmethod
    def _script_metrics(html: str) -> dict[str, int]:
        aliases = {
            "followers": ("followerCount", "follower_count", "followers_count", "fansCount", "fan_count", "subscriberCount", "subscriber_count"),
            "views": ("viewCount", "view_count", "views_count", "playCount", "play_count", "videoViewCount", "video_view_count"),
            "likes": ("likeCount", "like_count", "likes_count", "diggCount", "digg_count", "reaction_count", "reactions_count"),
            "comments": ("commentCount", "comment_count", "comments_count", "total_comment_count"),
            "shares": ("shareCount", "share_count", "shares_count"),
            "bookmarks": ("bookmarkCount", "bookmark_count", "collectCount", "collect_count", "saveCount", "save_count"),
            "reposts": ("repostCount", "repost_count", "retweetCount", "retweet_count"),
        }
        metrics = {}
        for output, keys in aliases.items():
            for key in keys:
                match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{[^{{}}]{{0,240}}?"(?:count|total_count)"\s*:\s*"?(\d+)"?', html, re.I)
                if not match:
                    match = re.search(rf'"{re.escape(key)}"\s*:\s*"?(\d+)"?', html, re.I)
                if match:
                    metrics[output] = int(match.group(1))
                    break
        if "comments" not in metrics:
            match = re.search(r'"comment_rendering_instance"\s*:\s*\{\s*"comments"\s*:\s*\{\s*"total_count"\s*:\s*"?(\d+)"?', html, re.I)
            if match:
                metrics["comments"] = int(match.group(1))
        return metrics

    def _metric_source(self, html: str, url: str) -> str:
        """Return the part of a platform response that belongs to the requested post."""
        return html

    def _meta_metrics(self, soup: BeautifulSoup) -> dict[str, int]:
        """Return platform-specific metric fallbacks from public meta tags."""
        return {}

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        """Return platform-specific metrics tied to the requested post."""
        return {}

    def _full_caption(self, soup: BeautifulSoup, current: str | None) -> str | None:
        """Return a longer public caption when the platform exposes one."""
        return current

    def _platform_author(
        self,
        html: str,
        soup: BeautifulSoup,
        url: str,
        current: str | None,
    ) -> str | None:
        """Return a platform-specific author label when more context is available."""
        return current

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        """Return a caption tied to the requested post when scripts expose the full text."""
        return current

    def _platform_posted_at(
        self,
        html: str,
        soup: BeautifulSoup,
        url: str,
        current: str | None,
    ) -> str | None:
        """Return a platform-specific posting date when public metadata exposes it."""
        return current

    def _platform_followers(
        self,
        html: str,
        soup: BeautifulSoup,
        url: str,
        author: str | None,
    ) -> int | None:
        """Return the public follower count for the post author when available."""
        return None

    def _platform_views(
        self,
        html: str,
        soup: BeautifulSoup,
        url: str,
        author: str | None,
    ) -> int | None:
        """Return post views from a platform-specific public fallback."""
        return None

    @staticmethod
    def _human_count(value: str) -> int | None:
        match = re.search(r"(\d[\d.,]*)\s*(k|m|b|rb|ribu|jt|juta)?", value.strip(), re.I)
        if not match:
            return None
        number_text, suffix = match.groups()
        suffix = (suffix or "").casefold()
        multipliers = {"k": 1_000, "rb": 1_000, "ribu": 1_000, "m": 1_000_000, "jt": 1_000_000, "juta": 1_000_000, "b": 1_000_000_000}
        multiplier = multipliers.get(suffix, 1)
        if multiplier == 1:
            return int(re.sub(r"[.,]", "", number_text))
        normalized = number_text.replace(",", ".")
        if normalized.count(".") > 1:
            normalized = normalized.replace(".", "")
        return int(float(normalized) * multiplier)

    def _followers_from_profile(self, profile_url: str) -> int | None:
        profile_html = self._public_profile_html(profile_url)
        if profile_html is None:
            return None
        profile_soup = BeautifulSoup(profile_html, "lxml")
        return self._profile_count_by_label(
            profile_html,
            profile_soup,
            "followers?",
            "pengikut",
        )

    @staticmethod
    def _public_profile_html(profile_url: str) -> str | None:
        try:
            return _fetch_public_profile_html(profile_url)
        except CollectionError:
            return None

    def _profile_count_by_label(
        self,
        profile_html: str,
        profile_soup: BeautifulSoup,
        *labels: str,
    ) -> int | None:
        candidates = [
            self._meta(profile_soup, 'meta[property="og:description"]'),
            self._meta(profile_soup, 'meta[name="description"]'),
        ]
        for match in re.finditer(r'"text"\s*:\s*"((?:\\.|[^"\\])*)"', profile_html, re.I):
            try:
                candidates.append(json.loads(f'"{match.group(1)}"'))
            except json.JSONDecodeError:
                candidates.append(match.group(1))
        label_pattern = "|".join(labels)
        for candidate in candidates:
            if not candidate:
                continue
            match = re.search(
                rf"(\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+(?:{label_pattern})\b",
                str(candidate),
                re.I,
            )
            if match:
                return self._human_count(match.group(1))
        return None

    @staticmethod
    def _script_text(html: str, *keys: str) -> str | None:
        for key in keys:
            match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', html, re.I)
            if not match:
                continue
            try:
                value = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                value = match.group(1)
            if str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _script_author(html: str) -> str | None:
        direct = BaseConnector._script_text(html, "author_name", "authorName", "owner_name", "ownerName", "username")
        if direct:
            return direct
        container = re.search(r'"(?:owner|author|actors)"\s*:\s*(?:\[\s*)?\{.{0,700}?"name"\s*:\s*"((?:\\.|[^"\\])*)"', html, re.I | re.S)
        if not container:
            return None
        try:
            return str(json.loads(f'"{container.group(1)}"')).strip() or None
        except json.JSONDecodeError:
            return container.group(1).strip() or None

    @staticmethod
    def _script_posted_at(html: str) -> str | None:
        iso_value = BaseConnector._script_text(html, "datePublished", "publishTime", "creationTime", "createTime", "created_at")
        if iso_value and not iso_value.isdigit():
            return iso_value
        for key in ("publish_time", "publishTime", "creation_time", "creationTime", "create_time", "createTime", "created_time", "createdTime"):
            match = re.search(rf'"{re.escape(key)}"\s*:\s*"?(\d{{10,13}})"?', html, re.I)
            if not match:
                continue
            timestamp = int(match.group(1))
            if timestamp > 9_999_999_999:
                timestamp //= 1000
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
            except (OverflowError, OSError, ValueError):
                continue
        return iso_value

    def _author_from_url(self, url: str) -> str | None:
        if self.platform != "Facebook":
            return None
        parts = [unquote(part).strip() for part in urlparse(url).path.split("/") if part.strip()]
        if not parts:
            return None
        candidate = parts[0]
        reserved = {"groups", "watch", "reel", "reels", "videos", "posts", "permalink.php", "photo.php", "story.php"}
        if candidate.lower() in reserved or candidate.isdigit():
            return None
        return candidate

    def enrich(self, url: str) -> SocialResult:
        validate_public_url(url)
        try:
            html, final_url = fetch_public_html(url)
        except CollectionError as exc:
            status = FieldStatus.LOGIN_REQUIRED if "login" in str(exc).lower() else FieldStatus.BLOCKED if "ditolak" in str(exc).lower() or "dibatasi" in str(exc).lower() else FieldStatus.FAILED
            empty = DataField(value=None, status=status)
            return SocialResult(url=url, platform=self.platform, username=empty, caption=empty, posted_at=empty, followers=empty, likes=empty, comments=empty, shares=empty, views=empty, bookmarks=empty, reposts=empty, note=str(exc))
        soup = BeautifulSoup(html, "lxml")
        author = self._meta(soup, 'meta[name="author"]', 'meta[property="article:author"]', 'meta[property="profile:username"]')
        caption = self._meta(soup, 'meta[property="og:description"]', 'meta[name="description"]')
        posted = self._meta(soup, 'meta[property="article:published_time"]', 'meta[name="date"]', 'meta[itemprop="datePublished"]')
        author = author or self._script_author(html) or self._author_from_url(final_url)
        posted = posted or self._script_posted_at(html)
        posted = self._platform_posted_at(html, soup, final_url, posted)
        canonical_node = soup.select_one('link[rel="canonical"]')
        canonical_url = self._meta(soup, 'meta[property="og:url"]') or (str(canonical_node.get("href")).strip() if canonical_node and canonical_node.get("href") else None)
        caption = self._full_caption(soup, caption)
        caption = self._platform_caption(html, canonical_url or final_url, caption)
        author = self._platform_author(html, soup, canonical_url or final_url, author)
        stats: dict[str, Any] = self._script_metrics(self._metric_source(html, canonical_url or final_url))
        stats.update(self._platform_metrics(html, canonical_url or final_url))
        for metric, value in self._meta_metrics(soup).items():
            stats[metric] = value
        for item in self._json_objects(soup):
            for node in self._walk(item):
                author_node = node.get("author")
                if not author and isinstance(author_node, dict):
                    author = author_node.get("name")
                posted = posted or node.get("datePublished")
                caption = caption or node.get("caption") or node.get("articleBody")
                interaction = node.get("interactionStatistic")
                if isinstance(interaction, dict): interaction = [interaction]
                for metric in interaction or []:
                    kind = str(metric.get("interactionType", "")).lower()
                    count = metric.get("userInteractionCount")
                    action_names = {"like": "likes", "comment": "comments", "share": "shares", "view": "views", "follow": "followers", "save": "bookmarks", "bookmark": "bookmarks", "repost": "reposts"}
                    for key, output in action_names.items():
                        if key in kind: stats[output] = count
        if stats.get("followers") is None:
            public_followers = self._platform_followers(html, soup, canonical_url or final_url, author)
            if public_followers is not None:
                stats["followers"] = public_followers
        if stats.get("views") is None:
            public_views = self._platform_views(html, soup, canonical_url or final_url, author)
            if public_views is not None:
                stats["views"] = public_views
        unsupported = FieldStatus.NOT_SUPPORTED
        zero_default_platforms = {"Facebook", "Instagram", "TikTok", "Threads"}
        followers = stats.get("followers")
        views = stats.get("views")
        if self.platform in zero_default_platforms:
            followers = 0 if followers is None else followers
            views = 0 if views is None else views
        return SocialResult(url=final_url, platform=self.platform, username=self._field(author), caption=self._field(caption), posted_at=self._field(posted), followers=self._field(followers, unsupported), likes=self._field(stats.get("likes")), comments=self._field(stats.get("comments")), shares=self._field(stats.get("shares"), unsupported), views=self._field(views, unsupported), bookmarks=self._field(stats.get("bookmarks"), unsupported), reposts=self._field(stats.get("reposts"), unsupported), note="MIDETA hanya menampilkan metadata yang tersedia pada halaman publik. Beberapa informasi mungkin tidak ditampilkan oleh platform.")

    def collect_comments(self, url: str) -> CommentCollection:
        validate_public_url(url)
        if not self.supports_public_comments:
            return CommentCollection(url=url, platform=self.platform, status=FieldStatus.NOT_SUPPORTED, reason=f"{self.platform} tidak menyediakan komentar publik di HTML standar. MIDETA tidak melewati login atau proteksi platform.")
        try:
            html, final_url = fetch_public_html(url)
        except CollectionError as exc:
            status = FieldStatus.LOGIN_REQUIRED if "login" in str(exc).lower() else FieldStatus.BLOCKED if "ditolak" in str(exc).lower() or "dibatasi" in str(exc).lower() else FieldStatus.FAILED
            return CommentCollection(url=url, platform=self.platform, status=status, reason=str(exc))
        soup = BeautifulSoup(html, "lxml")
        comments: list[PublicComment] = []
        for item in self._json_objects(soup):
            for node, comment_type in self._comment_nodes(item):
                text = node.get("text") or node.get("commentText")
                if not text: continue
                author = node.get("author")
                author_name = author.get("name") if isinstance(author, dict) else author
                nested_replies = list(self._comment_nodes(node.get("comment") or node.get("replies") or [], nested=True))
                reply_count = node.get("replyCount")
                try: reply_count = int(reply_count) if reply_count is not None else len(nested_replies)
                except (TypeError, ValueError): reply_count = len(nested_replies)
                likes = node.get("upvoteCount") or node.get("likeCount")
                try: likes = int(likes) if likes is not None else None
                except (TypeError, ValueError): likes = None
                comments.append(PublicComment(author=author_name, comment=str(text), commented_at=node.get("dateCreated") or node.get("datePublished"), likes=likes, reply_count=reply_count, comment_type=comment_type, source_url=final_url))
        if not comments:
            return CommentCollection(url=final_url, platform=self.platform, status=FieldStatus.NOT_PUBLIC, reason="Tidak ada komentar yang tersedia sebagai data terstruktur publik pada halaman ini.")
        return CommentCollection(url=final_url, platform=self.platform, comments=comments, status=FieldStatus.AVAILABLE)

    def mock_enrichment(self, url: str) -> SocialResult:
        return SocialResult(url=url, platform=self.platform, username=self._field("@mideta_demo"), caption=self._field("Contoh caption untuk demonstrasi MIDETA. Data ini tidak berasal dari tautan."), posted_at=self._field("2026-08-30T10:00:00+07:00"), followers=self._field(12800), likes=self._field(842), comments=self._field(64), shares=self._field(27), views=self._field(15320), bookmarks=self._field(105), reposts=self._field(18), is_mock=True, note="Seluruh nilai merupakan data contoh dan bukan hasil pengambilan nyata.")

    def mock_comments(self, url: str) -> CommentCollection:
        rows = [PublicComment(author="@demo_analyst", comment="Informasinya sangat membantu, terima kasih.", commented_at="2026-08-30T10:12:00+07:00", likes=12, reply_count=3, comment_type="parent", source_url=url), PublicComment(author="@demo_reader", comment="Apakah ada sumber data lengkapnya?", commented_at="2026-08-30T10:18:00+07:00", likes=4, reply_count=0, comment_type="reply", source_url=url)]
        return CommentCollection(url=url, platform=self.platform, comments=rows, status=FieldStatus.AVAILABLE, reason="Komentar ini merupakan data contoh dan bukan hasil pengambilan nyata.", is_mock=True)
