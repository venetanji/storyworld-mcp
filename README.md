# storyworld-mcp — FastMCP compatible MCP server

Lightweight MCP server that provides character contexts and assets for agent impersonation. The server uses FastMCP v3 patterns (lifespan startup, resources-as-tools transform, and optional file-based dynamic tools).

## What this repo contains ✅
- FastMCP tools that expose character contexts and asset-download tooling
- Downloader that fetches character YAMLs from GitHub and images from Hugging Face
- FastMCP v3 lifecycle startup for first-run asset bootstrap
- Optional `tools/` provider for drop-in extra tools during development
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

Recommended `.env` additions for your lab/local flow:

```bash
WORKSPACE_DIR=/path/to/storyworld-workspace
COMFYUI_URL=http://127.0.0.1:8188
COMFY_OUTPUT_DIR=/path/to/storyworld-workspace/comfy-output
STORIES_DIR=/path/to/storyworld-workspace/stories
COMFY_MCP_AUTO_SPAWN=1
FASTMCP_SHOW_BANNER=0
FASTMCP_LOG_LEVEL=WARNING
```

3) Run the FastMCP server (MCP protocol) for MCP clients:

```bash
# runs FastMCP on port 3334 by default
python -m mcp_server.mcp_app
```

4) Optional: enable auto-reload for Python tools dropped into `./tools`:

```bash
FASTMCP_TOOLS_RELOAD=1 python -m mcp_server.mcp_app --transport http --host 0.0.0.0 --port 3334
```

## FastMCP tools (examples) 💡
- `list_characters()` — returns available character codes
- `get_character_context(code)` — returns an MCP-style context payload for a given character
- `get_character_context_compact(code)` — returns profile + media references only (no embedded image binary)
- `get_character_media_manifest(code)` — returns local/public media manifest with file metadata
- `refresh_character(code)` — refresh YAML and image assets for one character
- `get_runtime_capabilities()` — returns active runtime dirs/flags (`COMFY_OUTPUT_DIR`, `STORIES_DIR`, proxy status)
- `ingest_comfy_outputs(code, story_id?, limit?, mode?)` — ingests recent media from local Comfy output folder
- `build_story_page(story_id, title?, character_codes?, notes?)` — writes static `stories/<story_id>/index.html` + `story.json`
- `list_stories()` — lists story bundles under `STORIES_DIR`
- `init_story_repo(story_id, github_repo?)` — initializes local git repo for a story and optional origin
- `commit_story_repo(story_id, message?)` — syncs story bundle and commits changes
- `push_story_repo(story_id, github_repo?, branch?)` — pushes to GitHub using `GITHUB_TOKEN`/`GH_TOKEN`
- `comfy_list_tools()` — returns available downstream comfy tools (for diagnostics)
- Wrapped comfy generation tools:
  - `comfy_generate_image`
  - `comfy_flux2_text_to_image`
  - `comfy_flux2_klein_multiple_angles`
  - `comfy_flux2_single_image_edit`
  - `comfy_flux2_double_image_edit`
  - `comfy_ltx2_singlepass_t2v`
  - `comfy_ltx2_singlepass_i2v`
  - `comfy_qwentts_voice`
  - `comfy_generate_song`

Clients can connect directly to the FastMCP endpoint.

### Optional provider composition
- Default mode is `COMFY_MOUNT_MODE=wrapped` (recommended): Storyworld exposes local comfy wrapper tools and calls comfy on tool execution. This keeps `list_tools` fast in LM Studio/Inspector.
- Optional `COMFY_MOUNT_MODE=mount`: mount the entire comfy MCP namespace directly (can make `list_tools` slower if downstream startup/discovery is slow).
- `http` mode (public instance): comfy proxy is disabled by default.
- Set `COMFY_PROXY_IN_HTTP=1` to enable comfy proxy also in `http` mode.
- `stdio` mode (lab/client mode): comfy proxy can be sourced from either:
  - `COMFY_MCP_URL` (remote/local HTTP MCP endpoint), or
  - `COMFY_MCP_STDIO_COMMAND` + `COMFY_MCP_STDIO_ARGS` (spawn local comfyui-mcp process).
  - If neither is set, Storyworld auto-spawns comfyui-mcp with:
    - `uvx --from ${COMFY_MCP_SERVER_SPEC} ${COMFY_MCP_SERVER_ENTRYPOINT} --comfy-url ${COMFYUI_URL} --output-folder ${COMFY_OUTPUT_DIR}`

## Lab-friendly local setup 🧪
For student lab machines, run ComfyUI + Comfy MCP locally and keep this server local as well.

- Set `COMFY_OUTPUT_DIR` to the folder where Comfy writes generated files.
- Set `STORIES_DIR` to a writable folder for static story bundles.
- `WORKSPACE_DIR` can be used as a single root folder that contains everything:
  - `characters/` (downloaded profiles + images)
  - `comfy-output/` (generated media to ingest)
  - `stories/` (story bundles + html output)
- Optional story repo config:
  - `STORY_REPOS_DIR` local repos root
  - `STORY_GITHUB_REPO` default `owner/repo` for pushes
  - `GITHUB_TOKEN` or `GH_TOKEN` for authenticated GitHub API/push operations
- Students can call generation tools (their local Comfy MCP), then call:
  1. `ingest_comfy_outputs(code=..., story_id=...)`
  2. `build_story_page(story_id=..., character_codes=[...])`
  3. `init_story_repo(...)`, `commit_story_repo(...)`, `push_story_repo(...)` when they want git-backed story publishing
- Publish `stories/<story_id>/` directly to GitHub Pages (or copy into a story repo and commit).

## Startup & On-Demand Loading ⚡
- Startup prefetch is opt-in (`STARTUP_PREFETCH=1`).
- Keep `DISABLE_AUTO_DOWNLOAD=1` to force pure on-demand behavior.
- Character YAML is fetched from GitHub when first requested if missing locally.
- Character images are fetched from Hugging Face on demand by character code, using partial dataset download patterns instead of full snapshot.
- This keeps MCP startup fast and avoids early timeout pressure in stdio/http clients.

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
