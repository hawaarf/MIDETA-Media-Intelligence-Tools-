import re
from urllib.parse import unquote, urlparse

from src.connectors.base import BaseConnector


class InstagramConnector(BaseConnector):
    platform = "Instagram"
    supports_public_comments = True

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
        return self._followers_from_profile(f"https://www.instagram.com/{username}/")

    def _platform_views(self, html: str, soup, url: str, author: str | None) -> int | None:
        username = (author or "").strip().lstrip("@")
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        if not re.fullmatch(r"[A-Za-z0-9._]+", username):
            return None
        shortcode = None
        for index, part in enumerate(parts[:-1]):
            if part.casefold() in {"p", "reel", "reels"}:
                shortcode = parts[index + 1]
                break
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
