import re
from urllib.parse import unquote, urlparse

from src.connectors.base import BaseConnector


class TikTokConnector(BaseConnector):
    platform = "TikTok"
    supports_public_comments = True

    def _platform_followers(self, html: str, soup, url: str, author: str | None) -> int | None:
        parts = [unquote(part) for part in urlparse(url).path.split("/") if part]
        username = next((part[1:] for part in parts if part.startswith("@")), "")
        if not username:
            username = (author or "").strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._]+", username):
            return None
        return self._followers_from_profile(f"https://www.tiktok.com/@{username}")
