from __future__ import annotations

from pathlib import Path

import pytest

from anvil.server import build_server


@pytest.mark.asyncio
async def test_every_tool_has_a_title_annotation(fake_contexts_yaml: Path) -> None:
    """Anthropic Directory review requires a human-readable title on every tool.

    The title drives the host's confirmation UI and the connector listing.
    """

    mcp = build_server()
    tools = await mcp.list_tools()

    missing_title = [
        tool.name
        for tool in tools
        if tool.annotations is None or not tool.annotations.title
    ]

    assert missing_title == [], f"tools missing a title annotation: {missing_title}"
