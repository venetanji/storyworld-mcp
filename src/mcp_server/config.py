from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env (if present) so env-based configuration works in dev
load_dotenv()

# Defaults (can be overridden via env vars)
CHARACTERS_DIR = Path(os.getenv("CHARACTERS_DIR", "./characters"))
# Separate subfolders for descriptions and images under characters/
CHARACTERS_DESC_DIR = Path(os.getenv("CHARACTERS_DESC_DIR", str(CHARACTERS_DIR / "descriptions")))
CHARACTERS_IMAGE_DIR = Path(os.getenv("CHARACTERS_IMAGE_DIR", str(CHARACTERS_DIR / "images")))

# Backwards-compatible IMAGES_DIR (top-level images) still available
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "./images"))

# Default remote sources (overrideable)
GITHUB_CHARACTERS_REPO = os.getenv("GITHUB_CHARACTERS_REPO", "venetanji/polyu-storyworld")
GITHUB_CHARACTERS_PATH = os.getenv("GITHUB_CHARACTERS_PATH", "characters")
HF_IMAGES_DATASET = os.getenv("HF_IMAGES_DATASET", "venetanji/polyu-storyworld-characters")

# HTTP / runtime
PORT = int(os.getenv("PORT", "3333"))
HOST = os.getenv("HOST", "0.0.0.0")

# Behavior
DISABLE_AUTO_DOWNLOAD = os.getenv("DISABLE_AUTO_DOWNLOAD", "0") in ("1", "true", "True")

# Ensure directories exist
CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
CHARACTERS_DESC_DIR.mkdir(parents=True, exist_ok=True)
CHARACTERS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
