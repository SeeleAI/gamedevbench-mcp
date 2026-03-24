import base64
from copy import deepcopy
import json
import logging
import textwrap
import time
from dataclasses import asdict, dataclass
from typing import Any
import asyncio

from openai import AsyncOpenAI

from llm.open_ai_helper import OpenAIHelper
from remote_config import get_config_by_class
from remote_config.schemas.llm.litellm_config import LiteLLMConfig, LiteLLMConfigItem
from remote_config.schemas.llm.screenshots_prompt_config import ScreenshotsPromptConfig
from util.s3_util import S3Client
from util.aiohttp_util import get_aiohttp_url_response
from llm.openai_config import OpenAIConfig

logger = logging.getLogger(__name__)


"""
bash -c '
  base64_image=$(base64 -i "Path/to/agi/image.jpeg");
  curl "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer GEMINI_API_KEY" \
    -d "{
      \"model\": \"gemini-2.0-flash\",
      \"messages\": [
        {
          \"role\": \"user\",
          \"content\": [
            { \"type\": \"text\", \"text\": \"What is in this image?\" },
            {
              \"type\": \"image_url\",
              \"image_url\": { \"url\": \"data:image/jpeg;base64,${base64_image}\" }
            }
          ]
        }
      ]
    }"
'


"""


ENABLE_LLM_ANALYZE_SCREENSHOT = True


@dataclass
class InvokeInputItem:
    input_text: str
    base64_img: str
    objects_info: str

    def to_dict(self):
        return asdict(self)


async def invoke_llm_with_litellm_openai(
    system_prompt: str,
    text_prompt: str,
    base64_img: str,
    litellm_config: LiteLLMConfigItem,
    trace_id: str | None,
) -> dict[str, Any]:
    url = f"{litellm_config.endpoint}{litellm_config.default_path}"
    logger.info(f"url: {url}")
    logger.info(f"model: {litellm_config.model}")

    # 构建图片 URL，如果 base64_img 不包含 data URI 前缀则添加
    image_url = base64_img
    if base64_img and not image_url.startswith("data:image/"):
        image_url = f"data:image/jpeg;base64,{base64_img}"

    # 使用 openai sdk
    # client = AsyncOpenAI(
    #     api_key=litellm_config.api_key,
    #     base_url=litellm_config.endpoint,
    #     timeout=60,
    # )

    openai_config = OpenAIConfig(
        model=litellm_config.model,
        api_key=litellm_config.api_key,
        endpoint=litellm_config.endpoint,
        # 原为 vertex/gemini xxx, 只上报gemini xxx
        model_name=litellm_config.model.split("/")[-1],
    )

    # 使用 OpenAIHelper
    openai_helper = OpenAIHelper(
        config=openai_config,
        trace_id=trace_id or "test_trace_id",
        use_json=False,
        system_prompt=system_prompt,
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                },
            ],
        },
    ]

    to_print_messages = deepcopy(messages)
    to_print_messages[-1]["content"][-1].pop("image_url")

    logger.info(
        f"invoke_llm_with_litellm_openai messages: {json.dumps(to_print_messages, indent=4, ensure_ascii=False)}"
    )

    start_time = time.time()

    infer_dicts = {
        "max_tokens": 16384,
        "extra_body": {
            "extra_body": {
                "google": {
                    "thinking_config": {
                        "thinking_level": "low",
                        "include_thoughts": True,
                    }
                }
            }
        },
    }
    raw_response = await openai_helper.send_request_with_infer_dict(
        messages, infer_dicts, channel="google_genai"
    )

    full_content = OpenAIHelper.get_resp_content(raw_response)

    # collected_content = []
    # logger_flag = False
    # async for chunk in gen:
    #     if chunk.choices and chunk.choices[0].delta.content:
    #         if not logger_flag:
    #             logger.info(f"received first chunk: {chunk}")
    #             logger_flag = True
    #         collected_content.append(chunk.choices[0].delta.content)

    # full_content = "".join(collected_content)
    end_time = time.time()

    logger.info(f"Invoke LLM finished. Duration: {end_time - start_time:.2f}s")
    return {"content": full_content}


async def biz_analyze_screenshot(
    input_items: InvokeInputItem,
    litellm_config: LiteLLMConfigItem,
    trace_id: str | None,
) -> dict[str, Any]:
    await get_config_by_class(ScreenshotsPromptConfig)
    system_prompt_current = ScreenshotsPromptConfig.current()
    if not system_prompt_current:
        raise ValueError("system_prompt_current is not found")
    system_prompt = system_prompt_current.text

    model_current = litellm_config.model

    if not model_current:
        raise ValueError("model_current is not found")

    text_prompt = textwrap.dedent(
        f"""
        <task>
        Task Title:
        {input_items.input_text}
        </task>

        <screenshot>
        See base64 message body
        </screenshot>

        <objects_info>
        {input_items.objects_info}
        </objects_info>
        """
    )

    content = await invoke_llm_with_litellm_openai(
        system_prompt, text_prompt, input_items.base64_img, litellm_config, trace_id
    )
    logger.info(f"content: {content}")
    return {"content": content or ""}


async def get_litellm_config() -> LiteLLMConfig:
    """
    获取LiteLLM配置。

    Returns:
        LiteLLMConfig配置对象

    Raises:
        ValueError: 如果配置未找到
    """
    await get_config_by_class(LiteLLMConfig)
    litellm_configs = LiteLLMConfig.current()
    if not litellm_configs:
        raise ValueError("litellm_config is not found")
    return litellm_configs


async def extract_blender_screenshot_data(result: dict) -> tuple[str, str, dict | None]:
    """
    从Blender响应结果中提取截图相关数据。

    如果URL存在但base64图片不存在，会根据URL特征选择合适的下载方式：
    - 如果URL包含"private"关键字，使用S3Client的加签下载方式
    - 如果URL包含"kokokeepall"关键字，使用直接HTTP下载方式
    - 其他情况使用S3Client的加签下载方式

    Args:
        result: Blender返回的result字典

    Returns:
        元组包含: (url, base64Image, screen_objects_info)
    """
    # Blender可能返回image_url或url
    url = result.get("image_url") or result.get("url", "")
    # Blender可能返回base64Image或base64_image
    base64Image = result.get("base64Image") or result.get("base64_image", "")

    # 如果URL存在但base64图片不存在，从URL下载图片
    if url and not base64Image:
        try:
            logger.info(f"Downloading image from URL: {url}")

            # 根据URL内容选择下载方式
            if "private" in url:
                # 私有S3文件，使用加签URL下载
                logger.info(f"Using presigned URL download for private S3 file: {url}")
                base64Image = await S3Client().get_s3_url_image_base64_async(url)
            elif "kokokeepall" in url:
                # 公开Azure Blob或公开URL，使用直接下载
                logger.info(f"Using direct download for public URL: {url}")
                base64Image = await download_image_as_base64(url)
            else:
                # 默认使用S3Client的加签下载方式
                logger.info(f"Using default S3 download method for: {url}")
                base64Image = await S3Client().get_s3_url_image_base64_async(url)

        except Exception as e:
            logger.warning(f"Failed to download image from URL {url}: {e}")
            # 继续执行，base64Image保持为空字符串

    # Blender可能返回screen_objects_info或objects_info
    screen_objects_info: dict | None = result.get("screen_objects_info") or result.get(
        "objects_info", None
    )
    return url, base64Image, screen_objects_info


async def download_image_as_base64(image_url: str, timeout: float | None = None) -> str:
    """
    从URL下载图片并转换为base64编码。

    Args:
        image_url: 图片的URL地址
        timeout: 超时时间（秒），默认60秒（图片通常较小，但网络可能较慢）

    Returns:
        base64编码的图片字符串（不包含data URI前缀）

    Raises:
        Exception: 如果下载失败
    """
    # 图片下载默认60秒超时，比小文件下载的30秒稍长，但比大文件下载的120秒短
    if timeout is None:
        timeout = 60.0

    try:
        # 使用通用的aiohttp工具函数下载图片
        image_data = await get_aiohttp_url_response(image_url, timeout=timeout)
        # 转换为base64编码
        base64_str = base64.b64encode(image_data).decode("utf-8")
        logger.info(
            f"Successfully downloaded and converted image to base64, size: {len(base64_str)} chars"
        )
        return base64_str
    except Exception as e:
        logger.error(f"Error downloading image from {image_url}: {e}")
        raise


async def analyze_screenshot_with_vision(
    base64Image: str,
    screen_objects_info: dict | None,
    task_name: str | None,
    trace_id: str | None,
) -> dict[str, Any]:
    """
    使用视觉理解模型分析截图。

    无论是否有物体信息，都会调用视觉理解来补充信息。

    Args:
        base64Image: base64编码的图片数据
        screen_objects_info: 屏幕物体信息字典，可能为None
        task_name: 任务名称，可能为None

    Returns:
        包含分析结果的字典，格式: {"success": bool, "content": str, "llm_analyzed_info": str}
        - success: 分析是否成功（True/False）
        - content: 分析内容或错误信息
        - llm_analyzed_info: 失败时的详细信息
    """
    if not ENABLE_LLM_ANALYZE_SCREENSHOT:
        return {
            "success": False,
            "content": "llm analyze screenshot is disabled",
            "llm_analyzed_info": "LLM分析截图功能已禁用",
        }

    # 将物体信息转换为JSON字符串，如果没有则为空字符串
    screen_objects_info_str = ""
    if screen_objects_info and isinstance(screen_objects_info, dict):
        screen_objects_info_str = json.dumps(screen_objects_info)
        logger.info(f"screen_objects_info: {screen_objects_info}")

    start_time = time.time()
    # LLM API 调用的超时时间（与 AsyncOpenAI 客户端的 timeout=60 保持一致）
    LLM_API_TIMEOUT = 60.0  # 60秒

    try:
        # 获取LiteLLM配置（这个配置在 nacos 的 litellm_config.json 中，这里选择gemini flash latest 模型）
        litellm_configs = await get_litellm_config()
        litellm_config_item = litellm_configs.configs[2]

        # 调用视觉理解分析截图，超时时间与 AsyncOpenAI 客户端保持一致（300秒）
        # 注意：AsyncOpenAI 客户端已经设置了 timeout=300，这里使用 asyncio.wait_for 作为额外的保护层
        llm_analyze_result: dict = await asyncio.wait_for(
            biz_analyze_screenshot(
                InvokeInputItem(
                    input_text=task_name or "",
                    base64_img=base64Image,
                    objects_info=screen_objects_info_str,
                ),
                litellm_config_item,
                trace_id,
            ),
            timeout=LLM_API_TIMEOUT,
        )

        end_time = time.time()
        logger.info(f"llm_analyze_result time: {end_time - start_time:0.2f}s")

        # 成功时返回结构
        return {
            "success": True,
            "content": llm_analyze_result.get("content", ""),
            "llm_analyzed_info": "",
        }

    except asyncio.TimeoutError:
        # 超时处理
        end_time = time.time()
        timeout_msg = f"视觉理解分析超时（{end_time - start_time:0.2f}s），请根据截图和物体信息自行判断分析任务"
        logger.warning(f"llm_analyze_result timeout: {timeout_msg}")

        return {
            "success": False,
            "content": timeout_msg,
            "llm_analyzed_info": f"分析超时（超过{LLM_API_TIMEOUT}秒），耗时：{end_time - start_time:0.2f}秒。建议参考截图和物体信息进行任务分析。",
        }

    except Exception as e:
        # 其他异常处理
        end_time = time.time()
        error_msg = f"视觉理解分析失败：{str(e)}"
        logger.error(f"llm_analyze_result error: {error_msg}")

        return {
            "success": False,
            "content": "invoke_llm fail, reference the screenshot and objects info to analyze the task",
            "llm_analyzed_info": f"分析失败：{error_msg}，耗时：{end_time - start_time:0.2f}秒。建议参考截图和物体信息进行任务分析。",
        }


# 单测
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s,%(msecs)03d] [%(levelname)s] [%(name)s:%(funcName)s] [%(filename)s:%(lineno)d] [%(message)s]",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    input_text = "检查武器是否正确绑定到手部骨骼"
    local_img_path = "/Users/saigyoujiyuyuko/Downloads/20251119-202625.jpg"
    base64_img = base64.b64encode(open(local_img_path, "rb").read()).decode("utf-8")
    # objects_info =
    obj_info_str = '{"name": "Scene", "object_count": 14, "objects": [{"name": "Genesis8Male", "type": "ARMATURE", "world_location": [0.0, 0.0, 0.0], "parent": "DazModel", "children_count": 3}, {"name": "Warrior", "type": "MESH", "world_location": [-0.0, -0.0, 0.0], "parent": "Genesis8Male", "children_count": 0}, {"name": "DazModel", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": "DazModel.001", "children_count": 1}, {"name": "DazModel.001", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": "DazModel.002", "children_count": 1}, {"name": "DazModel.002", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": null, "children_count": 1}, {"name": "Empty", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": null, "children_count": 0}, {"name": "Spear", "type": "MESH", "world_location": [-0.52, -0.02, 0.88], "parent": "Genesis8Male", "children_count": 0}, {"name": "72_model", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": null, "children_count": 1}, {"name": "Hylian_Shield.fbx", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": "72_model", "children_count": 1}, {"name": "RootNode", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": "Hylian_Shield.fbx", "children_count": 1}, {"name": "Object_3", "type": "ARMATURE", "world_location": [0.0, 0.0, 0.0], "parent": "RootNode", "children_count": 1}, {"name": "Object_5", "type": "EMPTY", "world_location": [0.0, 0.0, 0.0], "parent": "Object_3", "children_count": 0}, {"name": "Shield", "type": "MESH", "world_location": [0.25, -0.01, 0.6], "parent": "Genesis8Male", "children_count": 0}, {"name": "Camera", "type": "CAMERA", "world_location": [3.0, -3.0, 1.5], "parent": null, "children_count": 0}], "materials_count": 42}'

    async def main():
        await get_config_by_class(LiteLLMConfig)
        litellm_configs = LiteLLMConfig.current()
        if not litellm_configs:
            raise ValueError("litellm_config is not found")
        input_items = InvokeInputItem(
            input_text=input_text, base64_img=base64_img, objects_info=obj_info_str
        )

        trace_id = "test_trace_id"

        _result = await biz_analyze_screenshot(
            input_items, litellm_configs.configs[2], trace_id
        )
        # print(result)

    asyncio.run(main())
