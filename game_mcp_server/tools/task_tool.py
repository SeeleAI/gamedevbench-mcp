import asyncio
import json
import logging
import time
from typing import Dict, Any

from mcp.server import FastMCP
from mcp.server.fastmcp import Context

from config import config
from util.asset_report import report_generated_asset
from util.asset_util import get_target_property, update_property_item, transform_data_url
from util.context_util import get_context_canvas_id
from util.dify_client import DifyClient

logger = logging.getLogger(__name__)


def register_task_tools(mcp: FastMCP) -> None:
    @mcp.tool(description="""Check generation or edit asset job is completed.

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

        Polling Behavior:
        - This is a polling-style API. Only proceed to subsequent steps once the job is no longer
          in the "running" state (i.e., when it is "succeeded", "failed").
        - While running, the method returns {"success": True, "status": "running"}.
        - After completion, the method returns the workflow's raw outputs. Use these to continue the
          next steps in your pipeline
        """)
    async def poll_generation_job_status(ctx: Context, asset_id: str, task_name: str = None, ) -> Dict[str, Any]:
        
        return await _get_task_result_iml(ctx, asset_id)


async def _get_task_result_iml(ctx: Context, asset_id: str, return_public_url: bool = False) -> Dict[str, Any]:
    canvas_id = get_context_canvas_id(ctx) or config.test_canvas_id
    # 1) Find property
    try:
        prop = await get_target_property(canvas_id, asset_id)
    except Exception as e:
        return {"success": False, "message": str(e)}
    if not prop:
        return {"success": False, "message": f"asset_id not found: {asset_id}"}
    data = prop.get("data") or {}
    workflow_run_id = data.get("workflow_run_id")
    if not workflow_run_id:
        return {"success": False, "message": f"workflow_run_id not found for asset_id: {asset_id}"}

    use_api_key = data.get("api_key")
    if use_api_key is None:
        logger.warning(f"not find use api data is {data}")
        return {"success": False, "message": f"get task info fail asset_id: {asset_id}"}
    estimated_time = data.get("estimated_time", 300)
    first_check_result = await _check_workflow_info_and_save(use_api_key, workflow_run_id, canvas_id,
                                                             estimated_time * 2, return_public_url)
    logger.info(f"first_check_result:{first_check_result}")
    if not first_check_result.get("success"):
        return first_check_result
    status = first_check_result.get("status")
    if status != "running":
        return first_check_result

    # 当状态为 running 时，每 10 秒检查一次，最多检查 20 次
    attempts = 0
    last_result = first_check_result
    while attempts < 20:
        await asyncio.sleep(10)
        current = await _check_workflow_info_and_save(use_api_key, workflow_run_id, canvas_id, estimated_time * 2, return_public_url)
        last_result = current
        if not current.get("success"):
            return current
        if current.get("status") != "running":
            return current
        attempts += 1

    # 超过最大次数仍为 running，直接返回当前结果
    return last_result


async def _check_workflow_info_and_save(use_api_key: str, workflow_run_id: str, canvas_id: str, timeout: int, return_public_url: bool = False):
    try:
        client = DifyClient(api_key=use_api_key, canvas_id=canvas_id)
        status_info = await client.get_workflow_status(workflow_run_id)
        if not status_info.get("success"):
            return status_info
        status = status_info.get("data", {}).get("status")
        logger.info(f"{workflow_run_id} current status: {status}")
        if "running" == status:
            # 超时处理
            created_at = status_info.get("data", {}).get("created_at")
            if created_at and int(time.time()) - created_at > timeout:
                return {"success": False, "status": "timeout"}
            return {"success": True, "status": "running"}
        if "succeeded" == status or "partial-succeeded" == status:
            outputs = status_info.get("data", {}).get("outputs")
            save_info = await _save_result(canvas_id, outputs, workflow_run_id)
            if not save_info.get("success", True):
                return save_info
            result = {"success": True, "status": "completed"}
            if return_public_url:
                # ThreeJS环境：返回public_url
                property_doc = save_info.get("property_doc", {})
                data_dict = property_doc.get("data", {}) or {}
                public_url = (data_dict.get("model_url_public") or 
                             data_dict.get("fbx_url_public") or 
                             data_dict.get("sfx_url_public") or 
                             data_dict.get("bgm_url_public") or 
                             data_dict.get("image_url_public") or 
                             data_dict.get("audio_url_public"))
                if public_url:
                    result["public_url"] = public_url
            return result
        return {"success": False, "status": "failed",
                "message": f"task failed status:{status} error:{status_info.get('error')}"}
    except Exception as e:
        last_error = {"success": False, "message": f"query failed: {e}"}
        return last_error


async def _save_result(canvas_id: str, outputs: str, workflow_run_id: str):
    result_output = json.loads(outputs).get("output")
    result_output_obj = json.loads(result_output)
    property_doc = result_output_obj.get("property_doc")
    if not property_doc:
        return {"success": False, "message": "property_doc not found in workflow output"}
    property_doc["workflow_run_id"] = workflow_run_id
    property_doc["status"] = "completed"
    # 确保 data 字段存在，transform_data_url 会原地修改它，添加 *_public 字段
    if "data" not in property_doc or property_doc["data"] is None:
        property_doc["data"] = {}
    await transform_data_url(property_doc["data"])
    update_result = await update_property_item(canvas_id, property_doc)
    await report_generated_asset(canvas_id, property_doc)
    # 返回 update_result 并包含 property_doc，以便后续提取 public_url
    # 确保返回的是字典，并包含 property_doc
    if not isinstance(update_result, dict):
        update_result = {"success": True}
    update_result["property_doc"] = property_doc
    return update_result


if __name__ == "__main__":
    print(asyncio.run(_get_task_result_iml(None, "red_apple")))
    # 9bd32748-00e3-4f09-9df3-ccb8392f0b67
