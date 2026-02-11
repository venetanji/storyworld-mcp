import pytest
from mcp_server import mcp_app


def test_list_characters_mcp_tool():
    res = mcp_app.list_characters()
    assert isinstance(res, dict)
    assert "codes" in res
    assert "0000g" in res["codes"]


def test_get_example_context_mcp_tool():
    ctx = mcp_app.get_character_context("0000g")
    assert ctx["id"] == "0000g"
    assert "persona" in ctx["content"]
    assert isinstance(ctx["content"].get("images", []), list)
