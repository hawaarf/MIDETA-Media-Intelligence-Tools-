"""Central MIDETA configuration."""
from pathlib import Path

APP_NAME = "MIDETA"
APP_DESCRIPTION = "Media Intelligence Tools"
PAGE_TITLE = "MIDETA | Media Intelligence Tools"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 5
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DATABASE_PATH = DATA_DIR / "mideta.db"
ASSETS_DIR = ROOT_DIR / "assets"
