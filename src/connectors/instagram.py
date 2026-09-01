from src.connectors.base import BaseConnector
class InstagramConnector(BaseConnector):
    platform = "Instagram"
    supports_public_comments = True
