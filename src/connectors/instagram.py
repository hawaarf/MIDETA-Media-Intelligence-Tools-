import re
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector
from src.dates import relative_social_date_iso, social_date_iso


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
        shortcode = self._post_shortcode(url)
        if shortcode:
            exact_date = self._target_posted_at_from_json(soup, shortcode)
            if exact_date:
                return exact_date
            target_nodes = []
            for anchor in soup.select("a[href]"):
                href = unquote(str(anchor.get("href") or ""))
                if shortcode.casefold() in href.casefold():
                    target_nodes.extend(anchor.select("time"))
                    target_nodes.append(anchor)
            target_nodes.extend(soup.select("article header time, article time, main time"))
            seen_nodes: set[int] = set()
            for node in target_nodes:
                if id(node) in seen_nodes:
                    continue
                seen_nodes.add(id(node))
                for value in (
                    node.get_text(" ", strip=True),
                    node.get("aria-label"),
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
        wanted = username.casefold()

        for payload in self._embedded_json(profile_soup):
            for node in self._walk(payload):
                candidates = [node]
                if isinstance(node.get("user"), dict):
                    candidates.append(node["user"])
                for candidate in candidates:
                    candidate_username = str(candidate.get("username") or "").strip().lstrip("@")
                    if candidate_username.casefold() != wanted:
                        continue
                    for key in ("follower_count", "followers_count", "edge_followed_by"):
                        value = candidate.get(key)
                        if isinstance(value, dict):
                            value = value.get("count", value.get("total_count"))
                        if isinstance(value, bool) or value is None:
                            continue
                        count = self._human_count(str(value))
                        if count is not None:
                            return count

        description = self._meta(
            profile_soup,
            'meta[property="og:description"]',
            'meta[name="description"]',
        )
        if not description or not re.search(
            rf"(?<![A-Za-z0-9._])@?{re.escape(username)}(?![A-Za-z0-9._])",
            description,
            re.I,
        ):
            return None
        meta_match = re.search(
            r"(\d[\d.,]*\s*(?:k|m|b)?)\s+followers\b",
            description,
            re.I,
        )
        meta_count = self._human_count(meta_match.group(1)) if meta_match else None
        if meta_count is None:
            return None

        label_pattern = re.compile(
            r"(\d[\d.,]*\s*(?:k|m|b)?)\s+followers\b",
            re.I,
        )
        username_pattern = re.compile(
            rf"(?<![A-Za-z0-9._])@?{re.escape(username)}(?![A-Za-z0-9._])",
            re.I,
        )
        for text_node in profile_soup.find_all(string=label_pattern):
            match = label_pattern.search(str(text_node))
            if not match:
                continue
            scope = text_node.parent
            for _ in range(6):
                if scope is None or scope.name in {"body", "html"}:
                    break
                scope_text = scope.get_text(" ", strip=True)
                target_link = any(
                    [part for part in urlparse(str(link.get("href") or "")).path.split("/") if part]
                    == [username]
                    for link in scope.select("a[href]")
                )
                if target_link or username_pattern.search(scope_text):
                    visible_count = self._human_count(match.group(1))
                    if visible_count is not None:
                        return visible_count
                    break
                scope = scope.parent
        return meta_count

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
