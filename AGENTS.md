# AGENTS.md

## Project Scope
- Repository: `storyworld-mcp`
- Compose project: `storyworld-mcp`
- Primary app container: `storyworld-mcp-mcp-1`
- Tailscale sidecar: `storyworld-mcp-tailscale-serve-1`
- External MCP URL: `https://polyu-storyworld.tail9683c.ts.net/mcp`

## First Checks
- Read `compose.yaml` before changing runtime behavior.
- Confirm running services with `docker ps`.
- Use `docker inspect` for source-of-truth runtime details:
  - compose project + working directory labels
  - service command and entrypoint
  - mounts and volumes
  - network mode (app runs through tailscale sidecar)
- Check recent logs with `docker logs --tail 200 storyworld-mcp-mcp-1`.

## Runtime Notes
- `mcp` runs with `network_mode: service:tailscale-serve`.
- App command is `python -m mcp_server.mcp_app --transport http`.
- Persistent data:
  - character assets: Docker volume mounted at `/app/characters`
  - Hugging Face cache: Docker volume mounted at `/root/.cache/huggingface`
- MCP endpoint path is `/mcp` and is served over streamable HTTP transport.

## FastMCP v3 Conventions
- Prefer provider-based composition over monolithic files.
- Keep server metadata on `FastMCP(...)` (name, instructions, version, URLs).
- Use composable lifespans for startup/shutdown work.
- Use `FileSystemProvider` for optional local tool expansion.
- Keep `ResourcesAsTools` enabled for tool-only clients.
- `fastmcp-docs` MCP tool is available in this environment; use it as the primary reference for FastMCP API/behavior before ad-hoc guessing.

## Local Development
- Python package source is under `src/mcp_server`.
- Default command:
  - `python -m mcp_server.mcp_app --transport http --host 0.0.0.0 --port 3334`
- Optional dynamic tools directory:
  - `tools/` (repo root)
  - enable request-time reload via `FASTMCP_TOOLS_RELOAD=1`

## Safety
- Do not expose secrets from `.env`, container env, or compose outputs.
- Treat `docker inspect` and live container behavior as truth over assumptions.
- Avoid destructive Docker or git commands unless explicitly requested.
