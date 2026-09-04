"""Central MIDETA configuration."""
from pathlib import Path

APP_NAME = "MIDETA"
APP_DESCRIPTION = "Media Intelligence Tools"
PAGE_TITLE = "MIDETA | Media Intelligence Tools"
GITHUB_URL = "https://github.com/hawaarf/MIDETA-Media-Intelligence-Tools-"
GITHUB_PROFILE_URL = "https://github.com/hawaarf"
GITHUB_AVATAR_URL = "https://github.com/hawaarf.png?size=96"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_ENRICHMENT_URLS = 1000
ENRICHMENT_CHUNK_SIZE = 20
ENRICHMENT_BROWSER_CHUNK_SIZE = 5
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DATABASE_PATH = DATA_DIR / "mideta.db"
ASSETS_DIR = ROOT_DIR / "assets"
