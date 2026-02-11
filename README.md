# storyworld-mcp — FastMCP compatible MCP server

Lightweight MCP server that provides character contexts and assets for agent impersonation. This repository is now FastMCP-ready (MCP tools + HTTP compatibility).

## What this repo contains ✅
- FastMCP tools that expose character contexts and asset-download tooling
- Downloader that fetches character YAMLs from GitHub and images from Hugging Face
- (optional) HTTP convenience layer was removed in this iteration; use MCP tools directly
- Example character and images for local development
- Tests, Dockerfile, and GitHub Actions CI

## Quickstart (local) 🔧
1) Create a venv and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

2) (optional) create `.env` from the example and tweak sources:

```bash
cp .env.example .env
# edit .env to set HF dataset or GitHub repo overrides
```

3) Run the HTTP server (provides health + character endpoints):

```bash
uvicorn mcp_server.main:app --reload --host 0.0.0.0 --port ${PORT:-3333}
```

4) Run the FastMCP server (MCP protocol) for MCP clients:

```bash
# runs FastMCP on port 3334 by default
python -m mcp_server.mcp_app
```

## FastMCP tools (examples) 💡
- `list_characters()` — returns available character codes
- `get_character_context(code)` — returns an MCP-style context payload for a given character
- `fetch_characters(github_repo, github_path, hf_dataset)` — trigger remote download

Clients can use the provided `mcp.json` (dev) or connect to the FastMCP port.

## Data sources & overrides 🔁
Defaults (override with env vars or `.env`):
- GitHub characters repo: `venetanji/polyu-storyworld` (path: `characters/`)
- Hugging Face images dataset: `venetanji/polyu-storyworld-characters`

To manually fetch assets:

```bash
python -m scripts.fetch_data --github-repo venetanji/polyu-storyworld --github-path characters --hf-dataset venetanji/polyu-storyworld-characters
```

## Tests & CI ✅
- Run tests locally: `pytest -q`
- GitHub Actions run tests on push/PR (see `.github/workflows/ci.yml`).

## Publishing to GitHub (commands) 🔁
I prepared everything for a public repository named `storyworld-mcp` by default. To create the remote and push from your machine (recommended):

```bash
# create repo with gh (replace <owner> if needed)
gh repo create <owner>/storyworld-mcp --public --source=. --remote=origin
# push local main branch
git add .
git commit -m "chore: initialize FastMCP-compatible storyworld-mcp"
git branch -M main
git push -u origin main
```

If you prefer I can provide the exact `gh`/`git` commands for your GitHub username or push the repo for you (I will need a PAT configured).

## Security note ⚠️
Do not commit secrets. Use `.env` (ignored) and GitHub Actions repository secrets for CI.

---

Next steps I can do for you (pick any):
1. Create the public GitHub repo and push the initial commit (I can output exact commands). 
2. Add a release-ready `mcp.json` and publish to a static hosting endpoint.
3. Import remote character YAMLs/images into the repo (if you want them tracked).
