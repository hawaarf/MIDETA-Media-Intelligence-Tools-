import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

from src.connectors.base import BaseConnector


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

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        metrics: dict[str, int] = {}
        match = re.search(r'"view_counts?"\s*:\s*"?(\d+)"?', html, re.I)
        if match:
            metrics["views"] = int(match.group(1))
        else:
            visible = re.search(r"([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)\s+views?\b", html, re.I)
            count = self._human_count(visible.group(1)) if visible else None
            if count is not None:
                metrics["views"] = count

        shortcode = self._post_shortcode(url)
        if shortcode:
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
