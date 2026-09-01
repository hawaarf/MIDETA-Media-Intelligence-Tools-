from src.connectors.base import BaseConnector

class YouTubeConnector(BaseConnector):
    platform = "YouTube"
    supports_public_comments = True
