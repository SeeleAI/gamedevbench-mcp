#!/usr/bin/env python3
"""
Centralized prompt creation for gamedev benchmark solvers.

This module provides unified prompt creation functions used by all solver implementations,
ensuring consistency across different agents.
"""

import json
from typing import Optional

EDIT_FLOW_GUIDANCE_LOCAL = """

<edit_flow>
Code modifications must follow this workflow:

1. Extract key entities from the task/context:
   - function name, component/node name, error message, variable/resource name, file hint.
2. Infer the likely scope (modules/files) from those entities.
3. Search before editing:
   - Prefer: `rg "keywords"` (or `grep "keywords"` if rg is unavailable).
   - Goal: find relevant file paths and line locations.
4. Read only the relevant files/sections to understand current logic and data format.
5. If new keywords/references appear while reading:
   - Return to Step 3 and continue search-read iterations.

Termination conditions (all required):
- You clearly know which files must be modified.
- You clearly know the exact locations to modify.
- You have checked whether the change may affect other modules/files.

Prohibited behaviors:
- Do not guess paths and edit directly without search + read.
- Do not read many unrelated files at once.
- Do not start write/replace/modify operations before the target location is confirmed.
</edit_flow>
"""

EDIT_FLOW_GUIDANCE_MCP_PREFERRED = """

<edit_flow>
Code modifications should follow this workflow:

1. Extract key entities from the task/context:
   - function name, component/node name, error message, variable/resource name, file hint.
2. Infer the likely scope (modules/files) from those entities.
3. Choose search strategy before editing:
   - If target file/path is unclear, use available MCP search tools or local `rg/grep` to locate candidates first.
   - If target file/path is already explicit in the task, you may read that file directly first, then run additional search only when needed.
4. Read only the relevant files/sections to understand current logic and data format:
   - Choose the most suitable available read tool based on current task context.
5. If new keywords/references appear while reading:
   - Return to Step 3 and continue search-read iterations.
6. Perform edits:
   - Use MCP edit tools only by their exact runtime-exposed names when they improve reliability for the current task context.
   - Use local editing tools when local verification/execution is required or MCP state is not authoritative.

Termination conditions (all required):
- You clearly know which files must be modified.
- You clearly know the exact locations to modify.
- You have checked whether the change may affect other modules/files.

Prohibited behaviors:
- Do not guess paths and edit directly without search + read.
- Do not read many unrelated files at once.
- Do not start write/replace/modify operations before the target location is confirmed.
</edit_flow>
"""


def load_task_config() -> Optional[dict]:
    """Load task configuration from task_config.json in current directory.

    Returns:
        Parsed task configuration dict, or None if loading fails
    """
    try:
        with open("task_config.json", "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def create_task_prompt(
    config: dict,
    use_runtime_video: bool = False,
    use_mcp: bool = False,
    include_edit_flow: bool = True,
) -> str:
    """Create minimal task prompt with just the instruction.

    Args:
        config: Task configuration dict containing 'instruction' field
        use_runtime_video: Whether to append Godot runtime video instructions
        use_mcp: Whether to include MCP tool references
        include_edit_flow: Whether to append edit-flow guidance block

    Returns:
        The instruction text with optional runtime video and MCP guidance
    """
    try:
        if not config or "instruction" not in config:
            raise ValueError("Invalid config: 'instruction' field missing")
    except Exception as e:
        print(f"Error creating task prompt: {e}")
        return ""
    instruction = config.get("instruction")
    
    instruction += "\n You must complete the full task without any further assistance."
    instruction += "\n Godot is installed and you can run godot using the `godot` command. It is recommended to run this with a timeout (e.g., `timeout 10 godot` for 10 second timeout) to prevent hanging."
    instruction += "\n Use available tools and runtime checks to verify changes with concrete evidence."

    if use_runtime_video:
        runtime_guidance = """
    - You can run the game and get an image with `godot --path . --quit-after 1
    --write-movie output.png`.
    - You can save a movie file as avi instead with `timeout 60s godot --path . --quit-after 60 --write-movie output.avi`. This is a 1 second or 60 frame video. You can adjust as necessary.
    - It is very important that you ensure godot closes after running, or else the task will hang indefinitely.
    - You should use the video or images to verify that your changes worked as expected.
    """
        instruction += runtime_guidance

    if use_mcp:
        mcp_guidance = """

You have access to an external MCP (Model Context Protocol) server.

MCP usage rules:
- At the beginning, discover available MCP tools first.
- Only call MCP tools that are actually listed as available.
- Never invent tool names (for example: `screenshot_game`).
- Use MCP tools when they improve certainty or reduce manual work, but do not optimize for MCP call count.
- Local task workspace deliverables are authoritative for completion; MCP state alone is not sufficient.
- Choose tools based on task relevance, expected information gain, and execution reliability.

When to use MCP tools:
- Before starting work: collect task-relevant context if MCP tools can provide it.
- During implementation: use MCP tools when they reduce uncertainty or avoid assumptions.
- If you modify files via MCP, verify the same target paths in the local workspace before claiming completion.
- After making changes: use local file checks and/or Godot runtime checks for objective verification.

Important:
- The game directory is the current directory (`./`) unless a tool explicitly requires another path
- If an MCP call fails, try another relevant MCP tool before switching to pure file editing.
- Do not mark the task complete until all required files and key properties from the instruction are confirmed in local workspace files.
"""
        instruction += mcp_guidance

    if include_edit_flow:
        instruction += EDIT_FLOW_GUIDANCE_MCP_PREFERRED if use_mcp else EDIT_FLOW_GUIDANCE_LOCAL

    return instruction


def create_system_prompt(use_mcp: bool = False) -> str:
    """Create system prompt for Godot game development tasks.

    Args:
        use_mcp: Deprecated - MCP guidance is now in create_task_prompt

    Returns:
        System prompt string
    """
    guidance = EDIT_FLOW_GUIDANCE_MCP_PREFERRED if use_mcp else EDIT_FLOW_GUIDANCE_LOCAL
    return "You are a Godot game development expert.\n" + guidance
