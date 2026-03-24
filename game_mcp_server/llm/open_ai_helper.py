import asyncio
import logging
import random
import time
from typing import AsyncGenerator

from openai import NOT_GIVEN, AsyncStream, RateLimitError, AsyncOpenAI
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from python_http_cuda_rpc.util.report_types import create_llm_info

from llm.openai_config import OpenAIConfig, azure_gpt5_mini_config
from util.report_util import now_time, report_llm

logger = logging.getLogger(__name__)


class OpenAIHelper:
    def __init__(
        self, config: OpenAIConfig, trace_id: str, system_prompt="", use_json=True
    ):
        self.config = config
        self.trace_id = trace_id
        self.system_prompt = system_prompt
        self.chat_text = ""
        self.use_json = use_json

    def set_text(self, text):
        self.chat_text = text

    async def send_request(self):
        req_data = self._req_data_gen()
        resp_data = await self._send_request(req_data)
        return resp_data

    async def send_request_with_infer_dict(
        self, messages: list[dict], infer_dict: dict, channel: str = "openai"
    ):
        resp_data = await self._send_request(
            messages, infer_dict=infer_dict, channel=channel
        )
        return resp_data

    def _req_data_gen(self):
        user_content = []
        if self.chat_text:
            user_content.append({"type": "text", "text": self.chat_text})
        req_data = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        logger.info(f"req_data user_content:{self.chat_text}")
        return req_data

    async def _send_request(
        self, req_msg, retry_time=2, infer_dict=None, channel="openai"
    ):
        start_time = time.time()
        try:
            start_report_time = now_time()
            client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.endpoint,
            )
            response = await client.chat.completions.create(
                model=self.config.model,
                response_format={"type": "json_object"} if self.use_json else NOT_GIVEN,
                messages=req_msg,
                **infer_dict if infer_dict else {},
            )

            # fire-and-forget reporting in background thread
            asyncio.create_task(
                asyncio.to_thread(
                    report_llm,
                    self.trace_id,
                    start_report_time,
                    create_llm_info(
                        channel=channel,
                        model=self.config.model_name,
                        input_tokens=response.usage.prompt_tokens,
                        output_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                    ),
                )
            )
        except RateLimitError as e:
            logger.warning(f"_send_request RateLimitError {e}")
            if retry_time > 0:
                await asyncio.sleep(random.randint(2, 10))
                return await self._send_request(req_msg, retry_time - 1)
            else:
                raise e

        logger.info(
            f"fix response total_tokens:{response.usage.total_tokens}"
            f" cos:{time.time() - start_time} req_msg:{self.system_prompt} {self.chat_text}"
        )
        return response

    async def send_request_stream(
        self, messages: list[dict], infer_args: dict
    ) -> AsyncStream[ChatCompletionChunk]:
        client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.endpoint,
        )
        gen = await client.chat.completions.create(
            model=self.config.model, messages=messages, stream=True, **infer_args
        )
        return gen

    @staticmethod
    def get_resp_content(response) -> str:
        return response.choices[0].message.content


if __name__ == "__main__":
    h = OpenAIHelper(
        config=azure_gpt5_mini_config,
        trace_id="",
        use_json=False,
        system_prompt="""1. 需要分析动画需求，将需求处理成合适的动作描述文本
            - 文本动作描述中需要排除：微动作（如呼吸模式、眨眼、眨眼、轻微颤抖）、面部表情（如微笑、愤怒、哭泣、脸颊描述）；仅保留显著的身体动作（如肢体运动、姿态变化、触觉互动）
            - 文本动作描述的语言必须是英文
        2. **单个动画需求**中动作描述文本的类型：
motion_text：：宏观概括，是高度概括性的单一动作描述，代表主导动作或整体动作意图。
如果动画需求是Idle动作，遵循Idle动作规范: 前置修饰 + idle 或 idle + 进行式动作（可带工具/对象）， 动作描述应精简到1-5个词以内， 例如 breathing idle, zombie idle, idle hoding gun, idle hoding sword, ninja idle, rifle idle, drunk idle, sword and shield idle, ready idle, fight idle, idle aiming with gun, ...
如果动画需求是walk/run/jump等RootMotion动作，遵循RootMotion动作规范:动作规范：前置修饰 + walk 或 walk + 进行式修饰（可带方向/武器）或 walk like a + 简单人设， 动作描述应精简到1-5个词以内， 例如 casual walk, zombie run, ninja walk, rifle run, drunk walk, sword and shield walk, walk aiming with gun, walk holding sword, walk scanning, walk backward, walk sideways, female walk, happy walk, happy run, happy jump, walk like a robot， run like a monkey
如果动画需求是其他动作(Idle/RootMotion以外的动作)，遵循Perform动作规范：如果在1个动画需求中是多个连续动作，则将连续动作需合并为1个通用的日常描述，动作描述以"The person"开头，主动动作使用格式："The person is [verb-ing] [object]"，被动动作使用格式"The person is being [verb]"， 专注于动作的核心目的和整体性质。""",
    )
    h.set_text("jumping motion")
    print(asyncio.run(h.send_request()))
