"""Platform connector registry."""
from src.connectors.base import BaseConnector
from src.connectors.facebook import FacebookConnector
from src.connectors.instagram import InstagramConnector
from src.connectors.threads import ThreadsConnector
from src.connectors.tiktok import TikTokConnector
from src.connectors.x import XConnector
from src.connectors.youtube import YouTubeConnector
from src.social_urls import platform_from_url

CONNECTORS_BY_PLATFORM = {
    "Facebook": FacebookConnector,
    "Instagram": InstagramConnector,
    "Threads": ThreadsConnector,
    "X": XConnector,
    "TikTok": TikTokConnector,
    "YouTube": YouTubeConnector,
}

# Kept as a host lookup for callers that used the original registry directly.
CONNECTORS = {
    "facebook.com": FacebookConnector,
    "www.facebook.com": FacebookConnector,
    "web.facebook.com": FacebookConnector,
    "m.facebook.com": FacebookConnector,
    "fb.me": FacebookConnector,
    "fb.watch": FacebookConnector,
    "instagram.com": InstagramConnector,
    "www.instagram.com": InstagramConnector,
    "instagr.am": InstagramConnector,
    "ig.me": InstagramConnector,
    "threads.com": ThreadsConnector,
    "www.threads.com": ThreadsConnector,
    "threads.net": ThreadsConnector,
    "www.threads.net": ThreadsConnector,
    "x.com": XConnector,
    "www.x.com": XConnector,
    "twitter.com": XConnector,
    "www.twitter.com": XConnector,
    "t.co": XConnector,
    "tiktok.com": TikTokConnector,
    "www.tiktok.com": TikTokConnector,
    "vm.tiktok.com": TikTokConnector,
    "vt.tiktok.com": TikTokConnector,
    "youtube.com": YouTubeConnector,
    "www.youtube.com": YouTubeConnector,
    "m.youtube.com": YouTubeConnector,
    "youtube-nocookie.com": YouTubeConnector,
    "youtu.be": YouTubeConnector,
}

PLATFORM_OPTIONS = ("YouTube", "TikTok", "Facebook", "Instagram", "Threads", "X")

def get_connector(url: str) -> BaseConnector:
    connector = CONNECTORS_BY_PLATFORM.get(platform_from_url(url) or "")
    if connector is None:
        raise ValueError("Platform belum didukung. Gunakan URL YouTube, TikTok, Facebook, Instagram, Threads, atau X.")
    return connector()

def detect_platform(url: str) -> str:
    return get_connector(url).platform

def get_platform_connector(url: str, selected_platform: str) -> BaseConnector:
    connector = get_connector(url)
    if connector.platform != selected_platform:
        raise ValueError(f"URL ini terdeteksi sebagai {connector.platform}. Masukkan URL {selected_platform} pada bagian ini.")
    return connector
