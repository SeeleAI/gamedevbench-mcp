from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Dict, List

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from config import config


async def _get_tools_from_client_session(
        client_context_manager: Any, timeout_seconds: int = 10
) -> List:
    async with client_context_manager as streams:
        try:
            read, write, _ = streams
        except Exception:
            read, write = streams
        async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=timeout_seconds)
        ) as session:
            # Initialize the connection
            await session.initialize()
            # List available tools
            listed_tools = await session.list_tools()
            return listed_tools.tools


async def _call_tool_from_client_session(
        client_context_manager: Any,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout_seconds: int = 10,
) -> Any:
    async with client_context_manager as streams:
        try:
            read, write, _ = streams
        except Exception:
            read, write = streams
        async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=timeout_seconds)
        ) as session:
            # Initialize the connection
            await session.initialize()

            # Call the tool
            result = await session.call_tool(tool_name, arguments)
            return result


async def call_tool_from_streamable_http(
        url: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout_seconds: int = 30,
        headers: dict[str, str] | None = None
):
    return await _call_tool_from_client_session(streamablehttp_client(url=url, headers=headers), tool_name, arguments,
                                                timeout_seconds=timeout_seconds)


async def main():
    import uuid
    property_id = uuid.uuid4()
    print(f"property_id:{property_id}")
    print(await _get_tools_from_client_session(streamablehttp_client(url=config.higress_asset_mcp_url)))
    r = await call_tool_from_streamable_http(config.higress_asset_mcp_url, "Search_item_assets", {
        "property_id": property_id,
        "category": "avatar",
        "text_prompt": "apple",
        "canvasId": "57b6ddf8-d476-4201-99a9-76e373b0d712"
    }, headers={
        "x-canvas-id": "57b6ddf8-d476-4201-99a9-76e373b0d712", "canvasId": "57b6ddf8-d476-4201-99a9-76e373b0d712",
        "canvas_id": "57b6ddf8-d476-4201-99a9-76e373b0d712",
        "seele_canvas_trace_id": "57b6ddf8-d476-4201-99a9-76e373b0d712|8793dc8b-3600-4487-a758-b055914ff20f|game_scene_creator-2ac851f24ef7cc9fc947b02d|test"})
    print(r)
    # print(await _get_tools_from_client_session(streamablehttp_client(url=config.higress_asset_mcp_url)))


if __name__ == "__main__":
    asyncio.run(main())
