from typing import Dict, Any

from mcp.server import FastMCP
from mcp.server.fastmcp import Context

from ..task_tool import _get_task_result_iml


def register_task_tools(mcp: FastMCP) -> None:
    @mcp.tool(description="""Check whether an asset generation or asset edit job has completed.

        Use this tool after generate_assets, generate_image, or generate_sprite when you need
        to poll for completion before consuming the produced asset in the current game task.

        Parameters:
        - asset_id: The asset identifier saved/returned when the generation job was created.
        - task_name:  {{task_name_prompt}}

        Returns:
        - success: True/False — whether the call itself succeeded. When False, see message for details.
        - message: Present when success is False; contains error information.
        - status: Present only while the job is not completed. Possible values:
          - running: the workflow is still executing
          - succeeded: the workflow completed successfully
          - failed: the workflow execution failed
        - public_url: Present when status is "completed" and the job succeeded. Publicly accessible URL for the generated asset.

        Polling Behavior:
        - This is a polling-style API. Only proceed to subsequent steps once the job is no longer
          in the "running" state (i.e., when it is "succeeded", "failed").
        - While running, the method returns {"success": True, "status": "running"}.
        - After completion, the method returns the workflow's raw outputs. Use these to continue the
          next steps in your pipeline
        """)
    async def poll_generation_job_status(ctx: Context, asset_id: str, task_name: str = None, ) -> Dict[str, Any]:
        # 调用通用函数，传入 return_public_url=True
        return await _get_task_result_iml(ctx, asset_id, return_public_url=True)
