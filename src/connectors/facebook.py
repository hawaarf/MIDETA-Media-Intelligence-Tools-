import json
import re
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector


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
        return super()._profile_count_by_label(
            profile_html,
            profile_soup,
            "friends?",
            "teman",
        )

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
        for key in ("story_fbid", "fbid", "video_id"):
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
        if positions:
            return sorted(positions)
        for pattern in (rf'"id"\s*:\s*"{target}"', rf'\\"id\\"\s*:\s*\\"{target}\\"'):
            positions.update(match.start() for match in re.finditer(pattern, html, re.I))
        return sorted(positions)

    def _target_windows(self, html: str, url: str, radius: int = 4_000) -> list[tuple[int, str]]:
        return [
            (position, html[max(0, position - radius):min(len(html), position + radius)])
            for position in self._target_anchor_positions(html, url)
        ]

    def _target_owner(self, html: str, url: str) -> tuple[str | None, str | None]:
        anchors = self._target_anchor_positions(html, url)
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
            title = self._meta(soup, 'meta[property="og:title"]')
            if not title:
                return current
            parts = [part.strip() for part in title.split(" | ") if part.strip()]
            if len(parts) >= 2 and parts[-1].casefold() != "facebook" and len(parts[-1]) <= 120:
                return parts[-1]
            title_key = re.sub(r"[^a-z0-9]", "", title.casefold())
            current_key = re.sub(r"[^a-z0-9]", "", (current or "").casefold())
            if current_key and title_key == current_key:
                return title
            return current
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
        canonical = self._meta(soup, 'meta[property="og:url"]') or url
        parts = [unquote(part) for part in urlparse(canonical).path.split("/") if part]
        reserved = {"groups", "reel", "reels", "watch", "videos", "posts", "permalink.php"}
        profile_url = None
        group_post = self._group_post_ids(canonical)
        if group_post:
            _, profile_url = self._group_post_actor(html, group_post[1])
        if not profile_url:
            _, profile_url = self._target_owner(html, canonical)
        if len(parts) >= 2 and parts[0].casefold() not in reserved and parts[1].casefold() in {"videos", "posts"}:
            profile_url = profile_url or f"https://www.facebook.com/{parts[0]}"
        if not profile_url:
            owner = re.search(r'"video_owner"\s*:\s*\{.{0,1500}?"url"\s*:\s*"((?:\\.|[^"\\])*)"', html, re.I | re.S)
            if owner:
                profile_url = self._decode_script_value(owner.group(1)).replace("\\/", "/")
        return self._followers_from_profile(profile_url) if profile_url else None

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
        target = target_ids[0]
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
        return None

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
            if comment_matches:
                metrics["comments"] = int(comment_matches[-1])
            share_matches = re.findall(r'"share_count_reduced"\s*:\s*"([^"]+)"', window, re.I)
            shares = self._localized_count(share_matches[-1]) if share_matches else None
            if shares is not None:
                metrics["shares"] = int(shares)
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
                score = len(metrics) * 100 + (10 if "story_location\\\":12" in window or 'story_location":12' in window else 0)
                found.append((score, metrics))
        return max(found, key=lambda item: item[0])[1] if found else {}

    def _metric_source(self, html: str, url: str) -> str:
        """Focus metric parsing on the requested story instead of recommendations."""
        markers = ("reaction_count", "total_comment_count", "comment_count", "share_count", "play_count", "video_view_count", "feedback")
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
