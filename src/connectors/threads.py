import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector
from src.models import PublicComment


class ThreadsConnector(BaseConnector):
    platform = "Threads"
    supports_public_comments = True

    @staticmethod
    def _post_shortcode(url: str) -> str | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part.casefold() == "post":
                return parts[index + 1]
        return None

    def _profile_count_by_label(self, profile_html: str, profile_soup, *labels: str) -> int | None:
        match = re.search(r'"follower_count"\s*:\s*"?(\d+)"?', profile_html, re.I)
        if match:
            return int(match.group(1))
        return super()._profile_count_by_label(profile_html, profile_soup, *labels)

    def _platform_followers(self, html: str, soup, url: str, author: str | None) -> int | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        username = parts[0].lstrip("@") if parts and parts[0].startswith("@") else (author or "").lstrip("@")
        if not username:
            return None
        return self._followers_from_profile(f"https://www.threads.com/@{username}")

    @classmethod
    def _metric_number(cls, value) -> int | None:
        if isinstance(value, dict):
            value = value.get("count") or value.get("total_count") or value.get("value")
        if isinstance(value, (int, float)):
            return int(value)
        if not isinstance(value, str):
            return None
        return cls._human_count(value)

    @classmethod
    def _target_view_counts(cls, html: str, shortcode: str) -> list[int]:
        keys = {
            "view_count",
            "view_counts",
            "views_count",
            "play_count",
            "video_view_count",
        }
        counts: list[int] = []
        soup = BeautifulSoup(html, "lxml")
        for payload in cls._embedded_json(soup):
            for node in cls._walk(payload):
                post = node.get("post") if isinstance(node.get("post"), dict) else node
                code = post.get("code") or post.get("shortcode")
                if str(code or "").casefold() != shortcode.casefold():
                    continue
                for part in cls._walk(post):
                    for key in keys:
                        count = cls._metric_number(part.get(key))
                        if count is not None:
                            counts.append(count)

        code_matches = list(
            re.finditer(r'"(?:code|shortcode)"\s*:\s*"([^"\\]+)"', html, re.I)
        )
        metric_pattern = r'"(?:view_counts?|views_count|play_count|video_view_count)"\s*:\s*"?([\d.,]+\s*(?:k|m|b)?)"?'
        for metric in re.finditer(metric_pattern, html, re.I):
            if not code_matches:
                break
            closest = min(
                code_matches,
                key=lambda code: (abs(code.start() - metric.start()), code.start() > metric.start()),
            )
            if closest.group(1).casefold() != shortcode.casefold():
                continue
            if abs(closest.start() - metric.start()) > 40_000:
                continue
            count = cls._metric_number(metric.group(1))
            if count is not None:
                counts.append(count)
        return counts

    @classmethod
    def _visible_view_count(cls, html: str) -> int | None:
        soup = BeautifulSoup(html, "lxml")
        for node in soup.select("script, style, noscript"):
            node.decompose()
        visible = re.search(
            r"([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+(?:views?|tayangan)\b",
            soup.get_text(" ", strip=True),
            re.I,
        )
        return cls._metric_number(visible.group(1)) if visible else None

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        metrics: dict[str, int] = {}
        shortcode = self._post_shortcode(url)
        if shortcode:
            view_counts = self._target_view_counts(html, shortcode)
            visible_views = self._visible_view_count(html)
            if visible_views is not None:
                view_counts.append(visible_views)
            if view_counts:
                metrics["views"] = max(view_counts)

            code_matches = list(re.finditer(r'"code"\s*:\s*"([^"]+)"', html, re.I))
            reply_counts = [
                (reply.start(), int(reply.group(1)))
                for reply in re.finditer(r'"direct_reply_count"\s*:\s*"?(\d+)"?', html, re.I)
            ]
            candidates = []
            for position, count in reply_counts:
                if not code_matches:
                    break
                closest = min(code_matches, key=lambda code: (abs(code.start() - position), code.start() > position))
                distance = abs(closest.start() - position)
                if closest.group(1).casefold() == shortcode.casefold() and distance <= 40_000:
                    candidates.append((distance, count))
            if candidates:
                metrics["comments"] = min(candidates, key=lambda item: item[0])[1]
        else:
            visible_views = self._visible_view_count(html)
            if visible_views is not None:
                metrics["views"] = visible_views
        return metrics

    def _platform_posted_at(self, html: str, soup, url: str, current: str | None) -> str | None:
        shortcode = self._post_shortcode(url)
        if shortcode:
            code_matches = list(re.finditer(r'"code"\s*:\s*"([^"]+)"', html, re.I))
            timestamps = [
                (match.start(), int(match.group(1)))
                for match in re.finditer(r'"taken_at"\s*:\s*"?(\d{10,13})"?', html, re.I)
            ]
            candidates = []
            for position, timestamp in timestamps:
                if not code_matches:
                    break
                closest = min(code_matches, key=lambda code: (abs(code.start() - position), code.start() > position))
                distance = abs(closest.start() - position)
                if closest.group(1).casefold() == shortcode.casefold() and distance <= 40_000:
                    candidates.append((distance, timestamp))
            if candidates:
                timestamp = min(candidates, key=lambda item: item[0])[1]
                if timestamp > 9_999_999_999:
                    timestamp //= 1000
                try:
                    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
                except (OverflowError, OSError, ValueError):
                    pass
        if current:
            return current
        match = re.search(r"\b(\d{2}/\d{2}/\d{2})\b", html)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%m/%d/%y").date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _number(value, default: int = 0) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _reference(node: dict, *keys: str) -> str | None:
        for key in keys:
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("pk") or value.get("id") or value.get("code")
            if value not in (None, ""):
                return str(value)
        return None

    @classmethod
    def _post_record(cls, node: dict) -> dict | None:
        post = node.get("post") if isinstance(node.get("post"), dict) else node
        code = post.get("code") or post.get("shortcode")
        app_info = post.get("text_post_app_info")
        if not isinstance(app_info, dict):
            app_info = {}
        caption = post.get("caption")
        text = caption.get("text") if isinstance(caption, dict) else caption
        text = text or post.get("text") or app_info.get("text")
        user = post.get("user")
        if not code or not text or not isinstance(user, dict):
            return None
        identifier = post.get("pk") or post.get("id") or code
        parent = cls._reference(
            app_info,
            "reply_to_post_id",
            "replied_to_post_id",
            "parent_post_id",
            "reply_to_media_id",
            "reply_to_post",
        ) or cls._reference(
            post,
            "reply_to_post_id",
            "replied_to_post_id",
            "parent_post_id",
            "reply_to_media_id",
            "reply_to_post",
        )
        root = cls._reference(
            app_info,
            "root_post_id",
            "root_media_id",
            "conversation_id",
        ) or cls._reference(post, "root_post_id", "root_media_id", "conversation_id")
        timestamp = post.get("taken_at") or post.get("created_at")
        commented_at = None
        if timestamp is not None:
            if isinstance(timestamp, (int, float)) or str(timestamp).isdigit():
                value = int(timestamp)
                if value > 9_999_999_999:
                    value //= 1000
                try:
                    commented_at = datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
                except (OverflowError, OSError, ValueError):
                    commented_at = None
            else:
                commented_at = str(timestamp)
        return {
            "id": str(identifier),
            "code": str(code),
            "parent": parent,
            "root": root,
            "author": user.get("username") or user.get("name"),
            "comment": str(text).strip(),
            "date": commented_at,
            "likes": cls._number(post.get("like_count") or post.get("likeCount")),
            "replies": cls._number(
                app_info.get("direct_reply_count")
                or post.get("direct_reply_count")
                or post.get("reply_count")
            ),
        }

    def _platform_comments(self, html: str, final_url: str) -> list[PublicComment]:
        shortcode = self._post_shortcode(final_url)
        if not shortcode:
            return []
        soup = BeautifulSoup(html, "lxml")
        records: dict[str, dict] = {}
        fallback_groups: list[list[dict]] = []
        for payload in self._embedded_json(soup):
            for node in self._walk(payload):
                record = self._post_record(node)
                if record:
                    records.setdefault(record["id"], record)
                for key in ("thread_items", "items"):
                    values = node.get(key)
                    if not isinstance(values, list):
                        continue
                    group = [item for item in (self._post_record(value) for value in values if isinstance(value, dict)) if item]
                    if group:
                        fallback_groups.append(group)

        target = next(
            (record for record in records.values() if record["code"].casefold() == shortcode.casefold()),
            None,
        )
        if not target:
            return []
        target_refs = {target["id"], target["code"]}
        connected: dict[str, str] = {}
        known_refs = set(target_refs)
        pending = [record for record in records.values() if record is not target]
        changed = True
        while changed:
            changed = False
            for record in pending:
                if record["id"] in connected:
                    continue
                parent = record.get("parent")
                root = record.get("root")
                if parent in known_refs or root in target_refs:
                    connected[record["id"]] = "parent" if parent in target_refs else "reply"
                    known_refs.update({record["id"], record["code"]})
                    changed = True

        # Some Threads responses omit parent IDs but keep the root and its
        # direct replies in one thread_items list. Use that bounded list only.
        if not connected:
            for group in fallback_groups:
                target_index = next(
                    (index for index, item in enumerate(group) if item["code"].casefold() == shortcode.casefold()),
                    None,
                )
                if target_index is None:
                    continue
                for record in group[target_index + 1 :]:
                    records.setdefault(record["id"], record)
                    connected.setdefault(record["id"], "parent")

        comments = []
        for identifier, comment_type in connected.items():
            record = records.get(identifier)
            if not record or not record["comment"]:
                continue
            comments.append(
                PublicComment(
                    author=record["author"],
                    comment=record["comment"],
                    commented_at=record["date"],
                    likes=record["likes"],
                    reply_count=record["replies"],
                    comment_type=comment_type,
                    source_url=final_url,
                )
            )
        return comments
