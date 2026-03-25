"""Convert private asset URL to public URL tool for MCP."""
import logging
import asyncio
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP, Context

from util.s3_util import S3Client, PUBLIC_BUCKET

logger = logging.getLogger(__name__)

# 支持的文件后缀（小写，用于验证）
# 支持的格式：图片格式（.jpg, .jpeg, .png, .gif, .webp, .bmp, .svg, .ico, .tiff, .tif）和3D模型格式（.glb, .fbx）
SUPPORTED_FILE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico', '.tiff', '.tif', '.glb', '.fbx'}


def _is_valid_s3_file_url(url: str) -> bool:
    """
    验证URL是否为有效的私有S3文件链接。
    
    要求：
    1. 必须以 s3:// 开头
    2. 文件后缀必须是支持的文件格式（.jpg, .jpeg, .png, .gif, .webp, .bmp, .svg, .ico, .tiff, .tif, .glb, .fbx）
    
    Args:
        url: 待验证的URL（标准S3格式：s3://bucket/key）
        
    Returns:
        bool: 如果符合条件返回True，否则返回False
    """
    if not url or not isinstance(url, str):
        return False
    
    # 必须是以 s3:// 开头的链接
    if not url.startswith("s3://"):
        return False
    
    # 提取文件扩展名（转换为小写进行比较）
    url_lower = url.lower()
    # 查找最后一个点号，获取扩展名
    last_dot_idx = url_lower.rfind('.')
    if last_dot_idx == -1:
        # 没有扩展名，不符合支持的格式要求
        return False
    
    # 确保点号后面有字符（不是以点结尾）
    if last_dot_idx >= len(url_lower) - 1:
        return False
    
    extension = url_lower[last_dot_idx:]
    return extension in SUPPORTED_FILE_EXTENSIONS


def register_convert_s3_file_url_tool(mcp: FastMCP):
    """Register the convert_s3_file_url tool with the MCP server."""
    
    @mcp.tool(description="""
        Convert a private asset S3 URL into a public accessible URL.
        
        This tool strictly validates the input parameter and ONLY supports the following file types:
        - Image formats: .jpg, .jpeg, .png, .gif, .webp, .bmp, .svg, .ico, .tiff, .tif
        - 3D model formats: .glb, .fbx
        
        IMPORTANT: This tool ONLY supports these file extensions. Any other file type will be returned unchanged.
        
        Validation rules:
        - Input must be a private S3 link (starts with s3:// and has one of the supported file extensions listed above)
        - If the input is NOT a valid S3 link with supported extension, the original URL is returned unchanged
        - If the input IS a valid S3 link with supported extension, it is converted to a public CDN URL
        
        Supported file extensions (exactly 12 types):
        .jpg, .jpeg, .png, .gif, .webp, .bmp, .svg, .ico, .tiff, .tif, .glb, .fbx
        
        Args:
            task_name: {{task_name_prompt}},required
            private_s3_url: Private asset S3 URL (must start with s3:// and have one of the supported file extensions),required
            
        Returns:
            Dict[str, Any]: {
                "success": bool,  # True if conversion succeeded or input was invalid (returned original), False on error
                "message": str,   # Operation result message
                "data": {
                    "original_url": str,      # Original input URL
                    "public_url": str,        # Converted public URL (or original URL if input was invalid)
                    "was_converted": bool     # True if conversion was performed, False if original URL was returned
                }
            }
        """)
    async def convert_s3_file_url(
        ctx: Context,
        task_name: str,
        private_s3_url: str
    ) -> Dict[str, Any]:
        
        try:
            # 参数验证
            if not private_s3_url or (isinstance(private_s3_url, str) and not private_s3_url.strip()):
                return {
                    "success": False,
                    "message": "private_s3_url parameter is required",
                    "data": {
                        "error_type": "missing_parameter",
                        "parameter": "private_s3_url"
                    }
                }
            
            # 严格验证：必须是s3://开头且是支持的文件后缀
            if not _is_valid_s3_file_url(private_s3_url):
                logger.info(
                    f"Input URL does not match S3 format (s3:// with supported file extension), returning original: {private_s3_url}"
                )
                # 不符合条件，直接返回原始URL
                return {
                    "success": True,
                    "message": "Input URL does not match S3 format with supported file extension, returning original URL",
                    "data": {
                        "original_url": private_s3_url,
                        "public_url": private_s3_url,
                        "was_converted": False
                    }
                }
            
            # 符合条件，执行URL转换
            logger.info(f"Converting private S3 file URL to public URL: {private_s3_url}")
            
            # 调用S3Client的URL转换方法（将私有S3链接转换为公有链接）
            # 使用 move_and_get_accessible_url，target_bucket 设为公有桶，使用默认 tag="game_asset"
            s3_client = S3Client()
            
            try:
                # 使用 asyncio.to_thread 在异步环境中调用同步方法
                public_url = await asyncio.to_thread(
                    s3_client.move_and_get_accessible_url,
                    private_s3_url,
                    PUBLIC_BUCKET
                )
                
                # 检查转换后的URL是否真的改变了（move_and_get_accessible_url 失败时会返回原始URL）
                if public_url == private_s3_url:
                    logger.warning(f"URL conversion returned original URL, conversion may have failed: {private_s3_url}")
                    return {
                        "success": False,
                        "message": "URL conversion failed: returned URL is same as original",
                        "data": {
                            "original_url": private_s3_url,
                            "public_url": private_s3_url,
                            "was_converted": False,
                            "error": "Conversion did not change URL"
                        }
                    }
                
                logger.info(f"Successfully converted S3 URL: {private_s3_url} -> {public_url}")
                
                return {
                    "success": True,
                    "message": "Successfully converted private S3 URL to public URL",
                    "data": {
                        "original_url": private_s3_url,
                        "public_url": public_url,
                        "was_converted": True
                    }
                }
                
            except Exception as conversion_error:
                logger.error(
                    f"Failed to convert S3 URL {private_s3_url}: {str(conversion_error)}",
                    exc_info=True
                )
                # 转换失败，返回原始URL（但标记为失败）
                return {
                    "success": False,
                    "message": f"Failed to convert S3 URL: {str(conversion_error)}",
                    "data": {
                        "original_url": private_s3_url,
                        "public_url": private_s3_url,
                        "was_converted": False,
                        "error": str(conversion_error)
                    }
                }
            
        except Exception as e:
            logger.error(f"Error in convert_s3_file_url: {str(e)}", exc_info=True)
            # 尝试安全地获取 original_url，避免 NameError
            original_url = None
            try:
                original_url = private_s3_url
            except NameError:
                pass
            return {
                "success": False,
                "message": f"Python error: {str(e)}",
                "data": {
                    "error_type": "internal_error",
                    "original_url": original_url
                }
            }
