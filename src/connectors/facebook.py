# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import json
import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector
from src.dates import relative_social_date_iso, social_date_iso
from src.models import DataField, FieldStatus, SocialResult


class FacebookConnector(BaseConnector):
    platform = "Facebook"
    supports_public_comments = True

    def _profile_count_by_label(
        self,
        profile_html: str,
        profile_soup: BeautifulSoup,
        *labels: str,
    ) -> int | None:
        followers = super()._profile_count_by_label(
            profile_html,
            profile_soup,
            "followers?",
            "pengikut",
        )
        if followers is not None:
            return followers
        friends = super()._profile_count_by_label(
            profile_html,
            profile_soup,
            "friends?",
            "teman",
        )
        if friends is not None:
            return friends
        # The authenticated desktop page often renders these counts as
        # ordinary visible text instead of serialising them into a script.
        visible_text = profile_soup.get_text(" ", strip=True)
        for label in ("followers?", "pengikut", "friends?", "teman"):
            match = re.search(
                rf"(\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+(?:{label})\b",
                visible_text,
                re.I,
            )
            if match:
                return self._human_count(match.group(1))
        return None

    @staticmethod
    def _decode_script_value(value: str) -> str:
        try:
            return str(json.loads(f'"{value}"')).strip()
        except json.JSONDecodeError:
            return value.strip()

    @staticmethod
    def _group_post_ids(url: str) -> tuple[str, str] | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        if len(parts) < 4 or parts[0].lower() != "groups" or not parts[1].isdigit():
            return None
        if parts[2].lower() not in {"permalink", "posts"}:
            return None
        return parts[1], parts[3]

    @staticmethod
    def _post_identifiers(url: str) -> list[str]:
        parsed = urlparse(url)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        identifiers = [part for part in reversed(parts) if part.isdigit() or part.casefold().startswith("pfbid")]
        query = parse_qs(parsed.query)
        for key in ("story_fbid", "fbid", "video_id", "v"):
            for value in query.get(key, []):
                if value.isdigit() or value.casefold().startswith("pfbid"):
                    identifiers.append(value)
        return list(dict.fromkeys(identifiers))

    def _target_anchor_positions(self, html: str, url: str) -> list[int]:
        identifiers = self._post_identifiers(url)
        if not identifiers:
            return []
        target = re.escape(identifiers[0])
        positions: set[int] = set()
        strong_patterns = (
            rf'"(?:post_id|video_id|top_level_post_id)"\s*:\s*"{target}"',
            rf'\\"(?:post_id|video_id|top_level_post_id)\\"\s*:\s*\\"{target}\\"',
        )
        for pattern in strong_patterns:
            positions.update(match.start() for match in re.finditer(pattern, html, re.I))
        for pattern in (rf'"id"\s*:\s*"{target}"', rf'\\"id\\"\s*:\s*\\"{target}\\"'):
            positions.update(match.start() for match in re.finditer(pattern, html, re.I))
        return sorted(positions)

    def _target_feedback_positions(self, html: str, url: str) -> list[int]:
        """Prefer the post-level summary over repeated IDs inside comment records."""
        identifiers = self._post_identifiers(url)
        positions: set[int] = set()
        for identifier in identifiers:
            target = re.escape(identifier)
            patterns = (
                rf'"subscription_target_id"\s*:\s*"{target}"',
                rf'\\"subscription_target_id\\"\s*:\s*\\"{target}\\"',
            )
            for pattern in patterns:
                positions.update(match.start() for match in re.finditer(pattern, html, re.I))
        positions.update(self._target_anchor_positions(html, url))
        return sorted(positions)

    def _target_windows(self, html: str, url: str, radius: int = 12_000) -> list[tuple[int, str]]:
        return [
            (position, html[max(0, position - radius):min(len(html), position + radius)])
            for position in self._target_feedback_positions(html, url)
        ]

    def _platform_posted_at(self, html: str, soup, url: str, current: str | None) -> str | None:
        """Use only a timestamp attached to the requested Facebook story."""
        identifiers = self._post_identifiers(url)
        timestamp_keys = (
            "publish_time",
            "publishTime",
            "creation_time",
            "creationTime",
            "created_time",
            "createdTime",
        )
        for identifier in identifiers:
            exact_date = self._target_posted_at_from_json(
                soup,
                identifier,
                identifier_keys=("id", "post_id", "video_id", "top_level_post_id"),
                timestamp_keys=timestamp_keys,
            )
            if exact_date:
                return exact_date

        anchors = self._target_feedback_positions(html, url)
        if anchors:
            candidates: list[tuple[int, int, str]] = []
            for key_priority, key in enumerate(timestamp_keys):
                patterns = (
                    rf'"{re.escape(key)}"\s*:\s*"?(\d{{10,19}})"?',
                    rf'\\"{re.escape(key)}\\"\s*:\s*(?:\\")?(\d{{10,19}})(?:\\")?',
                )
                for pattern in patterns:
                    for match in re.finditer(pattern, html, re.I):
                        distance = min(abs(match.start() - anchor) for anchor in anchors)
                        if distance > 12_000:
                            continue
                        normalized = social_date_iso(match.group(1))
                        if normalized:
                            candidates.append((distance, key_priority, normalized))
            if candidates:
                return min(candidates, key=lambda item: (item[0], item[1]))[2]

        target_nodes = []
        for identifier in identifiers:
            for anchor in soup.select("a[href]"):
                href = unquote(str(anchor.get("href") or ""))
                if identifier.casefold() in href.casefold():
                    target_nodes.extend(anchor.select("time, abbr"))
                    target_nodes.append(anchor)
        target_nodes.extend(
            soup.select(
                '[role="main"] [role="article"] time, '
                '[role="main"] [role="article"] abbr, '
                '[role="article"] time, [role="article"] abbr, '
                'time[datetime], abbr[data-utime]'
            )
        )
        seen_nodes: set[int] = set()
        for node in target_nodes:
            if id(node) in seen_nodes:
                continue
            seen_nodes.add(id(node))
            for value in (
                node.get_text(" ", strip=True),
                node.get("aria-label"),
                node.get("data-tooltip-content"),
                node.get("title"),
            ):
                if value in (None, ""):
                    continue
                relative_date = relative_social_date_iso(value)
                if relative_date:
                    return relative_date
            for value in (node.get("datetime"), node.get("data-utime"), node.get("title")):
                exact_date = social_date_iso(value)
                if exact_date:
                    return exact_date
        return current

    def _target_owner(self, html: str, url: str) -> tuple[str | None, str | None]:
        anchors = self._target_feedback_positions(html, url)
        if not anchors:
            return None, None
        candidates: list[tuple[int, str, str | None]] = []
        pattern = r'"(?:video_owner|owning_profile|owner)"\s*:\s*\{(.{0,2000}?)\}'
        for match in re.finditer(pattern, html, re.I | re.S):
            distance = min(abs(match.start() - anchor) for anchor in anchors)
            if distance > 6_000:
                continue
            body = match.group(1)
            name_match = re.search(r'"name"\s*:\s*"((?:\\.|[^"\\])*)"', body, re.I)
            if not name_match:
                continue
            name = self._decode_script_value(name_match.group(1))
            if not name or name.casefold() in {"facebook", "everyone"}:
                continue
            url_match = re.search(r'"url"\s*:\s*"((?:\\.|[^"\\])*)"', body, re.I)
            id_match = re.search(r'"id"\s*:\s*"(\d+)"', body, re.I)
            profile_url = self._decode_script_value(url_match.group(1)).replace("\\/", "/") if url_match else None
            if not profile_url and id_match:
                profile_url = f"https://www.facebook.com/{id_match.group(1)}"
            candidates.append((distance, name, profile_url))
        if not candidates:
            return None, None
        _, name, profile_url = min(candidates, key=lambda item: item[0])
        return name, profile_url

    @staticmethod
    def _visible_post_owner(soup: BeautifulSoup) -> tuple[str | None, str | None]:
        """Read the owner from the action menu of the post shown on screen.

        Authenticated Facebook pages include the signed-in account in their
        scripts and navigation.  The post action label is scoped to the open
        post, so it is a safer fallback for share URLs that do not expose
        OpenGraph metadata.
        """
        patterns = (
            r"^Tindakan untuk postingan oleh\s+(.+?)\s+ini$",
            r"^Actions? for (?:this )?post by\s+(.+?)$",
            r"^Actions? for\s+(.+?)(?:'s|’s) post$",
        )
        for node in soup.select("[aria-label]"):
            label = re.sub(r"\s+", " ", str(node.get("aria-label") or "")).strip()
            author = None
            for pattern in patterns:
                match = re.match(pattern, label, re.I)
                if match:
                    author = match.group(1).strip()
                    break
            if not author:
                continue

            profile_url = None
            root = node
            for _ in range(7):
                if root is None:
                    break
                for link in root.select("a[href]"):
                    link_label = re.sub(
                        r"\s+",
                        " ",
                        " ".join(
                            value
                            for value in (
                                str(link.get("aria-label") or "").strip(),
                                link.get_text(" ", strip=True),
                            )
                            if value
                        ),
                    ).strip()
                    if link_label.casefold() != author.casefold():
                        continue
                    href = str(link.get("href") or "").replace("\\/", "/").replace("&amp;", "&")
                    parsed = urlparse(href)
                    parts = [part for part in parsed.path.split("/") if part]
                    if not parts:
                        continue
                    profile_url = f"https://www.facebook.com/{parts[0]}"
                    break
                if profile_url:
                    break
                root = root.parent
            return author, profile_url
        return None, None

    def _visible_post_metrics(self, soup: BeautifulSoup) -> dict[str, int]:
        """Read engagement buttons only from the currently open post card."""
        action_node = next(
            (
                node
                for node in soup.select("[aria-label]")
                if re.search(
                    r"Tindakan untuk postingan oleh|Actions? for (?:this )?post by|Actions? for .+(?:'s|’s) post",
                    str(node.get("aria-label") or ""),
                    re.I,
                )
            ),
            None,
        )
        if action_node is None:
            return {}

        def metric_nodes(root):
            return list(root.select("[aria-label]"))

        root = action_node
        for _ in range(8):
            nodes = metric_nodes(root)
            labels = [str(node.get("aria-label") or "").casefold() for node in nodes]
            if (
                any(label in {"suka", "like"} for label in labels)
                and any(label in {"beri komentar", "comment"} for label in labels)
                and any("kirim ini ke teman" in label or "send this to friends" in label for label in labels)
            ):
                break
            if root.parent is None:
                return {}
            root = root.parent
        else:
            return {}

        metrics: dict[str, int] = {}
        for node in metric_nodes(root):
            label = re.sub(r"\s+", " ", str(node.get("aria-label") or "")).strip().casefold()
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if not text or not re.fullmatch(
                r"\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?",
                text,
                re.I,
            ):
                continue
            value = self._localized_count(text)
            if value is None:
                continue
            if label in {"suka", "like"}:
                metrics.setdefault("likes", value)
            elif label in {"beri komentar", "comment"}:
                metrics.setdefault("comments", value)
            elif "kirim ini ke teman" in label or "send this to friends" in label:
                metrics.setdefault("shares", value)
        return metrics

    def _group_post_actor(self, html: str, post_id: str) -> tuple[str | None, str | None]:
        candidates: list[tuple[int, str, str | None]] = []
        for post_match in re.finditer(rf'"post_id"\s*:\s*"{re.escape(post_id)}"', html, re.I):
            start = max(0, post_match.start() - 6_000)
            window = html[start:post_match.start()]
            for actor_match in re.finditer(r'"actors"\s*:\s*\[\s*\{(.{0,3000}?)\}\s*\]', window, re.I | re.S):
                body = actor_match.group(1)
                name_match = re.search(r'"name"\s*:\s*"((?:\\.|[^"\\])*)"', body, re.I)
                if not name_match:
                    continue
                name = self._decode_script_value(name_match.group(1))
                id_match = re.search(r'"id"\s*:\s*"(\d+)"', body, re.I)
                url_match = re.search(r'"url"\s*:\s*"((?:\\.|[^"\\])*)"', body, re.I)
                profile_url = self._decode_script_value(url_match.group(1)).replace("\\/", "/") if url_match and url_match.group(1) != "null" else None
                if not profile_url and id_match:
                    profile_url = f"https://www.facebook.com/{id_match.group(1)}"
                distance = post_match.start() - (start + actor_match.end())
                candidates.append((distance, name, profile_url))
        if not candidates:
            return None, None
        _, name, profile_url = min(candidates, key=lambda item: item[0])
        return name, profile_url

    def _group_post_author(self, html: str, post_id: str) -> str | None:
        return self._group_post_actor(html, post_id)[0]

    def _group_name(self, html: str, soup, group_id: str) -> str | None:
        group_patterns = (
            rf'"group"\s*:\s*\{{\s*"id"\s*:\s*"{re.escape(group_id)}"\s*,\s*"name"\s*:\s*"((?:\\.|[^"\\])*)"',
            rf'"group"\s*:\s*\{{\s*"name"\s*:\s*"((?:\\.|[^"\\])*)".{0,800}?"id"\s*:\s*"{re.escape(group_id)}"',
        )
        for pattern in group_patterns:
            match = re.search(pattern, html, re.I | re.S)
            if match:
                name = self._decode_script_value(match.group(1))
                if name:
                    return name
        title = self._meta(soup, 'meta[property="og:title"]')
        if title and " | " in title:
            name = title.split(" | ", 1)[0].strip()
            if name and name.lower() != "facebook":
                return name
        return None

    def _platform_author(self, html: str, soup, url: str, current: str | None) -> str | None:
        group_post = self._group_post_ids(url)
        if not group_post:
            owner_name, _ = self._target_owner(html, url)
            if owner_name:
                return owner_name
            visible_author, _ = self._visible_post_owner(soup)
            if visible_author:
                return visible_author
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            title_match = re.match(
                r"^(?:\(\d+\)\s*)?(.+?)\s+-\s+.+?\s+\|\s+Facebook$",
                title,
                re.I | re.S,
            )
            if title_match:
                candidate = re.sub(r"\s+", " ", title_match.group(1)).strip()
                if candidate and candidate.casefold() != "facebook":
                    return candidate
            title = self._meta(soup, 'meta[property="og:title"]')
            if title:
                parts = [part.strip() for part in title.split(" | ") if part.strip()]
                if len(parts) >= 2 and parts[-1].casefold() != "facebook" and len(parts[-1]) <= 120:
                    return parts[-1]
                title_key = re.sub(r"[^a-z0-9]", "", title.casefold())
                current_key = re.sub(r"[^a-z0-9]", "", (current or "").casefold())
                if current_key and title_key == current_key:
                    return title
            url_author = self._author_from_url(url)
            if not url_author:
                return current
            current_key = re.sub(r"[^a-z0-9]", "", (current or "").casefold())
            url_key = re.sub(r"[^a-z0-9]", "", url_author.casefold())
            # Keep a display name that clearly represents the same URL owner,
            # but reject unrelated script authors such as the account that is
            # currently signed in to Facebook.
            return current if current_key and current_key == url_key else url_author
        group_id, post_id = group_post
        author = self._group_post_author(html, post_id) or current
        group_name = self._group_name(html, soup, group_id)
        if not author:
            return group_name
        if not group_name or author.casefold() == group_name.casefold():
            return author
        suffix = f" - {group_name}"
        return author if author.casefold().endswith(suffix.casefold()) else f"{author}{suffix}"

    def _platform_followers(self, html: str, soup, url: str, author: str | None) -> int | None:
        profile_url = self._target_profile_url(html, soup, url)
        return self._followers_from_profile(profile_url) if profile_url else None

    def _target_profile_url(self, html: str, soup, url: str) -> str | None:
        """Return the profile that owns the requested post, never a recommendation."""
        canonical = self._meta(soup, 'meta[property="og:url"]') or url
        parts = [unquote(part) for part in urlparse(canonical).path.split("/") if part]
        reserved = {
            "groups",
            "reel",
            "reels",
            "watch",
            "videos",
            "posts",
            "photos",
            "permalink.php",
            "photo.php",
            "story.php",
            "share",
        }
        profile_url: str | None = None
        group_post = self._group_post_ids(canonical)
        if group_post:
            _, profile_url = self._group_post_actor(html, group_post[1])
        if not profile_url:
            _, profile_url = self._target_owner(html, canonical)
        if not profile_url:
            _, profile_url = self._visible_post_owner(soup)
        if len(parts) >= 2 and parts[0].casefold() not in reserved and parts[1].casefold() in {
            "videos",
            "posts",
            "photos",
            "reels",
        }:
            profile_url = profile_url or f"https://www.facebook.com/{parts[0]}"
        if not profile_url:
            owner = re.search(r'"video_owner"\s*:\s*\{.{0,1500}?"url"\s*:\s*"((?:\\.|[^"\\])*)"', html, re.I | re.S)
            if owner:
                profile_url = self._decode_script_value(owner.group(1)).replace("\\/", "/")
        if not profile_url:
            return None
        normalized = profile_url.replace("\\/", "/").replace("&amp;", "&").strip()
        return normalized or None

    @staticmethod
    def _profile_reels_url(profile_url: str) -> str:
        parsed = urlparse(profile_url)
        if parsed.path.casefold().rstrip("/") == "/profile.php":
            separator = "&" if parsed.query else "?"
            return f"{profile_url}{separator}sk=reels"
        return f"{profile_url.split('?', 1)[0].rstrip('/')}/reels/"

    def _views_from_reels_html(self, reels_html: str, target: str) -> int | None:
        """Read views only from the exact Reel card requested by the user."""
        markers = list(re.finditer(r'"profile_reel_node"\s*:', reels_html, re.I))
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else min(len(reels_html), marker.start() + 100_000)
            block = reels_html[marker.start():end]
            video_ids = re.findall(r'\\?"video_id\\?"\s*:\s*\\?"(\d+)\\?"', block, re.I)
            if not video_ids or video_ids[0] != target:
                continue
            for pattern in (
                r'"play_count"\s*:\s*"?(\d+)"?',
                r'"video_view_count"\s*:\s*"?(\d+)"?',
                r'"view_count"\s*:\s*"?(\d+)"?',
                r'"play_count_reduced"\s*:\s*"([^"]+)"',
            ):
                match = re.search(pattern, block, re.I)
                count = self._localized_count(match.group(1)) if match else None
                if count is not None:
                    return count

        # Logged-in Facebook can render the grid as ordinary anchors without
        # profile_reel_node data. Limit this fallback to an href containing the
        # exact numeric target so a nearby Reel cannot donate its view count.
        soup = BeautifulSoup(reels_html, "lxml")
        labeled_pattern = re.compile(
            r"(\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?)\s*"
            r"(?:views?|tayangan|pemutaran|plays?|kali\s+(?:dilihat|ditonton))\b",
            re.I,
        )
        for anchor in soup.select("a[href]"):
            href = unquote(str(anchor.get("href") or ""))
            if target not in href:
                continue
            values = [
                anchor.get_text(" ", strip=True),
                str(anchor.get("aria-label") or ""),
                str(anchor.get("title") or ""),
            ]
            for node in anchor.select("span, div"):
                if not node.select_one("span, div"):
                    values.append(node.get_text(" ", strip=True))
            for value in values:
                match = labeled_pattern.search(value)
                if match:
                    return self._localized_count(match.group(1))
            for value in reversed(values):
                if re.fullmatch(r"\s*\d[\d.,]*\s*(?:k|m|b|rb|ribu|jt|juta)?\s*", value, re.I):
                    return self._localized_count(value)

        return None

    def _platform_views(self, html: str, soup, url: str, author: str | None) -> int | None:
        canonical = self._meta(soup, 'meta[property="og:url"]') or url
        parts = [unquote(part) for part in urlparse(canonical).path.split("/") if part]
        target_ids = [identifier for identifier in self._post_identifiers(canonical) if identifier.isdigit()]
        if not target_ids:
            return None
        is_reel = any(part.casefold() in {"reel", "reels", "videos"} for part in parts)
        if not is_reel:
            return None
        reserved = {"groups", "reel", "reels", "watch", "videos", "posts", "permalink.php"}
        username = parts[0] if parts and parts[0].casefold() not in reserved else None
        if not username:
            owner = re.search(r'"video_owner"\s*:\s*\{.{0,1500}?"url"\s*:\s*"((?:\\.|[^"\\])*)"', html, re.I | re.S)
            if owner:
                owner_url = self._decode_script_value(owner.group(1)).replace("\\/", "/")
                owner_parts = [part for part in urlparse(owner_url).path.split("/") if part]
                username = owner_parts[0] if owner_parts else None
        if not username:
            return None
        reels_html = self._public_profile_html(f"https://www.facebook.com/{username}/reels/")
        if not reels_html:
            return None
        return self._views_from_reels_html(reels_html, target_ids[0])

    def enrich_loaded_html(
        self,
        html: str,
        url: str,
        *,
        profile_html: str | None = None,
        reels_html: str | None = None,
    ) -> SocialResult:
        """Build an exact Facebook result from an authenticated browser page."""
        soup = BeautifulSoup(html, "lxml")
        canonical = self._meta(soup, 'meta[property="og:url"]') or url
        author = self._meta(
            soup,
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[property="profile:username"]',
        )
        author = author or self._script_author(html) or self._author_from_url(canonical)
        author = self._platform_author(html, soup, canonical, author)
        caption = self._meta(soup, 'meta[property="og:description"]', 'meta[name="description"]')
        caption = self._full_caption(soup, caption)
        caption = self._platform_caption(html, canonical, caption)
        posted = self._meta(
            soup,
            'meta[property="article:published_time"]',
            'meta[name="date"]',
            'meta[itemprop="datePublished"]',
        )
        posted = self._platform_posted_at(html, soup, canonical, posted)
        if not posted:
            posted = self._script_posted_at(self._metric_source(html, canonical))

        stats = self._script_metrics(self._metric_source(html, canonical))
        stats.update(self._platform_metrics(html, canonical))
        stats = self._merge_meta_metrics(stats, self._meta_metrics(soup))
        for name, value in self._visible_post_metrics(soup).items():
            if stats.get(name) is None:
                stats[name] = value
        if profile_html:
            profile_soup = BeautifulSoup(profile_html, "lxml")
            followers = self._profile_count_by_label(profile_html, profile_soup, "followers?", "pengikut")
            if followers is not None:
                stats["followers"] = followers
        target_ids = [identifier for identifier in self._post_identifiers(canonical) if identifier.isdigit()]
        if stats.get("views") is None and reels_html and target_ids:
            views = self._views_from_reels_html(reels_html, target_ids[0])
            if views is not None:
                stats["views"] = views

        def field(name: str) -> DataField:
            value = stats.get(name)
            return DataField(
                value=value,
                status=FieldStatus.AVAILABLE if value is not None else FieldStatus.NOT_PUBLIC,
            )

        return SocialResult(
            url=canonical,
            platform=self.platform,
            username=self._field(author),
            caption=self._field(caption),
            posted_at=self._field(posted),
            followers=field("followers"),
            likes=field("likes"),
            comments=field("comments"),
            shares=field("shares"),
            views=field("views"),
            bookmarks=field("bookmarks"),
            reposts=field("reposts"),
            note=(
                "Facebook Advanced membaca post target melalui sesi login dan mencocokkan Views "
                "dengan ID Reel yang sama pada halaman profil."
            ),
        )

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        identifiers = self._post_identifiers(url)
        if not identifiers:
            return current
        current_prefix = re.sub(r"\s+", " ", current or "").rstrip(" .…")[:100].casefold()
        candidates: list[str] = []
        target = identifiers[0]
        target_patterns = (
            rf'"post_id"\s*:\s*"{re.escape(target)}"',
            rf'"top_level_post_id\\?"\s*:\s*\\?"{re.escape(target)}\\?"',
            rf'"video_id\\?"\s*:\s*\\?"{re.escape(target)}\\?"',
        )
        positions: set[int] = set()
        for pattern in target_patterns:
            positions.update(match.start() for match in re.finditer(pattern, html, re.I))
        for position in positions:
            window = html[max(0, position - 30_000):min(len(html), position + 30_000)]
            for text_match in re.finditer(r'"text"\s*:\s*"((?:\\.|[^"\\])*)"', window, re.I):
                text = self._decode_script_value(text_match.group(1))
                normalized = re.sub(r"\s+", " ", text).casefold()
                if text and (not current_prefix or normalized.startswith(current_prefix)):
                    candidates.append(text.strip())
        if not candidates:
            return current
        best = max(candidates, key=len)
        return best if len(best) > len(current or "") else current

    @staticmethod
    def _localized_count(value: str) -> int | None:
        cleaned = value.lower().replace("\\\\u00a0", " ").replace("\\u00a0", " ").replace("\xa0", " ").strip()
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|m)?", cleaned)
        if not match:
            return None
        number_text, suffix = match.groups()
        multiplier = {"rb": 1_000, "ribu": 1_000, "k": 1_000, "jt": 1_000_000, "juta": 1_000_000, "m": 1_000_000}.get(suffix or "", 1)
        if multiplier == 1 and re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", number_text):
            return int(re.sub(r"[.,]", "", number_text))
        number = float(number_text.replace(",", "."))
        return int(number * multiplier)

    def _meta_metrics(self, soup) -> dict[str, int]:
        descriptions = [
            self._meta(soup, 'meta[property="og:image:alt"]'),
            self._meta(soup, 'meta[property="og:video:alt"]'),
            self._meta(soup, 'meta[property="og:title"]'),
        ]
        patterns = {
            "views": r"([\d.,]+\s*(?:rb|ribu|k|jt|juta|m)?)\s*(?:tayangan|views?|plays?|pemutaran)",
            "likes": r"([\d.,]+\s*(?:rb|ribu|k|jt|juta|m)?)\s*(?:suka|likes?|tanggapan|reactions?)",
            "comments": r"([\d.,]+\s*(?:rb|ribu|k|jt|juta|m)?)\s*(?:komentar|comments?)",
            "shares": r"([\d.,]+\s*(?:rb|ribu|k|jt|juta|m)?)\s*(?:kali dibagikan|dibagikan|shares?)",
        }
        metrics: dict[str, int] = {}
        for description in descriptions:
            if not description or " | " not in description:
                continue
            normalized = description.split(" | ", 1)[0].lower().replace("\xa0", " ")
            for output, pattern in patterns.items():
                if output in metrics:
                    continue
                match = re.search(pattern, normalized, re.I)
                if match:
                    count = self._localized_count(match.group(1))
                    if count is not None:
                        metrics[output] = count
        return metrics

    def _merge_meta_metrics(self, stats, meta_metrics):
        """Use meta tags only when the target post payload has no exact value.

        Facebook's meta descriptions can contain cached or recommendation
        counts. They must not replace an explicit zero (or another exact
        value) from the requested photo, Reel, or video payload.
        """
        for metric, value in meta_metrics.items():
            stats.setdefault(metric, value)
        return stats

    @staticmethod
    def _clean_caption_candidate(value: str) -> str:
        cleaned = value.strip()
        if " | " in cleaned:
            first, remainder = cleaned.split(" | ", 1)
            if re.search(r"\d", first) and re.search(r"tayangan|tanggapan|komentar|dibagikan|views?|likes?|comments?|shares?", first, re.I):
                cleaned = remainder
        if " | " in cleaned:
            body, suffix = cleaned.rsplit(" | ", 1)
            if "\n" not in suffix and len(suffix.strip()) <= 100:
                cleaned = body
        lines = [line.strip() for line in cleaned.splitlines() if line.strip().lower() not in {"lihat selengkapnya", "see more"}]
        return "\n\n".join(line for line in lines if line)

    def _full_caption(self, soup, current: str | None) -> str | None:
        candidates: list[str] = []
        for node in soup.select('[data-ad-rendering-role="story_message"], [data-ad-comet-preview="message"]'):
            text = node.get_text("\n", strip=True)
            if text:
                candidates.append(self._clean_caption_candidate(text))
        for node in soup.select('link[rel="alternate"][title]'):
            title = node.get("title")
            if title:
                candidates.append(self._clean_caption_candidate(str(title)))
        image_alt = self._meta(soup, 'meta[property="og:image:alt"]')
        if image_alt:
            candidates.append(self._clean_caption_candidate(image_alt))
        current_normalized = re.sub(r"\s+", " ", current or "").rstrip(" .…")
        prefix = current_normalized[:80].lower()
        matching = [candidate for candidate in candidates if candidate and (not prefix or re.sub(r"\s+", " ", candidate).lower().startswith(prefix))]
        if not matching:
            return current
        best = max(matching, key=len)
        return best if len(best) > len(current or "") else current

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        found: list[tuple[int, dict[str, int]]] = []
        for _, window in self._target_windows(html, url):
            metrics: dict[str, int] = {}
            like_matches = re.findall(
                r'"(?:likers|unified_reactors)"\s*:\s*\{\s*"count"\s*:\s*"?(\d+)"?',
                window,
                re.I,
            )
            if like_matches:
                metrics["likes"] = int(like_matches[-1])
            else:
                exact_reactions = re.findall(
                    r'"(?:reaction_count|reactions)"\s*:\s*\{[^{}]{0,240}?"(?:count|total_count)"\s*:\s*"?(\d+)"?',
                    window,
                    re.I,
                )
                reduced_reactions = re.findall(
                    r'"(?:reaction_count_reduced|i18n_reaction_count)"\s*:\s*"([^"]+)"',
                    window,
                    re.I,
                )
                reduced_count = self._localized_count(reduced_reactions[-1]) if reduced_reactions else None
                if exact_reactions:
                    metrics["likes"] = int(exact_reactions[-1])
                elif reduced_count is not None:
                    metrics["likes"] = reduced_count
            comment_matches = re.findall(r'"total_comment_count"\s*:\s*"?(\d+)"?', window, re.I)
            if not comment_matches:
                comment_matches = re.findall(
                    r'"comment_rendering_instance"\s*:\s*\{[^{}]{0,240}?"comments"\s*:\s*\{\s*"total_count"\s*:\s*"?(\d+)"?',
                    window,
                    re.I,
                )
            if comment_matches:
                metrics["comments"] = int(comment_matches[-1])
            share_matches = re.findall(r'"share_count_reduced"\s*:\s*"([^"]+)"', window, re.I)
            shares = self._localized_count(share_matches[-1]) if share_matches else None
            if shares is None:
                exact_shares = re.findall(
                    r'"share_count"\s*:\s*\{\s*"count"\s*:\s*"?(\d+)"?',
                    window,
                    re.I,
                )
                shares = int(exact_shares[-1]) if exact_shares else None
            if shares is not None:
                metrics["shares"] = int(shares)
            exact_bookmarks = re.findall(
                r'"(?:bookmark_count|save_count|saved_count|video_save_count)"\s*:\s*"?(\d+)"?',
                window,
                re.I,
            )
            if not exact_bookmarks:
                exact_bookmarks = re.findall(
                    r'"(?:bookmark_count|save_count|saved_count|video_save_count)"\s*:\s*\{[^{}]{0,240}?"(?:count|total_count)"\s*:\s*"?(\d+)"?',
                    window,
                    re.I,
                )
            reduced_bookmarks = re.findall(
                r'"(?:bookmark_count_reduced|save_count_reduced|saved_count_reduced)"\s*:\s*"([^"]+)"',
                window,
                re.I,
            )
            reduced_bookmark_count = self._localized_count(reduced_bookmarks[-1]) if reduced_bookmarks else None
            if exact_bookmarks:
                metrics["bookmarks"] = int(exact_bookmarks[-1])
            elif reduced_bookmark_count is not None:
                metrics["bookmarks"] = reduced_bookmark_count
            for output, patterns in {
                "views": (
                    r'"play_count"\s*:\s*"?(\d+)"?',
                    r'"video_view_count"\s*:\s*"?(\d+)"?',
                    r'"view_count"\s*:\s*"?(\d+)"?',
                    r'"play_count_reduced"\s*:\s*"([^"]+)"',
                ),
            }.items():
                for pattern in patterns:
                    value_match = re.search(pattern, window, re.I)
                    count = self._localized_count(value_match.group(1)) if value_match else None
                    if count is not None:
                        metrics[output] = count
                        break
            if metrics:
                score = len(metrics) * 100
                if "subscription_target_id" in window:
                    score += 50
                if "story_location\\\":12" in window or 'story_location":12' in window:
                    score += 10
                found.append((score, metrics))
        return max(found, key=lambda item: item[0])[1] if found else {}

    def _metric_source(self, html: str, url: str) -> str:
        """Focus metric parsing on the requested story instead of recommendations."""
        markers = (
            "reaction_count",
            "total_comment_count",
            "comment_count",
            "share_count",
            "bookmark_count",
            "save_count",
            "play_count",
            "video_view_count",
            "feedback",
        )
        windows: list[tuple[int, str]] = []
        for _, window in self._target_windows(html, url):
            valid_metrics = self._script_metrics(window)
            score = len(valid_metrics) * 1_000 + sum(window.lower().count(marker) for marker in markers)
            windows.append((score, window))
        if not windows:
            has_other_story_ids = re.search(
                r'\\?"(?:post_id|video_id|top_level_post_id)\\?"\s*:\s*\\?"[^"\\]+',
                html,
                re.I,
            )
            return "" if has_other_story_ids else html
        score, best_window = max(windows, key=lambda item: item[0])
        return best_window if score else ""
