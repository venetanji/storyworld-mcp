from pathlib import Path
import os
import json
from dotenv import load_dotenv

# Load .env (if present) so env-based configuration works in dev
load_dotenv()

# Workspace root for all storyworld artifacts (characters, stories, outputs).
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", "./workspace")).resolve()

# Defaults (can be overridden via env vars)
CHARACTERS_DIR = Path(os.getenv("CHARACTERS_DIR", str(WORKSPACE_DIR / "characters")))
# Separate subfolders for descriptions and images under characters/
CHARACTERS_DESC_DIR = Path(os.getenv("CHARACTERS_DESC_DIR", str(CHARACTERS_DIR / "descriptions")))
CHARACTERS_IMAGE_DIR = Path(os.getenv("CHARACTERS_IMAGE_DIR", str(CHARACTERS_DIR / "images")))

# Backwards-compatible IMAGES_DIR (top-level images) still available
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", str(WORKSPACE_DIR / "images")))
STORIES_DIR = Path(os.getenv("STORIES_DIR", str(WORKSPACE_DIR / "stories")))
COMFY_OUTPUT_DIR = Path(os.getenv("COMFY_OUTPUT_DIR", str(WORKSPACE_DIR / "comfy-output")))

# Default remote sources (overrideable)
GITHUB_CHARACTERS_REPO = os.getenv("GITHUB_CHARACTERS_REPO", "venetanji/polyu-storyworld")
GITHUB_CHARACTERS_PATH = os.getenv("GITHUB_CHARACTERS_PATH", "characters")
HF_IMAGES_DATASET = os.getenv("HF_IMAGES_DATASET", "venetanji/polyu-storyworld-characters")

# HTTP / runtime
PORT = int(os.getenv("PORT", "3333"))
HOST = os.getenv("HOST", "0.0.0.0")
COMFY_MCP_URL = os.getenv("COMFY_MCP_URL", "").strip()
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188").strip()
COMFY_PROXY_IN_HTTP = os.getenv("COMFY_PROXY_IN_HTTP", "0") in ("1", "true", "True")
COMFY_MCP_STDIO_COMMAND = os.getenv("COMFY_MCP_STDIO_COMMAND", "").strip()
COMFY_MCP_STDIO_ARGS = os.getenv("COMFY_MCP_STDIO_ARGS", "").strip()
COMFY_MCP_STDIO_CWD = os.getenv("COMFY_MCP_STDIO_CWD", "").strip()
COMFY_MCP_STDIO_ENV = os.getenv("COMFY_MCP_STDIO_ENV", "").strip()
COMFY_MCP_AUTO_SPAWN = os.getenv("COMFY_MCP_AUTO_SPAWN", "1") in ("1", "true", "True")
COMFY_MCP_SERVER_SPEC = os.getenv("COMFY_MCP_SERVER_SPEC", "git+https://github.com/venetanji/comfyui-mcp-server.git").strip()
COMFY_MCP_SERVER_ENTRYPOINT = os.getenv("COMFY_MCP_SERVER_ENTRYPOINT", "comfyui-mcp-server").strip()
COMFY_MCP_SERVER_EXTRA_ARGS = os.getenv("COMFY_MCP_SERVER_EXTRA_ARGS", "").strip()
FASTMCP_SHOW_BANNER = os.getenv("FASTMCP_SHOW_BANNER", "0") in ("1", "true", "True")
FASTMCP_LOG_LEVEL = os.getenv("FASTMCP_LOG_LEVEL", "WARNING").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip() or os.getenv("GH_TOKEN", "").strip()
STORY_GITHUB_REPO = os.getenv("STORY_GITHUB_REPO", "").strip()
STORY_REPOS_DIR = Path(os.getenv("STORY_REPOS_DIR", str(STORIES_DIR / "repos")))

# Behavior
DISABLE_AUTO_DOWNLOAD = os.getenv("DISABLE_AUTO_DOWNLOAD", "1") in ("1", "true", "True")
STARTUP_PREFETCH = os.getenv("STARTUP_PREFETCH", "0") in ("1", "true", "True")

# Ensure directories exist
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
CHARACTERS_DESC_DIR.mkdir(parents=True, exist_ok=True)
CHARACTERS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
STORIES_DIR.mkdir(parents=True, exist_ok=True)
STORY_REPOS_DIR.mkdir(parents=True, exist_ok=True)


def comfy_stdio_env_map() -> dict[str, str]:
    raw = COMFY_MCP_STDIO_ENV.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str):
            out[k] = str(v)
    return out
