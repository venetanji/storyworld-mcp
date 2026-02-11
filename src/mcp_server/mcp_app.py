"""FastMCP integration: register MCP tools that expose the character dataset.

This module is self-contained and does not depend on any HTTP routes.
Run in dev with:

    python -m mcp_server.mcp_app

Tools:
- list_characters() -> {count, codes}
- get_character_context(code) -> MCP-style context dict
- list_character_images(code) -> list of images for the character
- fetch_characters(...) -> trigger downloader
"""
from fastmcp import FastMCP
import logging
from pathlib import Path
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
from fastmcp.resources import ResourceResult, ResourceContent, FileResource
from fastmcp.server.transforms import ResourcesAsTools
import json

LOG = logging.getLogger(__name__)

mcp = FastMCP("storyworld-mcp")
# Expose resources as tools for clients that only support tools
mcp.add_transform(ResourcesAsTools(mcp))


def _load_yaml_for(code: str) -> dict:
    p = config.CHARACTERS_DESC_DIR / f"{code}.yaml"
    if not p.exists():
        matches = list(config.CHARACTERS_DESC_DIR.glob(f"{code}*.yaml"))
        if matches:
            p = matches[0]
    if not p.exists():
        raise FileNotFoundError(p)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {"text": str(raw)}
    return raw


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


@mcp.tool
def list_characters() -> dict:
    """Return a summary with character codes found locally."""
    entries = []
    for f in config.CHARACTERS_DESC_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
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

    # If we don't have any images locally, download images for this character on demand.
    if not images_list:
        hf_dataset = config.HF_IMAGES_DATASET
        cache_dir = Path('.cache') / 'hf-datasets'
        try:
            # Snapshot the HF dataset in a thread
            snapshot_dir = await asyncio.to_thread(snapshot_download, repo_type='dataset', repo_id=hf_dataset, cache_dir=str(cache_dir))
            src = Path(snapshot_dir)
            exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
            matches = []
            for p in src.rglob('*'):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in exts:
                    continue
                try:
                    rel = p.relative_to(src)
                except Exception:
                    continue
                # Only copy files that are in a folder matching the character code
                if len(rel.parts) > 0 and rel.parts[0] == code:
                    matches.append((p, rel))

            total = len(matches)
            if total:
                for idx, (p, rel) in enumerate(matches, start=1):
                    dest = config.CHARACTERS_IMAGE_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    # copy in thread to avoid blocking event loop
                    await asyncio.to_thread(shutil.copy2, p, dest)
                    # report progress to client (progress, total, message)
                    try:
                        await ctx.report_progress(idx, total, f"Downloading {rel}")
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

    embedded = []
    if selected_path and selected_path.exists():
        try:
            # Ensure a public copy exists for external access, but keep return type
            # identical (we still append an Image content object).
            public_path = _copy_to_public_dir(selected_path, code)
            img = Image(path=public_path)
            embedded.append(img.to_image_content())
        except Exception:
            pass

    if images_list:
        content["images_count"] = len(images_list)

    # Return as [content] + embedded (embedded contains at most one image)
    return [content] + embedded


@mcp.tool
def list_character_images(code: str) -> list:
    """Return Image helper objects for files in characters/images/<code>/.

    Returning `Image` objects lets FastMCP convert them to MCP image content
    blocks automatically when returned as a list.
    """
    images_folder = config.CHARACTERS_IMAGE_DIR / code
    imgs = []
    if not images_folder.exists() or not images_folder.is_dir():
        return imgs
    for p in sorted(images_folder.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            continue
        try:
            imgs.append(Image(path=p))
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


@mcp.resource("character://{code}/profile_image")
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
    # Return the raw file bytes as ResourceContent so tooling/transport can
    # deliver binary image data instead of a JSON-serialized FileResource.
    try:
        data = selected_path.read_bytes()
        wrapped = ResourceContent(data, mime_type=mime, name=selected_path.name)
        return ResourceResult(contents=[wrapped])
    except Exception:
        # Fallback to empty result on any read error
        return ResourceResult(contents=[])



@mcp.resource("character://{code}/profile")
def character_profile_resource(code: str) -> ResourceResult:
    """Return the character's profile as JSON resource."""
    try:
        c = _load_yaml_for(code)
    except FileNotFoundError:
        return ResourceResult(contents=[])
    try:
        payload = json.dumps(c, ensure_ascii=False)
        return ResourceResult(payload)
    except Exception:
        return ResourceResult(contents=[])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="storyworld-mcp")
    parser.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio",
                        help="Transport to use: stdio (default), http (streamable HTTP), or sse")
    parser.add_argument("--host", default=None, help="Host to bind when using network transports")
    parser.add_argument("--port", type=int, default=None, help="Port to bind when using network transports")
    parser.add_argument("--images-dir", default=None,
                        help="Directory where character images are stored (overrides CHARACTERS_IMAGE_DIR env)")
    parser.add_argument("--public-images-dir", default=None,
                        help="Directory where requested images are copied for public access (overrides PUBLIC_IMAGES_DIR env)")
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

    # First-run: fetch remote data if no descriptions present
    desc_files = list(config.CHARACTERS_DESC_DIR.glob("*.yaml"))
    if not desc_files and not config.DISABLE_AUTO_DOWNLOAD:
        LOG.info("No local character descriptions found; fetching remote data...")
        try:
            downloader.fetch_all()
        except Exception as ex:
            LOG.warning("Initial fetch failed: %s", ex)

    transport = ns.transport
    if transport == "stdio":
        mcp.run()
        return

    host = ns.host or "127.0.0.1"
    port = ns.port or 3334
    if transport == "http":
        mcp.run(transport="http", host=host, port=port)
    elif transport == "sse":
        mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
