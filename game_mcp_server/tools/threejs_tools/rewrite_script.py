"""Rewrite remote project file tool for MCP."""
from datetime import datetime
import logging
from typing import Dict, Any, List
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
from config import config
from util.context_util import get_context_canvas_id
from util.env_client import env_client
from .storage.s3_helper import get_s3_storage

logger = logging.getLogger(__name__)

class TodoItem(BaseModel):
    id: str = Field(..., description="Unique identifier for the task")
    content: str = Field(..., description="Description of the task to be completed")
    status: str = Field(
        ..., 
        description="Current status: pending, in_progress, or completed",
        pattern="^(pending|in_progress|completed)$"
    )
    priority: str = Field(
        ..., 
        description="Priority level: high, medium, or low",
        pattern="^(high|medium|low)$"
    )


def todos_to_markdown(todos: list[TodoItem]) -> str:
    STATUS_MARK = {"completed": "x", "in_progress": "-", "pending": " "}
    PRIORITY_EMOJI = {"high": "!!!", "medium": "!!", "low": "!"}
    sections: dict[str, list] = {"high": [], "medium": [], "low": []}
    for t in todos:
        sections[t.priority].append(t)

    lines = [
        "# TODO",
        "",
        f"> Last updated: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]

    for priority in ("high", "medium", "low"):
        items = sections[priority]
        if not items:
            continue
        emoji = PRIORITY_EMOJI[priority]
        lines.append(f"## {emoji} {priority.upper()}")
        lines.append("")
        for t in items:
            mark = STATUS_MARK[t.status]
            lines.append(f"- [{mark}] `{t.id}` {t.content}")
        lines.append("")

    return "\n".join(lines)


    
def register_rewrite_script_tool(mcp: FastMCP):
    """Register the rewrite_script tool with the MCP server."""
    @mcp.tool(description=(
        "Use this tool to create and manage a structured task list for the current coding session. "
        "This helps track progress on complex tasks with multiple steps. "
        "Note: This performs a full replacement of the todo list, not an append."
        "Args: "
        "    - uri: default to 'agent/todo/all/TODO.md'\n"
        "    - todos: The complete todo list to store (full replacement, not append)\n"
        "    - task_name: default to 'todo write'.\n"
    ))
    async def todo_write(
        ctx: Context,
        uri:str,
        todos: List[TodoItem],
        task_name: str = "todo write",
    ) -> Dict[str, Any]:
        markdown_content = todos_to_markdown(todos)
        return await rewrite_script(ctx, task_name, uri, markdown_content)
    
    
    @mcp.tool(description="""
        Rewrite an entire file in the remote project workspace using the full new content.

        For Godot-oriented tasks, treat this as a FALLBACK edit tool.
        Use it when modify_script is unsuitable or failed due to matching ambiguity.

        Use this tool when the target file needs a full replacement, when partial
        text replacement is too fragile, or when a previous incremental edit failed.
        
        Args:
            script_name: Name of the file to rewrite (for example "player.gd", "main.tscn", "settings.json"),required.
            code: New full file content to replace the entire file,required, content cannot be empty.
            task_name: {{task_name_prompt}},required
            
        Returns:
            Dict[str, Any]: {
                "success": bool,
                "message": str,
                "data": Any
            }
        """)
    async def rewrite_script(
        ctx: Context,
        task_name: str,
        script_name: str,
        code: str
    ) -> Dict[str, Any]:

        try:
            # Get canvas_id for project isolation
            canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
            
            # Validate parameters
            if not script_name:
                return {
                    "success": False,
                    "message": "Script name parameter is required",
                    "data": {"error_type": "missing_parameter", "parameter": "script_name"}
                }
            
            if not code or not code.strip():
                return {
                    "success": False,
                    "message": "Code parameter is required and cannot be empty or whitespace only",
                    "data": {"error_type": "missing_parameter", "parameter": "code"}
                }

            # --- Route to env service if enabled ---
            if config.threejs.use_env and config.threejs.env_service_url:
                result = await env_client.scripts_rewrite(ctx, script_name, code)
                logger.info(f"rewrite_script via env: {script_name}, success={result.get('success')}")
                return result

            # --- Original S3 flow (use_env=False) ---
            # Get S3 storage instance with canvas_id
            s3_storage = await get_s3_storage(canvas_id)
            
            # Check if file exists and get old content length
            file_existed = False
            old_code_length = 0
            exists, _, metadata = await s3_storage.file_exists(script_name)
            if exists:
                file_existed = True
                old_code_length = metadata.get("content_length", 0)
            
            # Upload file to S3 (will overwrite if exists)
            success, message, data = await s3_storage.upload_file(
                file_name=script_name,
                content=code,
                metadata={"modified_by": "rewrite_script_tool"}
            )
            
            if success:
                logger.info(f"Script '{script_name}' rewritten in S3 (existed: {file_existed})")
                
                return {
                    "success": True,
                    "message": message,
                    "data": {
                        "script_name": script_name,
                        "s3_uri": data["s3_uri"],  # type: ignore
                        "s3_key": data["s3_key"],  # type: ignore
                        "file_existed": file_existed,
                        "old_code_length": old_code_length,
                        "new_code_length": data["content_length"],  # type: ignore
                        "operation": "rewrite"
                    }
                }
            else:
                logger.error(f"Failed to rewrite script '{script_name}': {message}")
                return {
                    "success": False,
                    "message": message,
                    "data": {"error_type": "upload_failed", "script_name": script_name}
                }
            
        except Exception as e:
            logger.error(f"Error in rewrite_script: {str(e)}")
            return {"success": False, "message": f"Python error: {str(e)}", "data": None}

