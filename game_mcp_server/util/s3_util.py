import base64
import logging
import os
import tempfile
import time
import traceback
import urllib.parse
import uuid
from typing import Optional

import aioboto3
import boto3
from urllib.parse import urlparse
from botocore.exceptions import NoCredentialsError
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

from config import (
    S3_PRIVATE_ACCESS_KEY_ID,
    S3_PRIVATE_SECRET_ACCESS_KEY,
    S3_PRIVATE_REGION,
    S3_PUBLIC_ACCESS_KEY_ID,
    S3_PUBLIC_SECRET_ACCESS_KEY,
    S3_PUBLIC_REGION,
    S3_PUBLIC_BUCKET
)

logger = logging.getLogger(__name__)

_CDN_MAP = {
    # CDN -> static.seeles.ai mappings
    "https://d3vhd1f81y5p6c.cloudfront.net": "https://static.seeles.ai/data",
    "https://seelemedia.s3.amazonaws.com": "https://static.seeles.ai",
    "https://seelemedia.s3.us-east-1.amazonaws.com": "https://static.seeles.ai",
}

_ORIGIN_MAP = {
    # origin -> CDN mappings
    "https://seeleh5.blob.core.windows.net/kokokeepall": "https://static.seeles.ai/data",
    "https://seele-asset-public-1.s3.ap-southeast-1.amazonaws.com": "https://d3lzqljvieno0e.cloudfront.net",
}

PUBLIC_BUCKET = S3_PUBLIC_BUCKET  # Use config value


def _cdn_replace_host(url: str) -> str:
    """Replace known hosts to CDN/static hosts according to mapping rules."""
    if not url:
        return url
    for src, dst in _CDN_MAP.items():
        if url.startswith(src):
            new_url = url.replace(src, dst, 1)
            logger.info("CDN host replace: %s → %s", src, dst)
            return new_url
    for src, dst in _ORIGIN_MAP.items():
        if url.startswith(src):
            new_url = url.replace(src, dst, 1)
            logger.info("Origin host replace: %s → %s", src, dst)
            return new_url
    return url


def _cdn_replace_cdn(url: str) -> str:
    """Reverse replacement: map CDN/static hosts back to origin when possible."""
    if not url:
        return url
    # Reverse of _ORIGIN_MAP
    for origin, cdn in _ORIGIN_MAP.items():
        if url.startswith(cdn):
            new_url = url.replace(cdn, origin, 1)
            logger.info("CDN→Origin reverse replace: %s → %s", cdn, origin)
            return new_url
    # Reverse of _CDN_MAP
    for origin, cdn in _CDN_MAP.items():
        if url.startswith(cdn):
            new_url = url.replace(cdn, origin, 1)
            logger.info("CDN→Origin reverse replace: %s → %s", cdn, origin)
            return new_url
    return url


def _convert_cdn_to_s3_url(url: str) -> str:
    """Best-effort conversion of CDN/static URLs back to their original S3/Origin form.

    If no mapping applies, returns the original url.
    """
    converted = _cdn_replace_cdn(url)
    if converted != url:
        logger.info("convertCdnToS3Url: %s -> %s", url, converted)
    return converted


def _build_private_bucket_path(prefix: str, file_name: str) -> str:
    """Build path for private bucket with optional prefix."""
    if not prefix:
        return file_name
    return f"{prefix}/{file_name}"


def _parse_s3_url(url: str):
    """Parse an S3 URL (s3://bucket/key or https virtual/path style) into (bucket, key).

    Supports:
    - s3://bucket/key
    - https://bucket.s3.amazonaws.com/key
    - https://bucket.s3.<region>.amazonaws.com/key
    - https://s3.<region>.amazonaws.com/bucket/key (path-style)
    - https://s3.amazonaws.com/bucket/key (legacy path-style)
    """
    if not isinstance(url, str) or not url:
        raise ValueError("empty url")

    # s3://bucket/key
    if url.startswith("s3://"):
        rest = url[5:]
        if "/" not in rest:
            raise ValueError("invalid s3 url: missing key")
        bucket, key = rest.split("/", 1)
        if not bucket or not key:
            raise ValueError("invalid s3 url: missing bucket or key")
        return bucket, key

    # http(s) styles
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip('/')
    if not host:
        raise ValueError("invalid url: missing host")

    # Path-style: s3.<region>.amazonaws.com/bucket/key or s3.amazonaws.com/bucket/key
    if host == "s3.amazonaws.com" or host.startswith("s3.") or host.startswith("s3-"):
        bucket, sep, key = path.partition('/')
        if not sep or not bucket or not key:
            raise ValueError("invalid path-style s3 url: missing bucket/key")
        return bucket, key

    # Virtual-hosted style: bucket.s3.amazonaws.com or bucket.s3.<region>.amazonaws.com
    if ".s3.amazonaws.com" in host or ".s3." in host:
        bucket = host.split('.s3')[0]
        key = path
        if not bucket or not key:
            raise ValueError("invalid virtual-hosted s3 url: missing bucket/key")
        return bucket, key

    raise ValueError("unsupported s3 url host pattern")


# Use S3 credentials from config (imported above)
AWS_PRIVATE_ACCESS_KEY_ID = S3_PRIVATE_ACCESS_KEY_ID
AWS_PRIVATE_SECRET_ACCESS_KEY = S3_PRIVATE_SECRET_ACCESS_KEY
AWS_REGION_PRIVATE = S3_PRIVATE_REGION
AWS_PUBLIC_ACCESS_KEY_ID = S3_PUBLIC_ACCESS_KEY_ID
AWS_PUBLIC_SECRET_ACCESS_KEY = S3_PUBLIC_SECRET_ACCESS_KEY
AWS_REGION_PUBLIC = S3_PUBLIC_REGION


class S3Client:
    def __init__(self):
        # todo 这里的key要放到环境变量中
        # 私有与公有桶分别使用对应区域客户端
        self.private_client = boto3.client(
            's3',
            aws_access_key_id=AWS_PRIVATE_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_PRIVATE_SECRET_ACCESS_KEY,
            region_name=AWS_REGION_PRIVATE,
        )
        self.public_client = boto3.client(
            's3',
            aws_access_key_id=AWS_PUBLIC_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_PUBLIC_SECRET_ACCESS_KEY,
            region_name=AWS_REGION_PUBLIC,
        )
        self.aioboto3_session = aioboto3.Session(
            aws_access_key_id=AWS_PRIVATE_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_PRIVATE_SECRET_ACCESS_KEY,
            region_name=AWS_REGION_PRIVATE,
        )
        
    async def get_s3_session(self):
        return self.aioboto3_session

    def random_localfile(
        self, filename: str | None = None, format: str | None = None, extension: str | None = None
    ) -> str:
        """
        在Lambda的/tmp目录下创建临时文件
        """
        if filename is None:
            filename = str(uuid.uuid4())
        if format is not None:
            filename = f"{filename}.{extension}"

        # 使用/tmp目录
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, filename)

        logger.info(f"create temp file {filepath}")
        return filepath

    def convert_http_url_to_s3_url(self, http_url: str) -> str:
        """
        将HTTP格式的S3 URL转换为S3协议格式的URL

        Args:
            http_url: HTTP格式的S3 URL，例如 "https://bucket.s3.amazonaws.com/key"

        Returns:
            str: S3协议格式的URL，例如 "s3://bucket/key"

        Raises:
            ValueError: 如果输入的URL格式不正确
        """
        import re

        # 匹配标准的S3 HTTP URL格式
        # 支持格式：https://bucket.s3.amazonaws.com/key 或 https://bucket.s3.region.amazonaws.com/key
        pattern = r"https://([^.]+)\.s3(?:\.[^.]+)?\.amazonaws\.com/(.+)"
        match = re.match(pattern, http_url)

        if not match:
            raise ValueError(f"Invalid S3 HTTP URL format: {http_url}")

        bucket_name = match.group(1)
        s3_key = match.group(2)

        return f"s3://{bucket_name}/{s3_key}"

    async def generate_presigned_url_async(
        self, bucket_name: str, s3_key: str, expiration: int | None = None
    ) -> str:
        """
        生成S3对象的预签名URL（异步）

        Args:
            bucket_name: S3桶名称
            s3_key: S3对象键
            expiration: URL有效期（秒），如果不提供则使用配置中的默认值

        Returns:
            预签名URL字符串
        """
        try:

            # 如果没有指定有效期，从配置中获取
            if not expiration:
                expiration = 3600
            session = await self.get_s3_session()
            async with session.client('s3', use_ssl=True, verify=True) as s3_client:  # type: ignore
                presigned_url = await s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket_name, "Key": s3_key},
                    ExpiresIn=expiration,
                )
            logger.info(
                f"Generated presigned URL for s3://{bucket_name}/{s3_key} (expires in {expiration}s)"
            )
            return presigned_url
        except ClientError as e:
            logger.error(
                f"Failed to generate presigned URL for s3://{bucket_name}/{s3_key}: {e}"
            )
            raise

    def _client_for_bucket(self, bucket_name: str):
        if bucket_name == "seelemedia":
            logger.info("Select S3 client for bucket=%s region=%s", bucket_name, AWS_REGION_PUBLIC)
            return self.public_client
        # 默认走私有区域
        logger.info("Select S3 client for bucket=%s region=%s", bucket_name, AWS_REGION_PRIVATE)
        return self.private_client

    def generate_presigned_url(self, url: str):
        try:
            logger.info("Presign request url=%s", url)
            bucket_name, object_key = _parse_s3_url(url)
        except ValueError:
            # Not an S3 URL we can parse; return original URL
            return url

        try:
            client = self._client_for_bucket(bucket_name)
            logger.info("Generating presigned URL bucket=%s key=%s", bucket_name, object_key)
            url = client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": bucket_name,
                    "Key": object_key
                },
                ExpiresIn=3600  # 过期时间，单位秒，这里是1小时
            )
            logger.info("Presigned URL generated: %s", url)
            return url

        except NoCredentialsError:
            logger.info("没有找到 AWS 凭证，请配置 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY")
            return url

    def move_and_get_accessible_url(
            self,
            source_url: str,
            target_bucket: str,
            new_file_name: Optional[str] = None,
            tag: str = "game_asset",
            force_extension: Optional[str] = None,
            encrypt: bool = False,
            encrypt_version: Optional[str] = None,
    ) -> str:
        """
        移动文件到目标桶并返回可访问的URL（支持可选加密-命名标记）

        :param source_url: 源文件URL（支持 s3:// 和 https://bucket.s3.*.amazonaws.com/ 以及CDN/代理URL）
        :param target_bucket: 目标桶名字，例如 "seelemedia" / "seelemedia-private" / "temp"
        :param new_file_name: 新文件名（不包含扩展名），如果为None则保持原文件名
        :param tag: 路径前缀，相当于目录名
        :param force_extension: 强制扩展名（包含点号，如 ".lua.txt"），如果为None则使用原扩展名
        :param encrypt: 是否加密（当前实现为文件名打标 _enc<version>，不改变内容）
        :param encrypt_version: 加密版本（encrypt=True 时必填）
        :return: 可访问的URL
        """
        if not source_url:
            return source_url

        try:
            logger.info(
                "move_and_get_accessible_url start source_url=%s target_bucket=%s new_file_name=%s force_extension=%s encrypt=%s encrypt_version=%s",
                source_url, target_bucket, new_file_name, force_extension, encrypt, encrypt_version
            )
            # 1) 先尝试将 CDN URL 转换为原始的 S3/Origin URL
            processed_url = _convert_cdn_to_s3_url(source_url)
            logger.info("Processed URL=%s", processed_url)

            # 2) 解析出源桶与对象 key
            source_bucket_name, object_key = _parse_s3_url(processed_url)
            logger.info("Parsed source bucket=%s key=%s", source_bucket_name, object_key)

            # 3) 如果源桶就是目标桶，仅做URL转换返回
            if source_bucket_name == target_bucket:
                # 公有桶：返回替换后的 CDN URL
                if target_bucket == "seelemedia":
                    origin_url = f"https://{target_bucket}.s3.amazonaws.com/{object_key}"
                    logger.info("Same-bucket public, returning CDN url for %s", origin_url)
                    return _cdn_replace_host(origin_url)
                # 私有桶：返回 s3:// 形式
                if target_bucket == "seelemedia-private":
                    logger.info("Same-bucket private, returning s3 url")
                    return f"s3://{target_bucket}/{object_key}"
                # 其他：预签名可访问URL
                logger.info("Same-bucket other, returning presigned url")
                return self.generate_presigned_url(f"s3://{target_bucket}/{object_key}")

            # 4) 需要重命名时确定最终文件名
            original_file_name = object_key.split("/")[-1]
            final_file_name = original_file_name

            if new_file_name:
                if force_extension:
                    use_ext = force_extension
                else:
                    dot_idx = original_file_name.rfind(".")
                    use_ext = original_file_name[dot_idx:] if dot_idx > 0 else ""
                unique_id = str(time.time_ns())
                final_file_name = f"{new_file_name}_{str(uuid.uuid4()).replace('-', '_')}_{unique_id}{use_ext}"
                logger.info("Rename: %s -> %s", original_file_name, final_file_name)

            # 5) 可选加密：文件名打标 _enc<VERSION>
            if encrypt:
                if not encrypt_version:
                    raise ValueError("encrypt_version is required when encrypt=True")
                dot_idx = final_file_name.find(".")
                if dot_idx > 0:
                    name_part = final_file_name[:dot_idx]
                    ext_group = final_file_name[dot_idx:]
                    final_file_name = f"{name_part}_enc{encrypt_version}{ext_group}"
                else:
                    final_file_name = f"{final_file_name}_enc{encrypt_version}"
                logger.info("Encrypt tag applied, new file name=%s", final_file_name)

            # 6) 计算目标 key（公有桶确保 media/ 前缀；私有桶添加环境前缀）
            if target_bucket == "seelemedia":
                target_key = f"media/{tag}/{final_file_name}"
            elif target_bucket == "seelemedia-private":
                target_key = _build_private_bucket_path(tag, final_file_name)
            else:
                target_key = f"{tag}/{final_file_name}"
            logger.info("Target key=%s", target_key)

            # 7) 执行 S3 复制（源 -> 目标）
            copy_source = {"Bucket": source_bucket_name, "Key": object_key}
            target_client = self._client_for_bucket(target_bucket)
            logger.info(
                "CopyObject start from %s/%s to %s/%s",
                source_bucket_name, object_key, target_bucket, target_key
            )
            target_client.copy_object(Bucket=target_bucket, Key=target_key, CopySource=copy_source)
            logger.info("CopyObject success")

            # 8) 返回最终可访问URL
            if target_bucket == "seelemedia":
                origin_url = f"https://{target_bucket}.s3.{AWS_REGION_PUBLIC}.amazonaws.com/{target_key}"
                final_url = _cdn_replace_host(origin_url)
                logger.info("Return public CDN url=%s", final_url)
                return final_url
            if target_bucket == "seelemedia-private":
                final_url = f"s3://{target_bucket}/{target_key}"
                logger.info("Return private s3 url=%s", final_url)
                return final_url

            # 其他桶：生成预签名URL
            final_url = self.generate_presigned_url(f"s3://{target_bucket}/{target_key}")
            logger.info("Return presigned url=%s", final_url)
            return final_url

        except Exception as e:
            logger.error("Failed to move file from %s to bucket %s: %s", source_url, target_bucket, e, exc_info=True)
            return source_url

    async def get_s3_url_file_async(self, url: str, timeout: float | None = 60.0) -> str:
        """
        异步获取S3文件内容（UTF-8文本）
        
        Args:
            url: 文件URL地址
            timeout: 超时时间（秒），默认使用 download_file_raw_async 的默认值（60秒）
        """
        logger.info(f"get_s3_file_content: {url}")
        tmp_file = await self.download_file_raw_async(url, timeout=timeout)
        try:
            with open(tmp_file, "r", encoding="utf-8") as f:
                data = f.read()
            return data
        finally:
            try:
                os.unlink(tmp_file)
            except Exception:
                pass


    async def get_s3_url_file_bytes_async(self, url: str, timeout: float | None = 60.0) -> bytes:
        """
        异步获取S3文件内容（二进制）
        
        Args:
            url: 文件URL地址
            timeout: 超时时间（秒），默认使用 download_file_raw_async 的默认值（60秒）
        """
        logger.info(f"get_s3_file_content: {url}")
        tmp_file = await self.download_file_raw_async(url, timeout=timeout)
        try:
            with open(tmp_file, "rb") as f:
                data = f.read()
            return data
        finally:
            try:
                os.unlink(tmp_file)
            except Exception:
                pass


    async def get_s3_url_image_base64_async(self, url: str, timeout: float | None = 60.0) -> str:
        """
        异步获取S3图片的base64编码，并避免重复添加前缀
        
        Args:
            url: 图片URL地址
            timeout: 超时时间（秒），默认60秒（图片通常较小，不需要太长的超时）
        
        Returns:
            base64编码的图片字符串（包含data URI前缀）
        """
        logger.info(f"get_s3_url_image_base64: {url}")

        # 已经有 data:image/...;base64, 前缀则直接返回
        if url.startswith("data:image/") and ";base64," in url:
            logger.info("Already base64 image data, returning as is.")
            return url

        tmp_file = await self.download_file_raw_async(url, timeout=timeout)
        try:
            with open(tmp_file, "rb") as image_file:
                base64_str = base64.b64encode(image_file.read()).decode("utf-8")

            image_type = "png"
            tmp_img_type = url.split(".")[-1].lower()
            if tmp_img_type == "png":
                image_type = "png"
            elif tmp_img_type == "jpg" or tmp_img_type == "jpeg":
                image_type = "jpeg"
            return f"data:image/{image_type};base64,{base64_str}"
        finally:
            try:
                os.unlink(tmp_file)
            except Exception:
                pass

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=15))
    async def download_file_raw_async(self, url: str, timeout: float | None = 60.0) -> str:
        """
        异步下载文件到临时目录
        
        Args:
            url: 文件URL地址
            timeout: 超时时间（秒），默认60秒
            
        Returns:
            临时文件路径
        """

        filename = os.path.basename(urlparse(url).path)
        tmpfile = self.random_localfile(filename=filename)

        start_time = time.perf_counter()

        if not url.startswith("s3://"):
            try:
                url = self.convert_http_url_to_s3_url(url)
            except Exception:
                pass

        if url.startswith("s3://"):
            # 处理S3 URL
            try:
                # 解析S3 URL
                parsed = urlparse(url)
                bucket_name = parsed.netloc
                s3_key = parsed.path.lstrip("/")

                logger.info(f"Downloading S3 file: bucket={bucket_name}, key={s3_key}")

                # 使用S3客户端下载文件
                session = await self.get_s3_session()
                async with session.client('s3', use_ssl=True, verify=True) as s3_client:  # type: ignore
                    await s3_client.download_file(bucket_name, s3_key, tmpfile)
                # 获取文件大小
                size = os.path.getsize(tmpfile)
                logger.info(f"Downloaded S3 file size: {size} bytes")

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")

                # 如果是访问被拒绝或未找到文件，尝试使用预签名URL
                if error_code in ["AccessDenied", "NoSuchKey", "Forbidden"]:
                    logger.warning(
                        f"Direct S3 download failed ({error_code}), trying presigned URL approach"
                    )
                    try:
                        # 生成预签名URL并使用HTTP方式下载
                        presigned_url = await self.generate_presigned_url_async(
                            bucket_name, s3_key
                        )
                        logger.info("Attempting download using presigned URL")

                        # 从预签名URL异步下载文件，传递timeout参数
                        from util.aiohttp_util import download_file_in_chunks
                        size = 0
                        with open(tmpfile, "wb") as f:
                            async for chunk in download_file_in_chunks(presigned_url, timeout=timeout):
                                f.write(chunk)
                                size += len(chunk)
                        logger.info(f"Downloaded file size using presigned URL: {size} bytes")

                    except Exception as presigned_error:
                        logger.error(
                            f"Presigned URL download also failed: {presigned_error}"
                        )
                        raise ValueError(f"S3 file {url} not accessible: {e}")
                else:
                    logger.error(f"Failed to download S3 file {url}: {e}")
                    raise ValueError(f"S3 file {url} download error: {e}")

            except Exception:
                logger.error(f"Error downloading S3 file {url}: {traceback.format_exc()}")
                raise
        else:
            # 处理HTTP/HTTPS URL，传递timeout参数
            try:
                from util.aiohttp_util import download_file_in_chunks
                logger.info(f"Downloading HTTP file: {url}")
                size = 0
                with open(tmpfile, "wb") as f:
                    async for chunk in download_file_in_chunks(url, timeout=timeout):
                        f.write(chunk)
                        size += len(chunk)
                logger.info(f"Downloaded file size: {size} bytes")
            except Exception as e:
                logger.error(f"Error downloading HTTP file {url}: {e}")
                raise

        logger.info(
            f"download {url} to {tmpfile}, duration: {time.perf_counter() - start_time}"
        )
        return tmpfile

if __name__ == "__main__":
    # print(S3Client().generate_presigned_url(
    #     "s3://seelemedia-private/TEST/gpt_image_edit/5f1c7e7e2c4bb7518b0fbbc4c1d14187_17577447994721915959633446397453.png"))
    r = S3Client().move_and_get_accessible_url(
        "s3://seelemedia-private/TEST/gpt_image_edit/5f1c7e7e2c4bb7518b0fbbc4c1d14187_17577447994721915959633446397453.png",
        "seelemedia", "assets")
    print(f"rrrrr:{r}")
