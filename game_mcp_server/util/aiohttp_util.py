import logging
from typing import AsyncIterator

import aiohttp

logger = logging.getLogger(__name__)


async def get_aiohttp_url_response(url: str, timeout: float | None = None) -> bytes:
    """
    从URL异步下载文件内容。
    
    Args:
        url: 文件URL地址
        timeout: 超时时间（秒），默认30秒
        
    Returns:
        文件的二进制内容
        
    Raises:
        Exception: 如果下载失败（HTTP状态码不为200或其他错误）
    """
    if timeout is None:
        timeout = 30.0
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to get url: HTTP {resp.status}")
            return await resp.read()


async def download_file_in_chunks(url: str, timeout: float | None = None, chunk_size: int = 8192) -> AsyncIterator[bytes]:
    """
    从URL异步流式下载文件内容（分块）。
    
    Args:
        url: 文件URL地址
        timeout: 超时时间（秒），默认30秒
        chunk_size: 每次读取的块大小（字节），默认8192
        
    Yields:
        文件的二进制块数据
        
    Raises:
        Exception: 如果下载失败（HTTP状态码不为200或其他错误）
    """
    if timeout is None:
        timeout = 30.0
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to get url: HTTP {resp.status}")
            async for chunk in resp.content.iter_chunked(chunk_size):
                if chunk:
                    yield chunk