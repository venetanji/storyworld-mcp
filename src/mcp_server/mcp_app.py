"""FastMCP integration: register MCP tools that expose the character dataset.

This module is self-contained and does not depend on any HTTP routes.
Run in dev with:

    python -m mcp_server.mcp_app

Tools:
- list_characters() -> summary of known characters
- get_character_context(code) -> character context + optional image content
- refresh_character(code) -> fetch latest YAML/images for one character
- list_character_images(code) -> image content list for the character
"""
from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy
from fastmcp.server.providers.filesystem import FileSystemProvider
from fastmcp.server.lifespan import lifespan

import importlib.metadata
import logging
from pathlib import Path
from datetime import datetime, timezone
import re
import shlex
import subprocess
import threading
from html import escape
import yaml
import argparse
import sys
from . import downloader, config
from fastmcp.utilities.types import Image
from fastmcp.server.context import Context
import asyncio
from huggingface_hub import snapshot_download
import mimetypes
import os
import shutil
from urllib.parse import urlparse
from fastmcp.resources import ResourceResult, ResourceContent
from fastmcp.server.transforms import ResourcesAsTools
import json
import requests

LOG = logging.getLogger(__name__)
MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp4", ".webm", ".mov")
_comfy_provider_added = False
_runtime_transport = "stdio"
_yaml_fetch_locks: dict[str, threading.Lock] = {}


def _lock_for(code: str) -> threading.Lock:
    if code not in _yaml_fetch_locks:
        _yaml_fetch_locks[code] = threading.Lock()
    return _yaml_fetch_locks[code]

try:
    PROJECT_VERSION = importlib.metadata.version("storyworld-mcp")
except importlib.metadata.PackageNotFoundError:
    PROJECT_VERSION = "0.0.0-dev"


def _env_is_true(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_character_text(text: str) -> dict:
    """Parse character text as YAML, with a permissive fallback parser.

    Some student-authored files contain unquoted colons in values
    (e.g. `personality: Positive: kind, curious`) which breaks strict YAML.
    """
    try:
        raw = yaml.safe_load(text) or {}
        if isinstance(raw, dict):
            return raw
        return {"text": str(raw)}
    except Exception:
        pass

    fallback: dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            fallback[key] = value
    return fallback


@lifespan
async def _startup_lifespan(_: FastMCP):
    # Keep startup fetch opt-in; default behavior is on-demand per character.
    desc_files = list(config.CHARACTERS_DESC_DIR.glob("*.yaml"))
    if not desc_files and config.STARTUP_PREFETCH and not config.DISABLE_AUTO_DOWNLOAD:
        LOG.info("No local character descriptions found; fetching remote data...")
        try:
            downloader.fetch_all()
        except Exception as ex:
            LOG.warning("Initial fetch failed: %s", ex)
    yield {}


mcp = FastMCP(
    "storyworld-mcp",
    instructions=(
        "Storyworld MCP server for character profiles and image resources. "
        "Use tools to list characters, fetch profile context, and refresh assets; "
        "use resources for JSON profiles and binary images."
    ),
    version=PROJECT_VERSION,
    website_url="https://polyu-storyworld.tail9683c.ts.net/mcp",
    lifespan=_startup_lifespan,
)
# Expose resources as tools for clients that only support tools
mcp.add_transform(ResourcesAsTools(mcp))
_tools_dir = Path(__file__).resolve().parents[2] / "tools"
_tools_dir.mkdir(exist_ok=True)
mcp.add_provider(
    FileSystemProvider(
        _tools_dir,
        reload=_env_is_true("FASTMCP_TOOLS_RELOAD", default=False),
    )
)


def _configure_comfy_proxy(transport: str) -> None:
    """Attach comfy server via mount(create_proxy(...)) based on runtime config."""
    global _comfy_provider_added
    if _comfy_provider_added:
        return
    if config.COMFY_MOUNT_MODE != "mount":
        LOG.info("Skipping comfy mount mode (COMFY_MOUNT_MODE=%s)", config.COMFY_MOUNT_MODE)
        return

    enable_for_http = bool(config.COMFY_PROXY_IN_HTTP)
    if transport == "http" and not enable_for_http:
        LOG.info("Skipping comfy proxy in HTTP mode (set COMFY_PROXY_IN_HTTP=1 to enable)")
        return

    if config.COMFY_MCP_URL:
        mcp.mount(create_proxy(config.COMFY_MCP_URL), namespace="comfy")
        _comfy_provider_added = True
        LOG.info("Mounted comfy proxy via COMFY_MCP_URL=%s", config.COMFY_MCP_URL)
        return

    if config.COMFY_MCP_STDIO_COMMAND:
        args = shlex.split(config.COMFY_MCP_STDIO_ARGS) if config.COMFY_MCP_STDIO_ARGS else []
        server_cfg = {
            "mcpServers": {
                "default": {
                    "command": config.COMFY_MCP_STDIO_COMMAND,
                    "args": args,
                }
            }
        }
        env_map = config.comfy_stdio_env_map()
        if env_map:
            server_cfg["mcpServers"]["default"]["env"] = env_map
        if config.COMFY_MCP_STDIO_CWD:
            server_cfg["mcpServers"]["default"]["cwd"] = config.COMFY_MCP_STDIO_CWD
        mcp.mount(create_proxy(server_cfg), namespace="comfy")
        _comfy_provider_added = True
        LOG.info(
            "Mounted comfy proxy via stdio command: %s %s",
            config.COMFY_MCP_STDIO_COMMAND,
            " ".join(args),
        )
        return

    if transport == "stdio" and config.COMFY_MCP_AUTO_SPAWN and config.COMFY_MCP_SERVER_SPEC:
        args = [
            "--from",
            config.COMFY_MCP_SERVER_SPEC,
            config.COMFY_MCP_SERVER_ENTRYPOINT,
            "--comfy-url",
            config.COMFYUI_URL,
            "--output-folder",
            str(config.COMFY_OUTPUT_DIR),
        ]
        if config.COMFY_MCP_SERVER_EXTRA_ARGS:
            args.extend(shlex.split(config.COMFY_MCP_SERVER_EXTRA_ARGS))
        server_cfg = {"mcpServers": {"default": {"command": "uvx", "args": args}}}
        mcp.mount(create_proxy(server_cfg), namespace="comfy")
        _comfy_provider_added = True
        LOG.info("Mounted comfy proxy via uvx auto-spawn: uvx %s", " ".join(args))


def _comfy_transport():
    if config.COMFY_MCP_URL:
        return config.COMFY_MCP_URL
    if config.COMFY_MCP_STDIO_COMMAND:
        args = shlex.split(config.COMFY_MCP_STDIO_ARGS) if config.COMFY_MCP_STDIO_ARGS else []
        env = dict(os.environ)
        env.update(config.comfy_stdio_env_map())
        cwd = config.COMFY_MCP_STDIO_CWD or None
        return StdioTransport(command=config.COMFY_MCP_STDIO_COMMAND, args=args, env=env, cwd=cwd)
    if config.COMFY_MCP_AUTO_SPAWN and config.COMFY_MCP_SERVER_SPEC:
        args = [
            "--from",
            config.COMFY_MCP_SERVER_SPEC,
            config.COMFY_MCP_SERVER_ENTRYPOINT,
            "--comfy-url",
            config.COMFYUI_URL,
            "--output-folder",
            str(config.COMFY_OUTPUT_DIR),
        ]
        if config.COMFY_MCP_SERVER_EXTRA_ARGS:
            args.extend(shlex.split(config.COMFY_MCP_SERVER_EXTRA_ARGS))
        return StdioTransport(command="uvx", args=args, env=dict(os.environ))
    return None


async def _call_comfy_tool(name: str, payload: dict) -> dict:
    transport = _comfy_transport()
    if transport is None:
        return {"ok": False, "error": "No comfy transport configured"}
    try:
        async with Client(transport) as c:
            result = await asyncio.wait_for(
                c.call_tool(name, payload),
                timeout=config.COMFY_TOOL_TIMEOUT_SECONDS,
            )
            data = getattr(result, "data", None)
            if data is not None:
                return {"ok": True, "tool": name, "result": data}
            text = []
            for item in getattr(result, "content", []) or []:
                t = getattr(item, "text", None)
                if t:
                    text.append(t)
            return {"ok": True, "tool": name, "result": text}
    except Exception as ex:
        return {"ok": False, "tool": name, "error": str(ex)}


def _download_yaml_for_code(code: str) -> Path | None:
    repo = config.GITHUB_CHARACTERS_REPO
    path = config.GITHUB_CHARACTERS_PATH.strip("/")
    try:
        owner, name = repo.split("/")
    except ValueError:
        LOG.warning("Invalid GITHUB_CHARACTERS_REPO value: %s", repo)
        return None

    filename = f"{code}.yaml"
    api_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}/{filename}"
    try:
        resp = requests.get(api_url, timeout=20, headers=_github_headers())
    except Exception as ex:
        LOG.warning("YAML fetch failed for %s: %s", code, ex)
        return None
    if resp.status_code != 200:
        return None

    try:
        meta = resp.json()
    except Exception:
        return None
    download_url = meta.get("download_url")
    if not download_url:
        return None

    try:
        raw = requests.get(download_url, timeout=20, headers=_github_headers())
        raw.raise_for_status()
    except Exception as ex:
        LOG.warning("YAML download failed for %s: %s", code, ex)
        return None

    dest = config.CHARACTERS_DESC_DIR / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw.content)
    return dest


def _download_images_for_code(code: str) -> int:
    """Download only this character's files from HF dataset into local images dir."""
    hf_dataset = config.HF_IMAGES_DATASET
    cache_dir = config.WORKSPACE_DIR / ".cache" / "hf-datasets"
    cache_dir.mkdir(parents=True, exist_ok=True)
    allow_patterns = [f"{code}/*", f"{code}/**"]
    try:
        snapshot_dir = snapshot_download(
            repo_type="dataset",
            repo_id=hf_dataset,
            cache_dir=str(cache_dir),
            allow_patterns=allow_patterns,
        )
    except Exception as ex:
        LOG.warning("Image snapshot download failed for %s: %s", code, ex)
        return 0

    src = Path(snapshot_dir) / code
    if not src.exists() or not src.is_dir():
        return 0

    copied = 0
    for p in src.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in MEDIA_EXTS:
            continue
        rel = p.relative_to(Path(snapshot_dir))
        dst = config.CHARACTERS_IMAGE_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        copied += 1
    return copied


def _load_yaml_for(code: str) -> dict:
    p = config.CHARACTERS_DESC_DIR / f"{code}.yaml"
    if not p.exists():
        matches = list(config.CHARACTERS_DESC_DIR.glob(f"{code}*.yaml"))
        if matches:
            p = matches[0]
    if not p.exists():
        lock = _lock_for(code)
        with lock:
            # Recheck inside lock to avoid duplicate downloads under concurrent requests.
            if not p.exists():
                fetched = _download_yaml_for_code(code)
                if fetched is not None:
                    p = fetched
    if not p.exists():
        raise FileNotFoundError(p)
    return _parse_character_text(p.read_text(encoding="utf-8"))


def _copy_to_public_dir(selected_path: Path, code: str) -> Path:
    """Copy selected_path into PUBLIC_IMAGES_DIR/<code>/ and return dest path.

    PUBLIC_IMAGES_DIR can be set via env var `PUBLIC_IMAGES_DIR`. Defaults to
    `<CHARACTERS_DIR>/public_images`.
    """
    try:
        public_root = Path(os.getenv("PUBLIC_IMAGES_DIR", str(config.CHARACTERS_DIR / "public_images")))
        target_dir = public_root / code
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / selected_path.name
        if not dest.exists() or selected_path.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(selected_path, dest)
        return dest
    except Exception:
        return selected_path


def _safe_story_id(story_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", story_id.strip()).strip("-").lower()
    return cleaned or "story"


def _list_media_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    items = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
            items.append(p)
    return sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)


def _story_dir(story_id: str) -> Path:
    d = config.STORIES_DIR / _safe_story_id(story_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _story_manifest(story_id: str) -> dict:
    sid = _safe_story_id(story_id)
    sdir = _story_dir(sid)
    manifest_path = sdir / "story.json"
    assets_root = sdir / "assets"
    assets = []
    for p in _list_media_files(assets_root):
        try:
            rel = p.relative_to(sdir).as_posix()
        except Exception:
            rel = p.name
        assets.append(
            {
                "path": rel,
                "filename": p.name,
                "bytes": p.stat().st_size,
                "mime_type": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
            }
        )
    if manifest_path.exists():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw["assets"] = assets
                return raw
        except Exception:
            pass
    return {"story_id": sid, "title": sid, "characters": [], "updated_at": None, "assets": assets}


def _render_story_html(manifest: dict, notes: str = "") -> str:
    title = escape(str(manifest.get("title") or manifest.get("story_id") or "Story"))
    chars = manifest.get("characters") or []
    assets = manifest.get("assets") or []
    chips = " ".join(f"<span class='chip'>{escape(str(c))}</span>" for c in chars) or "<span class='chip'>No characters</span>"
    blocks = []
    for asset in assets:
        rel = escape(str(asset.get("path", "")))
        mime = str(asset.get("mime_type") or "")
        fname = escape(str(asset.get("filename", rel)))
        if mime.startswith("image/"):
            blocks.append(f"<figure><img src='{rel}' alt='{fname}' loading='lazy'/><figcaption>{fname}</figcaption></figure>")
        elif mime.startswith("video/"):
            blocks.append(f"<figure><video src='{rel}' controls preload='metadata'></video><figcaption>{fname}</figcaption></figure>")
        else:
            blocks.append(f"<p><a href='{rel}'>{fname}</a></p>")
    gallery = "\n".join(blocks) or "<p>No media assets yet.</p>"
    notes_html = f"<section><h2>Notes</h2><p>{escape(notes)}</p></section>" if notes else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{ --bg:#f2efe9; --fg:#151515; --accent:#005f73; --card:#ffffff; }}
    body {{ margin:0; font-family: ui-serif, Georgia, 'Times New Roman', serif; background: radial-gradient(circle at 20% 10%, #fff, var(--bg)); color:var(--fg); }}
    main {{ max-width: 980px; margin: 0 auto; padding: 2rem 1rem 3rem; }}
    h1 {{ font-size: clamp(2rem, 5vw, 3.2rem); margin: 0 0 .4rem; letter-spacing: .01em; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:.5rem; margin-bottom: 1.25rem; }}
    .chip {{ background: var(--card); border:1px solid #ddd; border-radius:999px; padding:.25rem .65rem; font-size:.85rem; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; }}
    figure {{ margin:0; background:var(--card); border:1px solid #ddd; border-radius:14px; overflow:hidden; }}
    img,video {{ display:block; width:100%; height:auto; background:#000; }}
    figcaption {{ padding:.6rem .75rem; font-size:.85rem; color:#444; }}
    a {{ color: var(--accent); }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <div class="meta">{chips}</div>
    {notes_html}
    <section class="grid">
      {gallery}
    </section>
  </main>
</body>
</html>
"""


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return headers


def _story_repo_dir(story_id: str) -> Path:
    repo_dir = config.STORY_REPOS_DIR / _safe_story_id(story_id)
    repo_dir.mkdir(parents=True, exist_ok=True)
    return repo_dir


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or "").strip()


def _ensure_story_repo(story_id: str) -> dict:
    sid = _safe_story_id(story_id)
    repo_dir = _story_repo_dir(sid)
    git_dir = repo_dir / ".git"
    initialized = False
    if not git_dir.exists():
        rc, out = _run_git(["init", "-b", "main"], repo_dir)
        if rc != 0:
            return {"ok": False, "error": out, "story_id": sid, "repo_dir": str(repo_dir)}
        initialized = True
        _run_git(["config", "user.name", "Storyworld Agent"], repo_dir)
        _run_git(["config", "user.email", "storyworld-agent@local"], repo_dir)
    return {"ok": True, "initialized": initialized, "story_id": sid, "repo_dir": str(repo_dir)}


def _sync_story_bundle_into_repo(story_id: str) -> dict:
    sid = _safe_story_id(story_id)
    ensure = _ensure_story_repo(sid)
    if not ensure.get("ok"):
        return ensure
    src = _story_dir(sid)
    repo_dir = _story_repo_dir(sid)
    dst = repo_dir / "stories" / sid
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return {"ok": True, "story_id": sid, "repo_dir": str(repo_dir), "bundle_dir": str(dst)}


@mcp.tool
def list_characters() -> dict:
    """Return a summary with character codes found locally."""
    entries = []
    for f in config.CHARACTERS_DESC_DIR.glob("*.yaml"):
        try:
            data = _parse_character_text(f.read_text(encoding="utf-8"))
            name = data.get("name") or f.stem
            age = data.get("age")
            try:
                age = int(age) if age is not None else None
            except Exception:
                age = None

            personality_raw = data.get("personality") or data.get("persona") or ""
            traits = []
            if isinstance(personality_raw, str) and personality_raw:
                sections = {}
                current = None
                for line in personality_raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.endswith(":" ) and ":" not in line[:-1]:
                        current = line[:-1]
                        sections[current] = ""
                        continue
                    if ":" in line and (line.startswith("Positive:") or line.startswith("Negative:")):
                        k, v = line.split(":", 1)
                        sections[k.strip()] = v.strip()
                        current = k.strip()
                        continue
                    if current:
                        sections[current] = sections.get(current, "") + " " + line
                for sec in ("Positive", "Negative"):
                    raw = sections.get(sec, "")
                    if raw:
                        parts = [p.strip() for p in raw.split(",") if p.strip()]
                        traits.extend(parts)
                if not traits:
                    traits = [p.strip() for p in personality_raw.replace("\n", " ").split(",") if p.strip()]
            traits = traits[:8]
            entries.append({"code": f.stem, "name": name, "age": age, "traits": traits})
        except Exception:
            continue
    return {"count": len(entries), "characters": sorted(entries, key=lambda e: (e.get("name") or "").lower())}


@mcp.tool(task=True)
async def get_character_context(code: str, ctx: Context) -> list[dict]:
    """Return the MCP-style context for a single character.

    This returns a dict: {id,type,content}. `content` contains top-level YAML
    keys (schemaless). For images we only include a single `profile_image` key
    (either from YAML `profile_image` or the first file in characters/images/<code>/).
    """
    c = _load_yaml_for(code)
    content = {}
    profile_ref = None

    # copy non-image keys, capture profile_image ref if present
    for k, v in c.items():
        if k == "images":
            continue
        if k == "profile_image":
            profile_ref = v
            content[k] = v
            continue
        if isinstance(v, (str, int, float, list, dict)):
            content[k] = v
        else:
            content[k] = str(v)

    # find local images for the character
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    images_list = []
    if images_folder.exists() and images_folder.is_dir():
        for p in sorted(images_folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                continue
            images_list.append(p)

    selected_path = None
    if profile_ref and isinstance(profile_ref, str):
        cand = Path(profile_ref)
        if cand.exists():
            selected_path = cand
        else:
            name = os.path.basename(urlparse(profile_ref).path)
            if name:
                local_matches = [p for p in images_list if p.name == name]
                if local_matches:
                    selected_path = local_matches[0]
                else:
                    global_matches = list(config.CHARACTERS_IMAGE_DIR.rglob(name))
                    if global_matches:
                        selected_path = global_matches[0]

    if not selected_path and images_list:
        selected_path = images_list[0]

    # If we don't have any images locally, download only this character's images on demand.
    if not images_list:
        try:
            copied = await asyncio.to_thread(_download_images_for_code, code)
            if copied:
                try:
                    await ctx.report_progress(copied, copied, f"Downloaded {copied} assets for {code}")
                except Exception:
                    pass
                # rebuild images_list after download
                images_list = []
                if images_folder.exists() and images_folder.is_dir():
                    for p in sorted(images_folder.iterdir()):
                        if not p.is_file():
                            continue
                        if p.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
                            continue
                        images_list.append(p)
                if not selected_path and images_list:
                    selected_path = images_list[0]
        except Exception as ex:
            LOG.warning('On-demand image download failed: %s', ex)
    return [content] + ([Image(path=_copy_to_public_dir(selected_path, code)).to_image_content()] if selected_path else [])


@mcp.tool
def get_character_context_compact(code: str) -> dict:
    """Return character context with file/resource references only (no embedded binary image data)."""
    c = _load_yaml_for(code)
    content = {}
    for k, v in c.items():
        if isinstance(v, (str, int, float, list, dict)):
            content[k] = v
        else:
            content[k] = str(v)

    images_folder = config.CHARACTERS_IMAGE_DIR / code
    images = []
    if images_folder.exists() and images_folder.is_dir():
        for p in sorted(images_folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                continue
            public_path = _copy_to_public_dir(p, code)
            images.append(
                {
                    "name": p.name,
                    "path": str(public_path),
                    "resource_uri": f"character://{code}/images",
                    "mime_type": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                }
            )

    return {
        "code": code,
        "profile": content,
        "profile_resource_uri": f"character://{code}/profile",
        "profile_image_resource_uri": f"character://{code}/profile_image",
        "images": images,
    }


@mcp.tool
def get_character_media_manifest(code: str) -> dict:
    """Return a lightweight manifest for local/public media files for a character."""
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    manifest = []
    if images_folder.exists() and images_folder.is_dir():
        for p in sorted(images_folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".mp4", ".webm", ".mov"):
                continue
            public_path = _copy_to_public_dir(p, code)
            manifest.append(
                {
                    "filename": p.name,
                    "path": str(public_path),
                    "bytes": p.stat().st_size,
                    "mime_type": mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                    "resource_uri": f"character://{code}/images",
                }
            )
    return {"code": code, "count": len(manifest), "assets": manifest}


@mcp.tool
def get_runtime_capabilities() -> dict:
    """Return runtime paths and optional integration flags."""
    return {
        "transport": _runtime_transport,
        "workspace_dir": str(config.WORKSPACE_DIR),
        "comfy_proxy_enabled": bool(config.COMFY_MCP_URL or config.COMFY_MCP_STDIO_COMMAND),
        "comfy_mcp_url": config.COMFY_MCP_URL or None,
        "comfyui_url": config.COMFYUI_URL or None,
        "comfy_mcp_stdio_command": config.COMFY_MCP_STDIO_COMMAND or None,
        "comfy_mcp_auto_spawn": bool(config.COMFY_MCP_AUTO_SPAWN),
        "comfy_mcp_server_spec": config.COMFY_MCP_SERVER_SPEC or None,
        "comfy_mcp_server_entrypoint": config.COMFY_MCP_SERVER_ENTRYPOINT or None,
        "comfy_mount_mode": config.COMFY_MOUNT_MODE,
        "comfy_tool_timeout_seconds": config.COMFY_TOOL_TIMEOUT_SECONDS,
        "comfy_proxy_in_http": bool(config.COMFY_PROXY_IN_HTTP),
        "comfy_output_dir": str(config.COMFY_OUTPUT_DIR),
        "stories_dir": str(config.STORIES_DIR),
        "story_repos_dir": str(config.STORY_REPOS_DIR),
        "story_github_repo": config.STORY_GITHUB_REPO or None,
        "github_token_configured": bool(config.GITHUB_TOKEN),
        "characters_desc_dir": str(config.CHARACTERS_DESC_DIR),
        "characters_image_dir": str(config.CHARACTERS_IMAGE_DIR),
    }


@mcp.tool
def ingest_comfy_outputs(code: str, story_id: str = "", limit: int = 20, mode: str = "copy") -> dict:
    """Ingest recent media files from COMFY_OUTPUT_DIR into character/story folders.

    - `code`: character code destination
    - `story_id`: optional story id; when set, assets are also copied into stories/<story_id>/assets/<code>/
    - `limit`: max recent files to ingest
    - `mode`: `copy` (default) or `move`
    """
    mode = mode.strip().lower()
    if mode not in {"copy", "move"}:
        return {"error": "mode must be 'copy' or 'move'"}
    if limit <= 0:
        return {"error": "limit must be > 0"}

    src_dir = config.COMFY_OUTPUT_DIR
    if not src_dir.exists() or not src_dir.is_dir():
        return {"error": f"COMFY_OUTPUT_DIR not found: {src_dir}"}

    files = _list_media_files(src_dir)[:limit]
    if not files:
        return {"code": code, "story_id": _safe_story_id(story_id) if story_id else None, "ingested": 0, "assets": []}

    char_dir = config.CHARACTERS_IMAGE_DIR / code
    char_dir.mkdir(parents=True, exist_ok=True)

    story_assets_dir = None
    sid = None
    if story_id.strip():
        sid = _safe_story_id(story_id)
        story_assets_dir = _story_dir(sid) / "assets" / code
        story_assets_dir.mkdir(parents=True, exist_ok=True)

    op = shutil.move if mode == "move" else shutil.copy2
    ingested = []
    for idx, p in enumerate(files, start=1):
        suffix = p.suffix.lower()
        stamped_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{idx:03d}_{p.name}"
        char_dest = char_dir / stamped_name
        op(str(p), str(char_dest))
        entry = {
            "source": str(p),
            "character_path": str(char_dest),
            "filename": char_dest.name,
            "bytes": char_dest.stat().st_size,
            "mime_type": mimetypes.guess_type(char_dest.name)[0] or "application/octet-stream",
            "ext": suffix,
        }
        if story_assets_dir is not None:
            story_dest = story_assets_dir / char_dest.name
            shutil.copy2(char_dest, story_dest)
            entry["story_path"] = str(story_dest)
        ingested.append(entry)

    if sid:
        manifest = _story_manifest(sid)
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        story_json = _story_dir(sid) / "story.json"
        story_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {"code": code, "story_id": sid, "mode": mode, "ingested": len(ingested), "assets": ingested}


@mcp.tool
def build_story_page(story_id: str, title: str = "", character_codes: list[str] | None = None, notes: str = "") -> dict:
    """Generate stories/<story_id>/index.html from currently ingested story assets."""
    sid = _safe_story_id(story_id)
    sdir = _story_dir(sid)
    manifest = _story_manifest(sid)
    if title.strip():
        manifest["title"] = title.strip()
    if character_codes is not None:
        manifest["characters"] = sorted({c.strip() for c in character_codes if c and c.strip()})
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()

    story_json = sdir / "story.json"
    story_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    html = _render_story_html(manifest, notes=notes)
    html_path = sdir / "index.html"
    html_path.write_text(html, encoding="utf-8")

    return {
        "story_id": sid,
        "title": manifest.get("title"),
        "characters": manifest.get("characters", []),
        "assets_count": len(manifest.get("assets") or []),
        "story_json": str(story_json),
        "html_path": str(html_path),
    }


@mcp.tool
def list_stories() -> dict:
    """List stories found under STORIES_DIR."""
    rows = []
    if config.STORIES_DIR.exists() and config.STORIES_DIR.is_dir():
        for p in sorted(config.STORIES_DIR.iterdir()):
            if not p.is_dir():
                continue
            manifest = _story_manifest(p.name)
            rows.append(
                {
                    "story_id": p.name,
                    "title": manifest.get("title") or p.name,
                    "assets_count": len(manifest.get("assets") or []),
                    "characters": manifest.get("characters") or [],
                }
            )
    return {"count": len(rows), "stories": rows}


@mcp.tool
async def comfy_generate_image(prompt: str) -> dict:
    return await _call_comfy_tool("generate_image", {"prompt": prompt})


@mcp.tool
async def comfy_flux2_text_to_image(prompt: str, output_filename_prefix: str, width: int, height: int) -> dict:
    return await _call_comfy_tool(
        "flux2_text_to_image",
        {
            "prompt": prompt,
            "output_filename_prefix": output_filename_prefix,
            "width": width,
            "height": height,
        },
    )


@mcp.tool
async def comfy_flux2_single_image_edit(
    prompt: str,
    reference_image_filename: str,
    output_filename_prefix: str,
    width: int,
    height: int,
) -> dict:
    return await _call_comfy_tool(
        "flux2_single_image_edit",
        {
            "prompt": prompt,
            "reference_image_filename": reference_image_filename,
            "output_filename_prefix": output_filename_prefix,
            "width": width,
            "height": height,
        },
    )


@mcp.tool
async def comfy_flux2_double_image_edit(
    prompt: str,
    reference_image_filename_1: str,
    reference_image_filename_2: str,
    output_filename_prefix: str,
    width: int,
    height: int,
) -> dict:
    return await _call_comfy_tool(
        "flux2_double_image_edit",
        {
            "prompt": prompt,
            "reference_image_filename_1": reference_image_filename_1,
            "reference_image_filename_2": reference_image_filename_2,
            "output_filename_prefix": output_filename_prefix,
            "width": width,
            "height": height,
        },
    )


@mcp.tool
async def comfy_ltx2_singlepass_t2v(
    prompt: str,
    output_video_filename_prefix: str,
    output_lastframe_filename_prefix: str,
    video_length_seconds: int,
) -> dict:
    return await _call_comfy_tool(
        "ltx2_singlepass_t2v",
        {
            "prompt": prompt,
            "output_video_filename_prefix": output_video_filename_prefix,
            "output_lastframe_filename_prefix": output_lastframe_filename_prefix,
            "video_length_seconds": video_length_seconds,
        },
    )


@mcp.tool
async def comfy_ltx2_singlepass_i2v(
    prompt: str,
    first_frame_image_filename: str,
    output_video_filename_prefix: str,
    output_lastframe_filename_prefix: str,
    video_length_seconds: int,
) -> dict:
    return await _call_comfy_tool(
        "ltx2_singlepass_i2v",
        {
            "prompt": prompt,
            "first_frame_image_filename": first_frame_image_filename,
            "output_video_filename_prefix": output_video_filename_prefix,
            "output_lastframe_filename_prefix": output_lastframe_filename_prefix,
            "video_length_seconds": video_length_seconds,
        },
    )


@mcp.tool
async def comfy_qwentts_voice(speech_text: str, voice_instruct: str, output_filename_prefix: str) -> dict:
    return await _call_comfy_tool(
        "qwentts_voice",
        {
            "speech_text": speech_text,
            "voice_instruct": voice_instruct,
            "output_filename_prefix": output_filename_prefix,
        },
    )


@mcp.tool
async def comfy_generate_song(tags: str, lyrics: str) -> dict:
    return await _call_comfy_tool("generate_song", {"tags": tags, "lyrics": lyrics})


@mcp.tool
def init_story_repo(story_id: str, github_repo: str = "") -> dict:
    """Initialize a local git repo for a story and optionally set GitHub origin."""
    result = _ensure_story_repo(story_id)
    if not result.get("ok"):
        return result

    sid = _safe_story_id(story_id)
    repo_dir = _story_repo_dir(sid)
    target_repo = github_repo.strip() or config.STORY_GITHUB_REPO
    if target_repo:
        remote_url = f"https://github.com/{target_repo}.git"
        rc, _ = _run_git(["remote", "remove", "origin"], repo_dir)
        if rc != 0:
            # Ignore if origin doesn't exist.
            pass
        rc, out = _run_git(["remote", "add", "origin", remote_url], repo_dir)
        if rc != 0:
            result["remote_error"] = out
        else:
            result["remote"] = remote_url
            result["github_repo"] = target_repo
    return result


@mcp.tool
def commit_story_repo(story_id: str, message: str = "chore: update story bundle") -> dict:
    """Sync story bundle into local repo and commit changes."""
    sid = _safe_story_id(story_id)
    synced = _sync_story_bundle_into_repo(sid)
    if not synced.get("ok"):
        return synced
    repo_dir = _story_repo_dir(sid)

    rc, out = _run_git(["add", "."], repo_dir)
    if rc != 0:
        return {"ok": False, "story_id": sid, "error": out}

    rc, out = _run_git(["commit", "-m", message], repo_dir)
    if rc != 0:
        # No-op commits are common in iterative runs.
        if "nothing to commit" in out.lower():
            return {"ok": True, "story_id": sid, "repo_dir": str(repo_dir), "committed": False, "message": out}
        return {"ok": False, "story_id": sid, "error": out}

    rc, sha = _run_git(["rev-parse", "HEAD"], repo_dir)
    return {
        "ok": True,
        "story_id": sid,
        "repo_dir": str(repo_dir),
        "committed": True,
        "commit": sha if rc == 0 else None,
    }


@mcp.tool
def push_story_repo(story_id: str, github_repo: str = "", branch: str = "main") -> dict:
    """Push story repo to GitHub; uses configured token if present."""
    sid = _safe_story_id(story_id)
    ensure = _ensure_story_repo(sid)
    if not ensure.get("ok"):
        return ensure
    repo_dir = _story_repo_dir(sid)
    target_repo = github_repo.strip() or config.STORY_GITHUB_REPO
    if not target_repo:
        return {"ok": False, "story_id": sid, "error": "No github_repo provided and STORY_GITHUB_REPO is empty"}
    if not config.GITHUB_TOKEN:
        return {"ok": False, "story_id": sid, "error": "GITHUB_TOKEN/GH_TOKEN is required for authenticated push"}

    authed_remote = f"https://x-access-token:{config.GITHUB_TOKEN}@github.com/{target_repo}.git"
    rc, _ = _run_git(["remote", "remove", "origin"], repo_dir)
    if rc != 0:
        pass
    rc, out = _run_git(["remote", "add", "origin", authed_remote], repo_dir)
    if rc != 0:
        return {"ok": False, "story_id": sid, "error": out}

    rc, out = _run_git(["push", "-u", "origin", branch], repo_dir)
    clean_remote = f"https://github.com/{target_repo}.git"
    _run_git(["remote", "set-url", "origin", clean_remote], repo_dir)
    if rc != 0:
        return {"ok": False, "story_id": sid, "error": out}

    return {"ok": True, "story_id": sid, "github_repo": target_repo, "branch": branch}


@mcp.tool(task=True)
async def refresh_character(code: str, ctx: Context) -> dict:
    """Fetch latest YAML for `code` from GitHub and download images for that code from HF dataset.

    This runs as a background task and reports progress via `ctx.report_progress`.
    Returns a summary dict: {"yaml_updated": bool, "images_copied": int}
    """
    result = {"yaml_updated": False, "images_copied": 0}

    # 1) Fetch YAML from GitHub
    try:
        repo = config.GITHUB_CHARACTERS_REPO
        path = config.GITHUB_CHARACTERS_PATH.strip("/")
        owner, name = repo.split("/")
        filename = f"{code}.yaml"
        api_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}/{filename}"
        resp = requests.get(api_url, timeout=30, headers=_github_headers())
        if resp.status_code == 200:
            meta = resp.json()
            download_url = meta.get("download_url")
            if download_url:
                raw = requests.get(download_url, timeout=30, headers=_github_headers())
                raw.raise_for_status()
                dest = config.CHARACTERS_DESC_DIR / filename
                dest.write_bytes(raw.content)
                result["yaml_updated"] = True
        else:
            LOG.info("No remote YAML for %s (status %s)", code, resp.status_code)
    except Exception as e:
        LOG.warning("Failed to refresh YAML for %s: %s", code, e)

    # 2) Download only this character's image subset from HF dataset
    try:
        copied = await asyncio.to_thread(_download_images_for_code, code)
        if copied:
            try:
                await ctx.report_progress(copied, copied, f"Copied {copied} assets for {code}")
            except Exception:
                pass
        result["images_copied"] = copied
    except Exception as e:
        LOG.warning("Failed to refresh images for %s: %s", code, e)

    return result


@mcp.tool
def list_character_images(code: str) -> list[dict]:
    """Return Image helper objects for files in characters/images/<code>/.

    Returning `Image` objects lets FastMCP convert them to MCP image content
    blocks automatically when returned as a list.
    """
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    imgs: list[dict] = []
    if not images_folder.exists() or not images_folder.is_dir():
        return imgs
    for p in sorted(images_folder.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            continue
        try:
            # Ensure a public copy exists and return a structured entry so
            # outputSchema validation can succeed for tool clients.
            public_path = _copy_to_public_dir(p, code)
            imgs.append(Image(path=public_path).to_image_content())
        except Exception:
            continue
    
    return imgs


@mcp.tool
def get_character_profile_image(code: str):
    """Tool-compatible helper that returns an Image helper for the profile image.

    This is provided for clients that call tools (not resources) so they get an
    actual image block (FastMCP will convert `Image` when returned in a list).
    """
    try:
        c = _load_yaml_for(code)
    except FileNotFoundError:
        return []

    profile_ref = c.get("profile_image")
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    images_list = []
    if images_folder.exists() and images_folder.is_dir():
        for p in sorted(images_folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                continue
            images_list.append(p)

    selected_path = None
    if profile_ref and isinstance(profile_ref, str):
        cand = Path(profile_ref)
        if cand.exists():
            selected_path = cand
        else:
            name = os.path.basename(urlparse(profile_ref).path)
            if name:
                local_matches = [p for p in images_list if p.name == name]
                if local_matches:
                    selected_path = local_matches[0]
                else:
                    global_matches = list(config.CHARACTERS_IMAGE_DIR.rglob(name))
                    if global_matches:
                        selected_path = global_matches[0]

    if not selected_path and images_list:
        selected_path = images_list[0]

    if not selected_path:
        return []

    try:
        return [Image(path=selected_path)]
    except Exception:
        return []


@mcp.resource(
    uri = "character://{code}/profile_image",
    mime_type = "image/*"
)
def character_profile_image(code: str) -> ResourceResult:
    """Return the character's profile image as a resource (binary with mime type).

    Chooses YAML `profile_image` if present (resolving local files), otherwise the
    first file in `characters/images/<code>/`.
    """
    try:
        c = _load_yaml_for(code)
    except FileNotFoundError:
        return ResourceResult(contents=[])

    profile_ref = c.get("profile_image")
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    images_list = []
    if images_folder.exists() and images_folder.is_dir():
        for p in sorted(images_folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                continue
            images_list.append(p)

    selected_path = None
    if profile_ref and isinstance(profile_ref, str):
        cand = Path(profile_ref)
        if cand.exists():
            selected_path = cand
        else:
            name = os.path.basename(urlparse(profile_ref).path)
            if name:
                local_matches = [p for p in images_list if p.name == name]
                if local_matches:
                    selected_path = local_matches[0]
                else:
                    global_matches = list(config.CHARACTERS_IMAGE_DIR.rglob(name))
                    if global_matches:
                        selected_path = global_matches[0]

    if not selected_path and images_list:
        selected_path = images_list[0]

    if not selected_path:
        return ResourceResult(contents=[])

    mime = mimetypes.guess_type(selected_path.name)[0] or "application/octet-stream"
    
    # Ensure public copy exists and return a FileResource referencing it
    public_path = _copy_to_public_dir(selected_path, code)
    #file_res = FileResource(path=str(public_path.absolute()), is_binary=True, mime_type=mime, uri=public_path.absolute().as_uri())
    return ResourceResult(
        contents=[
            ResourceContent(
                mime_type=mime,
                meta={"filename": selected_path.name},
                content=public_path.read_bytes()
             )
            ]
        )

@mcp.resource("character://{code}/images")
def character_images_resource(code: str) -> ResourceResult:
    """Return the character's images as a resource (binary with mime type)."""
    try:
        c = _load_yaml_for(code)
    except FileNotFoundError:
        return ResourceResult(contents=[])
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    images_list = []
    if images_folder.exists() and images_folder.is_dir():
        for p in sorted(images_folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                continue
            images_list.append(p)

    if not images_list:
        return ResourceResult(contents=[])

    try:
        return ResourceResult(
            contents=[
                ResourceContent(
                        mime_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                        meta={"filename": p.name},
                        content=p.read_bytes()
                    ) 
                    for p in images_list
                ])
    except Exception:
        return ResourceResult(contents=[])   


@mcp.resource(
    uri = "character://{code}/profile",
    mime_type = "application/json"
)
def character_profile_resource(code: str) -> ResourceResult:
    """Return the character's profile as JSON resource."""
    try:
        c = _load_yaml_for(code)
    except FileNotFoundError:
        return ResourceResult(contents=[])
    try:
        return ResourceResult(contents=[ResourceContent(
            mime_type="application/json",
            content=json.dumps(c)
        )])
    except Exception:
        return ResourceResult(contents=[])


def main(argv: list[str] | None = None) -> None:
    global _runtime_transport
    parser = argparse.ArgumentParser(prog="storyworld-mcp")
    parser.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio",
                        help="Transport to use: stdio (default), http (streamable HTTP), or sse")
    parser.add_argument("--host", default=None, help="Host to bind when using network transports")
    parser.add_argument("--port", type=int, default=None, help="Port to bind when using network transports")
    parser.add_argument("--images-dir", default=None,
                        help="Directory where character images are stored (overrides CHARACTERS_IMAGE_DIR env)")
    parser.add_argument("--public-images-dir", default=None,
                        help="Directory where requested images are copied for public access (overrides PUBLIC_IMAGES_DIR env)")
    parser.add_argument("--comfy-output-dir", default=None,
                        help="Directory containing local ComfyUI output files to ingest (overrides COMFY_OUTPUT_DIR env)")
    parser.add_argument("--stories-dir", default=None,
                        help="Directory where generated story bundles are written (overrides STORIES_DIR env)")
    parser.add_argument("--workspace-dir", default=None,
                        help="Workspace root for story assets and outputs (overrides WORKSPACE_DIR env)")
    parser.add_argument("--comfyui-url", default=None,
                        help="ComfyUI base URL used by upstream/local generation workflows")
    ns = parser.parse_args(argv if argv is not None else sys.argv[1:])

    # Apply runtime override for images dir if provided
    if ns.images_dir:
        try:
            new_img_dir = Path(ns.images_dir)
            config.CHARACTERS_IMAGE_DIR = new_img_dir
            config.CHARACTERS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            LOG.info("Using images dir: %s", config.CHARACTERS_IMAGE_DIR)
        except Exception as ex:
            LOG.warning("Failed to apply --images-dir %s: %s", ns.images_dir, ex)

    # Allow overriding PUBLIC_IMAGES_DIR via CLI; store in env so helper reads it
    if getattr(ns, "public_images_dir", None):
        try:
            pub = Path(ns.public_images_dir)
            pub.mkdir(parents=True, exist_ok=True)
            os.environ["PUBLIC_IMAGES_DIR"] = str(pub)
            LOG.info("Using public images dir: %s", pub)
        except Exception as ex:
            LOG.warning("Failed to apply --public-images-dir %s: %s", ns.public_images_dir, ex)

    if getattr(ns, "comfy_output_dir", None):
        try:
            out_dir = Path(ns.comfy_output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            config.COMFY_OUTPUT_DIR = out_dir
            LOG.info("Using Comfy output dir: %s", out_dir)
        except Exception as ex:
            LOG.warning("Failed to apply --comfy-output-dir %s: %s", ns.comfy_output_dir, ex)

    if getattr(ns, "stories_dir", None):
        try:
            stories_dir = Path(ns.stories_dir)
            stories_dir.mkdir(parents=True, exist_ok=True)
            config.STORIES_DIR = stories_dir
            LOG.info("Using stories dir: %s", stories_dir)
        except Exception as ex:
            LOG.warning("Failed to apply --stories-dir %s: %s", ns.stories_dir, ex)

    if getattr(ns, "workspace_dir", None):
        try:
            workspace = Path(ns.workspace_dir).resolve()
            workspace.mkdir(parents=True, exist_ok=True)
            config.WORKSPACE_DIR = workspace
            if not ns.images_dir:
                config.CHARACTERS_IMAGE_DIR = workspace / "characters" / "images"
                config.CHARACTERS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            if not ns.stories_dir:
                config.STORIES_DIR = workspace / "stories"
                config.STORIES_DIR.mkdir(parents=True, exist_ok=True)
            if not ns.comfy_output_dir:
                config.COMFY_OUTPUT_DIR = workspace / "comfy-output"
                config.COMFY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            config.STORY_REPOS_DIR = config.STORIES_DIR / "repos"
            config.STORY_REPOS_DIR.mkdir(parents=True, exist_ok=True)
            LOG.info("Using workspace dir: %s", workspace)
        except Exception as ex:
            LOG.warning("Failed to apply --workspace-dir %s: %s", ns.workspace_dir, ex)

    if getattr(ns, "comfyui_url", None):
        try:
            config.COMFYUI_URL = ns.comfyui_url.strip()
            LOG.info("Using COMFYUI_URL: %s", config.COMFYUI_URL)
        except Exception as ex:
            LOG.warning("Failed to apply --comfyui-url %s: %s", ns.comfyui_url, ex)

    transport = ns.transport
    _runtime_transport = transport
    _configure_comfy_proxy(transport)

    if transport == "stdio":
        mcp.run(show_banner=config.FASTMCP_SHOW_BANNER, log_level=config.FASTMCP_LOG_LEVEL)
        return

    host = ns.host or "127.0.0.1"
    port = ns.port or 3334
    if transport == "http":
        mcp.run(
            transport="http",
            host=host,
            port=port,
            show_banner=config.FASTMCP_SHOW_BANNER,
            log_level=config.FASTMCP_LOG_LEVEL,
        )
    elif transport == "sse":
        mcp.run(
            transport="sse",
            host=host,
            port=port,
            show_banner=config.FASTMCP_SHOW_BANNER,
            log_level=config.FASTMCP_LOG_LEVEL,
        )


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
