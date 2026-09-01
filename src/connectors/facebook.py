import json
import re
from urllib.parse import unquote, urlparse

from src.connectors.base import BaseConnector


class FacebookConnector(BaseConnector):
    platform = "Facebook"
    supports_public_comments = True

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

    def _group_post_author(self, html: str, post_id: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for post_match in re.finditer(rf'"post_id"\s*:\s*"{re.escape(post_id)}"', html, re.I):
            start = max(0, post_match.start() - 3_000)
            window = html[start:post_match.start()]
            for actor_match in re.finditer(
                r'"actors"\s*:\s*\[\s*\{.{0,2_200}?"name"\s*:\s*"((?:\\.|[^"\\])*)"',
                window,
                re.I | re.S,
            ):
                author = self._decode_script_value(actor_match.group(1))
                if author:
                    distance = post_match.start() - (start + actor_match.end())
                    candidates.append((distance, author))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

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

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        path_parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        identifiers = [part for part in reversed(path_parts) if part.isdigit() or part.lower().startswith("pfbid")]
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
            if not description:
                continue
            normalized = description.lower().replace("\xa0", " ")
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
        path_parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        candidates = [part for part in reversed(path_parts) if part.isdigit() or part.lower().startswith("pfbid")]
        if not candidates:
            return {}
        target = candidates[0]
        found: list[tuple[int, dict[str, int]]] = []
        for match in re.finditer(re.escape(target), html, re.I):
            window = html[max(0, match.start() - 2_500):min(len(html), match.end() + 500)]
            if "top_level_post_id" not in window and "video_id" not in window:
                continue
            metrics: dict[str, int] = {}
            comment_matches = re.findall(r'"total_comment_count"\s*:\s*"?(\d+)"?', window, re.I)
            if comment_matches:
                metrics["comments"] = int(comment_matches[-1])
            share_matches = re.findall(r'"share_count_reduced"\s*:\s*"([^"]+)"', window, re.I)
            shares = self._localized_count(share_matches[-1]) if share_matches else None
            if shares is not None:
                metrics["shares"] = int(shares)
            if metrics:
                score = len(metrics) * 100 + (10 if "story_location\\\":12" in window or 'story_location":12' in window else 0)
                found.append((score, metrics))
        return max(found, key=lambda item: item[0])[1] if found else {}

    def _metric_source(self, html: str, url: str) -> str:
        """Focus metric parsing on the requested story instead of recommendations."""
        path_parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        candidates = [part for part in reversed(path_parts) if part.isdigit() or part.lower().startswith("pfbid")]
        if not candidates:
            return html
        markers = ("reaction_count", "total_comment_count", "comment_count", "share_count", "play_count", "video_view_count", "feedback")
        windows: list[tuple[int, str]] = []
        for match in re.finditer(re.escape(candidates[0]), html, re.I):
            start = max(0, match.start() - 12_000)
            end = min(len(html), match.end() + 12_000)
            window = html[start:end]
            valid_metrics = self._script_metrics(window)
            score = len(valid_metrics) * 1_000 + sum(window.lower().count(marker) for marker in markers)
            windows.append((score, window))
        if not windows:
            return html
        score, best_window = max(windows, key=lambda item: item[0])
        return best_window if score else html
