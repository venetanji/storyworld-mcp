import asyncio

from mcp_server import config, mcp_app


class _DummyCtx:
    async def report_progress(self, *_args, **_kwargs):
        return None


def test_list_characters_mcp_tool(tmp_path):
    desc_dir = tmp_path / "descriptions"
    img_dir = tmp_path / "images"
    desc_dir.mkdir(parents=True)
    img_dir.mkdir(parents=True)
    (desc_dir / "0000g.yaml").write_text(
        "name: Alice\nage: 21\npersonality: Positive: kind, curious\n",
        encoding="utf-8",
    )

    config.CHARACTERS_DESC_DIR = desc_dir
    config.CHARACTERS_IMAGE_DIR = img_dir

    res = mcp_app.list_characters()
    assert isinstance(res, dict)
    assert res["count"] == 1
    assert res["characters"][0]["code"] == "0000g"
    assert res["characters"][0]["name"] == "Alice"


def test_get_character_context_mcp_tool(tmp_path):
    desc_dir = tmp_path / "descriptions"
    img_dir = tmp_path / "images" / "0000g"
    desc_dir.mkdir(parents=True)
    img_dir.mkdir(parents=True)
    (desc_dir / "0000g.yaml").write_text(
        "name: Alice\npersona: friendly guide\nprofile_image: avatar.png\n",
        encoding="utf-8",
    )
    (img_dir / "avatar.png").write_bytes(b"fake")

    config.CHARACTERS_DESC_DIR = desc_dir
    config.CHARACTERS_IMAGE_DIR = tmp_path / "images"

    ctx = asyncio.run(mcp_app.get_character_context("0000g", _DummyCtx()))
    assert isinstance(ctx, list)
    assert ctx[0]["name"] == "Alice"
    assert "persona" in ctx[0]


def test_get_character_context_compact_and_manifest(tmp_path):
    desc_dir = tmp_path / "descriptions"
    img_dir = tmp_path / "images" / "6166r"
    desc_dir.mkdir(parents=True)
    img_dir.mkdir(parents=True)
    (desc_dir / "6166r.yaml").write_text(
        "name: Athena\nprofile_image: 5.png\nbackstory: test\n",
        encoding="utf-8",
    )
    (img_dir / "5.png").write_bytes(b"fakepng")
    (img_dir / "clip.mp4").write_bytes(b"fakevideo")

    config.CHARACTERS_DESC_DIR = desc_dir
    config.CHARACTERS_IMAGE_DIR = tmp_path / "images"

    compact = mcp_app.get_character_context_compact("6166r")
    assert compact["code"] == "6166r"
    assert compact["profile"]["name"] == "Athena"
    assert compact["profile_image_resource_uri"] == "character://6166r/profile_image"
    assert len(compact["images"]) == 1

    manifest = mcp_app.get_character_media_manifest("6166r")
    assert manifest["code"] == "6166r"
    assert manifest["count"] == 2
    names = {a["filename"] for a in manifest["assets"]}
    assert {"5.png", "clip.mp4"} <= names


def test_ingest_comfy_outputs_and_build_story_page(tmp_path):
    config.CHARACTERS_IMAGE_DIR = tmp_path / "images"
    config.CHARACTERS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    config.COMFY_OUTPUT_DIR = tmp_path / "comfy-output"
    config.COMFY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.STORIES_DIR = tmp_path / "stories"
    config.STORIES_DIR.mkdir(parents=True, exist_ok=True)

    (config.COMFY_OUTPUT_DIR / "frame_a.png").write_bytes(b"png")
    (config.COMFY_OUTPUT_DIR / "clip_a.mp4").write_bytes(b"mp4")

    ingested = mcp_app.ingest_comfy_outputs("6166r", story_id="studio-week-1", limit=10, mode="copy")
    assert ingested["ingested"] == 2
    assert ingested["story_id"] == "studio-week-1"

    result = mcp_app.build_story_page(
        "studio-week-1",
        title="Studio Week 1",
        character_codes=["6166r"],
        notes="First pass output",
    )
    assert result["assets_count"] == 2
    assert (tmp_path / "stories" / "studio-week-1" / "index.html").exists()
    assert (tmp_path / "stories" / "studio-week-1" / "story.json").exists()


def test_get_runtime_capabilities(tmp_path):
    config.COMFY_OUTPUT_DIR = tmp_path / "out"
    config.STORIES_DIR = tmp_path / "stories"
    config.CHARACTERS_DESC_DIR = tmp_path / "descriptions"
    config.CHARACTERS_IMAGE_DIR = tmp_path / "images"
    for p in (config.COMFY_OUTPUT_DIR, config.STORIES_DIR, config.CHARACTERS_DESC_DIR, config.CHARACTERS_IMAGE_DIR):
        p.mkdir(parents=True, exist_ok=True)

    caps = mcp_app.get_runtime_capabilities()
    assert "workspace_dir" in caps
    assert "comfyui_url" in caps
    assert "comfy_output_dir" in caps
    assert "stories_dir" in caps


def test_story_repo_init_and_commit(tmp_path):
    config.STORIES_DIR = tmp_path / "stories"
    config.STORIES_DIR.mkdir(parents=True, exist_ok=True)
    config.STORY_REPOS_DIR = tmp_path / "story-repos"
    config.STORY_REPOS_DIR.mkdir(parents=True, exist_ok=True)

    # Create a minimal story bundle first.
    built = mcp_app.build_story_page("repo-demo", title="Repo Demo", character_codes=["6166r"])
    assert built["assets_count"] == 0

    init = mcp_app.init_story_repo("repo-demo")
    assert init["ok"] is True
    assert (tmp_path / "story-repos" / "repo-demo" / ".git").exists()

    commit = mcp_app.commit_story_repo("repo-demo", message="test commit")
    assert commit["ok"] is True
    assert "repo_dir" in commit


def test_story_repo_push_requires_token(tmp_path):
    config.STORY_REPOS_DIR = tmp_path / "story-repos"
    config.STORY_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    config.GITHUB_TOKEN = ""
    config.STORY_GITHUB_REPO = ""

    res = mcp_app.push_story_repo("repo-demo", github_repo="owner/repo")
    assert res["ok"] is False
    assert "required" in res["error"].lower()


def test_load_yaml_fetches_on_demand(tmp_path):
    config.CHARACTERS_DESC_DIR = tmp_path / "descriptions"
    config.CHARACTERS_DESC_DIR.mkdir(parents=True, exist_ok=True)
    target = config.CHARACTERS_DESC_DIR / "6166r.yaml"

    original = mcp_app._download_yaml_for_code

    def _fake_fetch(code: str):
        if code == "6166r":
            target.write_text("name: Athena\npersona: test\n", encoding="utf-8")
            return target
        return None

    mcp_app._download_yaml_for_code = _fake_fetch
    try:
        data = mcp_app._load_yaml_for("6166r")
    finally:
        mcp_app._download_yaml_for_code = original

    assert data["name"] == "Athena"
