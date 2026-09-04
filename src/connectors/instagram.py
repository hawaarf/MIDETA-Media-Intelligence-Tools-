import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector


class InstagramConnector(BaseConnector):
    platform = "Instagram"
    supports_public_comments = True
    prefer_profile_followers = True

    MONTHS = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    @staticmethod
    def _post_shortcode(url: str) -> str | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        for index, part in enumerate(parts[:-1]):
            if part.casefold() in {"p", "reel", "reels"}:
                return parts[index + 1]
        return None

    def _platform_metrics(self, html: str, url: str) -> dict[str, int]:
        metrics: dict[str, int] = {}
        shortcode = self._post_shortcode(url)
        if shortcode:
            code_matches = list(
                re.finditer(
                    r'"(?:code|shortcode|media_code)"\s*:\s*"([^"]+)"',
                    html,
                    re.I,
                )
            )
            repost_matches: list[tuple[int, int]] = []
            keys = (
                "repost_count",
                "repostCount",
                "reposts_count",
                "reshare_count",
                "reshareCount",
                "reshares_count",
                "repost_count_reduced",
                "repostCountReduced",
                "reshare_count_reduced",
                "reshareCountReduced",
            )
            for key in keys:
                pattern = rf'"{re.escape(key)}"\s*:\s*(?:\{{[^{{}}]{{0,240}}?"(?:count|total_count)"\s*:\s*)?"?([\d.,]+\s*(?:k|m|b|rb|ribu|jt|juta)?)'
                for match in re.finditer(pattern, html, re.I):
                    count = self._human_count(match.group(1))
                    if count is not None:
                        repost_matches.append((match.start(), count))
            candidates = []
            for position, count in repost_matches:
                if not code_matches:
                    break
                same_record = [
                    code
                    for code in code_matches
                    if not re.search(
                        r"}\s*,\s*{",
                        html[min(code.start(), position):max(code.start(), position)],
                    )
                ]
                if not same_record:
                    continue
                closest = min(same_record, key=lambda code: abs(code.start() - position))
                distance = abs(closest.start() - position)
                if closest.group(1).casefold() == shortcode.casefold() and distance <= 40_000:
                    candidates.append((distance, count))
            if candidates:
                metrics["reposts"] = min(candidates, key=lambda item: item[0])[1]
        return metrics

    def _platform_caption(self, html: str, url: str, current: str | None) -> str | None:
        if not current:
            return current
        month_names = "|".join(self.MONTHS)
        match = re.match(
            rf"^.*?\bon\s+(?:{month_names})\s+\d{{1,2}},\s+\d{{4}}\s*:\s*(.+)$",
            current.strip(),
            re.I | re.S,
        )
        caption = match.group(1).strip() if match else current.strip()
        wrapped = re.fullmatch(r'["“](.*)["”]\s*\.?', caption, re.S)
        if wrapped:
            return wrapped.group(1).strip() or current
        quote_pairs = (("\"", "\""), ("“", "”"), ("‘", "’"))
        for opening, closing in quote_pairs:
            if caption.startswith(opening) and caption.endswith(closing):
                caption = caption[len(opening):-len(closing)].strip()
                break
        return caption or current

    def _platform_posted_at(self, html: str, soup, url: str, current: str | None) -> str | None:
        if current:
            return current
        descriptions = (
            self._meta(soup, 'meta[property="og:description"]'),
            self._meta(soup, 'meta[name="description"]'),
        )
        month_names = "|".join(self.MONTHS)
        for description in descriptions:
            if not description:
                continue
            match = re.search(rf"\bon\s+({month_names})\s+(\d{{1,2}}),\s+(\d{{4}})\s*:", description, re.I)
            if match:
                month_name, day, year = match.groups()
                return f"{int(year):04d}-{self.MONTHS[month_name.casefold()]:02d}-{int(day):02d}"
        return current

    def _platform_followers(self, html: str, soup, url: str, author: str | None) -> int | None:
        username = (author or "").strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._]+", username):
            return None
        profile_html = self._public_profile_html(f"https://www.instagram.com/{username}/")
        if not profile_html:
            return None
        profile_soup = BeautifulSoup(profile_html, "lxml")
        visible_text = profile_soup.get_text(" ", strip=True)
        visible_match = re.search(
            r"(\d[\d.,]*\s*(?:k|m|b)?)\s+followers\b",
            visible_text,
            re.I,
        )
        if visible_match:
            visible_count = self._human_count(visible_match.group(1))
            if visible_count is not None:
                return visible_count
        exact_match = re.search(r'"follower_count"\s*:\s*"?(\d+)"?', profile_html, re.I)
        if exact_match:
            return int(exact_match.group(1))
        return self._profile_count_by_label(profile_html, profile_soup, "followers?")

    def _platform_views(self, html: str, soup, url: str, author: str | None) -> int | None:
        username = (author or "").strip().lstrip("@")
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        if not re.fullmatch(r"[A-Za-z0-9._]+", username):
            return None
        shortcode = self._post_shortcode(url)
        if not shortcode:
            return None
        reels_html = self._public_profile_html(f"https://www.instagram.com/{username}/reels/")
        if not reels_html:
            return None
        code_pattern = rf'"code"\s*:\s*"{re.escape(shortcode)}"'
        candidates: list[tuple[int, int]] = []
        play_positions = [
            (match.start(), int(match.group(1)))
            for match in re.finditer(r'"play_count"\s*:\s*"?(\d+)"?', reels_html, re.I)
        ]
        for code_match in re.finditer(code_pattern, reels_html, re.I):
            for position, count in play_positions:
                distance = abs(code_match.start() - position)
                if distance <= 1_500:
                    candidates.append((distance, count))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None
