# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

from src.connectors.base import BaseConnector

class YouTubeConnector(BaseConnector):
    platform = "YouTube"
    supports_public_comments = True
