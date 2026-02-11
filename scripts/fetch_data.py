"""Convenience CLI to fetch character YAMLs and images (wraps mcp_server.downloader)."""
from pathlib import Path
import argparse
from mcp_server import downloader


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--github-repo", default=None)
    p.add_argument("--github-path", default=None)
    p.add_argument("--hf-dataset", default=None)
    p.add_argument("--dest-chars", default=None)
    p.add_argument("--dest-images", default=None)
    args = p.parse_args()
    downloader.fetch_all(args.github_repo, args.github_path, args.hf_dataset, Path(args.dest_chars) if args.dest_chars else None, Path(args.dest_images) if args.dest_images else None)


if __name__ == "__main__":
    main()
