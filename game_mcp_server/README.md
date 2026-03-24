# MCP for Unity Server

This package contains the MCP server used by the Unity Editor bridge. It exposes MCP tools for interacting with the Unity Editor and runs with `uv`.

- Entry points: `server.py` (local) and `server_deploy.py` (container/remote)
- Requires Python 3.12 

# 提交合并 
- 提交合并前建议本地先执行一次扫描，并修复相关问题
```bash
uv run ruff check . --fix

```

# 对应说明
## blender
- 需配合插件使用，插件地址：https://github.com/SeeleAI/blender_mcp_server/blob/master/addon.py