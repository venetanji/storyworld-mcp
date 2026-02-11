"""Downloader for character YAMLs (GitHub) and images (Hugging Face).
Default sources mirror the user's provided repos; both are overrideable.

This module exposes the same `fetch_all` function used by the HTTP routes and the FastMCP tools.
"""
from pathlib import Path
import requests
import shutil
import os
import logging
import yaml
from huggingface_hub import snapshot_download
from . import config

LOG = logging.getLogger(__name__)


def _github_list_and_download(repo: str, path: str, dest: Path):
    """List files in `path` from GitHub repo and download YAMLs into dest."""
    owner, name = repo.split("/")
    api_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}"
    resp = requests.get(api_url, timeout=30)
    resp.raise_for_status()
    items = resp.json()
    for it in items:
        if it.get("type") == "file" and it.get("name", "").endswith(".yaml"):
            raw = requests.get(it["download_url"], timeout=30)
            raw.raise_for_status()
            dest_path = dest / it["name"]
            dest_path.write_bytes(raw.content)
            LOG.info("Downloaded %s -> %s", it["name"], dest_path)


def _hf_download_images(dataset_id: str, dest: Path, subfolder: str | None = None):
    """Use huggingface_hub to snapshot the dataset and copy images to dest."""
    cache_dir = Path(".cache") / "hf-datasets"
    snapshot_dir = snapshot_download(repo_type='dataset', repo_id=dataset_id, cache_dir=str(cache_dir))
    src = Path(snapshot_dir)
    # Copy common image types (user can override later)
    exts = ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp")
    for pattern in exts:
        for p in src.rglob(pattern):
            try:
                rel = p.relative_to(src)
            except Exception:
                rel = p.name
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            LOG.info("Copied image %s -> %s", p, out)


def fetch_all(github_repo: str | None = None, github_path: str | None = None, hf_dataset: str | None = None, dest_chars: Path | None = None, dest_images: Path | None = None):
    """Download character YAMLs and images into the configured local folders.

    By default this writes character YAMLs into `config.CHARACTERS_DESC_DIR`
    and images into `config.CHARACTERS_IMAGE_DIR` so the project keeps
    all character assets under `characters/`.

    This function is synchronous to make it easy to call from CLI, tests,
    and startup hooks.
    """
    github_repo = github_repo or config.GITHUB_CHARACTERS_REPO
    github_path = github_path or config.GITHUB_CHARACTERS_PATH
    hf_dataset = hf_dataset or config.HF_IMAGES_DATASET
    dest_chars = dest_chars or config.CHARACTERS_DESC_DIR
    # allow explicit top-level images dir, but default to characters/images
    dest_images = dest_images or config.CHARACTERS_IMAGE_DIR

    dest_chars.mkdir(parents=True, exist_ok=True)
    dest_images.mkdir(parents=True, exist_ok=True)

    LOG.info("Fetching characters from %s:%s -> %s", github_repo, github_path, dest_chars)
    _github_list_and_download(github_repo, github_path, dest_chars)

    LOG.info("Fetching images from HF dataset %s -> %s", hf_dataset, dest_images)
    try:
        _hf_download_images(hf_dataset, dest_images)
    except Exception as ex:
        LOG.warning("Failed to download HF images: %s", ex)


def list_local_character_codes():
    """Return sorted list of character codes found in the local characters dir."""
    codes = []
    for f in config.CHARACTERS_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            codes.append(data.get("code") or f.stem)
        except Exception:
            continue
    return sorted(codes)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-repo", default=None)
    parser.add_argument("--github-path", default=None)
    parser.add_argument("--hf-dataset", default=None)
    parser.add_argument("--dest-chars", default=None)
    parser.add_argument("--dest-images", default=None)
    args = parser.parse_args()
    fetch_all(args.github_repo, args.github_path, args.hf_dataset, Path(args.dest_chars) if args.dest_chars else None, Path(args.dest_images) if args.dest_images else None)
