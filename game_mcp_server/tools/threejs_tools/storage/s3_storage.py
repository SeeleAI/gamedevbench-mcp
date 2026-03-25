"""
S3 Storage implementation for ThreeJS script file operations.
"""
import logging
from typing import Optional, List, Dict, Any, Tuple
from botocore.exceptions import ClientError

from config import config

logger = logging.getLogger(__name__)


class S3Storage:
    """S3存储操作类 - ThreeJS脚本文件管理"""
    
    def __init__(self, canvas_id: Optional[str] = None, session=None, custom_base_prefix: Optional[str] = None):
        """
        Initialize S3 storage client using config settings.
        Automatically reads configuration from config.s3 and config.threejs
        
        Args:
            canvas_id: Optional canvas ID for project isolation
            session: Optional shared aioboto3.Session instance. If not provided,
                    will be obtained from get_aioboto3_session() singleton.
                    This allows reusing the session across the service.
            custom_base_prefix: Optional custom base prefix (for bundle directory).
                               If provided, uses this prefix instead of script_base_prefix.
        """
        s3_cfg = config.s3
        threejs_cfg = config.threejs
        
        self.bucket_name = s3_cfg.private_bucket
        self.canvas_id = canvas_id
        
        # 如果提供了自定义前缀，使用它
        if custom_base_prefix:
            if canvas_id:
                self.base_prefix = f"{custom_base_prefix}/{canvas_id}/"
            else:
                self.base_prefix = f"{custom_base_prefix}/"
        else:
            # 默认：使用脚本存储前缀
            base_prefix = threejs_cfg.script_base_prefix.rstrip('/')
            if canvas_id:
                self.base_prefix = f"{base_prefix}/{canvas_id}/"
            else:
                self.base_prefix = f"{base_prefix}/"
        
        # Use shared aioboto3.Session to avoid creating multiple sessions
        if session is not None:
            self.session = session
        else:
            # Fallback: get from singleton if not provided (for backward compatibility)
            # Use lazy import to avoid circular import issues
            from . import s3_helper
            self.session = s3_helper.get_aioboto3_session()
        
        # Store S3 config for async client creation
        self.s3_config = {
            'aws_access_key_id': s3_cfg.private_access_key_id,
            'aws_secret_access_key': s3_cfg.private_secret_key,
            'region_name': s3_cfg.private_region,
            'use_ssl': True,
            'verify': True
        }
        
        logger.debug(f"S3Storage initialized. Bucket: {self.bucket_name}, Prefix: {self.base_prefix}")
    
    def _get_s3_key(self, file_name: str) -> str:
        """Convert file name to full S3 key"""
        return f"{self.base_prefix}{file_name}"
    
    def _get_content_type(self, file_name: str) -> str:
        """Infer content type from file extension"""
        extension = file_name.lower().split('.')[-1]
        content_types = {
            'html': 'text/html',
            'htm': 'text/html',
            'js': 'application/javascript',
            'css': 'text/css',
            'json': 'application/json',
            'txt': 'text/plain',
            'py': 'text/x-python',
            'md': 'text/markdown',
            'xml': 'application/xml',
        }
        return content_types.get(extension, 'application/octet-stream')
    
    async def upload_file(
        self,
        file_name: str,
        content: Optional[str] = None,
        source_file_path: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
        max_retries: int = 1
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Upload file to S3
        
        Args:
            file_name: Name of the file to upload (S3 relative path)
            content: File content (string). Either content or source_file_path must be provided.
            source_file_path: Local file path to upload from. Either content or source_file_path must be provided.
            metadata: Optional metadata dict
            max_retries: Maximum number of retry attempts (default: 1, no retry)
            
        Returns:
            Tuple[bool, str, Optional[Dict[str, Any]]]: (success, message, data)
        """
        import asyncio
        
        # 参数验证：必须提供 content 或 source_file_path 之一
        if not content and not source_file_path:
            return False, "Either content or source_file_path must be provided", None
        if content and source_file_path:
            return False, "Cannot provide both content and source_file_path", None
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                s3_key = self._get_s3_key(file_name)
                content_type = self._get_content_type(file_name)
                
                # 优先使用文件路径（避免内存占用）
                if source_file_path:
                    # 从文件读取内容
                    import os
                    if not os.path.exists(source_file_path):
                        return False, f"Source file not found: {source_file_path}", None
                    
                    # 读取文件内容（使用二进制模式，然后编码）
                    with open(source_file_path, 'rb') as f:
                        file_body = f.read()
                    content_length = len(file_body)
                else:
                    # 使用内存内容
                    file_body = content.encode('utf-8')
                    content_length = len(content)
                
                put_params = {
                    'Bucket': self.bucket_name,
                    'Key': s3_key,
                    'Body': file_body,
                    'ContentType': content_type,
                }
                
                if metadata:
                    put_params['Metadata'] = metadata
                
                async with self.session.client('s3', **self.s3_config) as s3_client:
                    await s3_client.put_object(**put_params)
                
                logger.info(f"File uploaded successfully: {s3_key}")
                return True, f"File '{file_name}' uploaded to S3 successfully", {
                    "file_name": file_name,
                    "s3_key": s3_key,
                    "s3_uri": f"s3://{self.bucket_name}/{s3_key}",
                    "content_length": content_length,
                    "content_type": content_type
                }
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_msg = e.response['Error']['Message']
                last_error = f"S3 error: {error_code} - {error_msg}"
                
                if attempt < max_retries - 1:
                    # 还有重试机会
                    delay = min(2 ** attempt, 4)  # 指数退避：1s, 2s, 4s
                    logger.warning(f"S3 upload failed (attempt {attempt + 1}/{max_retries}), "
                                 f"retrying in {delay}s: {last_error}")
                    await asyncio.sleep(delay)
                else:
                    # 最后一次尝试也失败了
                    logger.error(f"S3 ClientError during upload after {max_retries} attempts: "
                               f"{error_code} - {error_msg}")
                    
            except Exception as e:
                last_error = f"Upload error: {str(e)}"
                
                if attempt < max_retries - 1:
                    # 还有重试机会
                    delay = min(2 ** attempt, 4)  # 指数退避：1s, 2s, 4s
                    logger.warning(f"Upload failed (attempt {attempt + 1}/{max_retries}), "
                                 f"retrying in {delay}s: {last_error}")
                    await asyncio.sleep(delay)
                else:
                    # 最后一次尝试也失败了
                    logger.error(f"Error uploading file to S3 after {max_retries} attempts: {str(e)}")
        
        # 所有重试都失败
        return False, last_error or "Upload failed", None
    
    async def download_file(self, file_name: str, max_retries: int = 1) -> Tuple[bool, str, Optional[str]]:
        """
        Download file content from S3
        
        Args:
            file_name: Name of the file to download
            max_retries: Maximum number of retry attempts (default: 1, no retry)
            
        Returns:
            Tuple[bool, str, Optional[str]]: (success, message, content)
        """
        import asyncio
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                s3_key = self._get_s3_key(file_name)
                
                async with self.session.client('s3', **self.s3_config) as s3_client:
                    response = await s3_client.get_object(
                        Bucket=self.bucket_name,
                        Key=s3_key
                    )
                    
                    # Read the body content
                    body = await response['Body'].read()
                    try:
                        content = body.decode('utf-8')
                    except UnicodeDecodeError as decode_error:
                        # 文件不是 UTF-8 编码（可能是二进制文件或其他编码）
                        logger.warning(f"File '{file_name}' is not UTF-8 encoded: {str(decode_error)}. "
                                     f"File size: {len(body)} bytes. This file will be skipped for bundling.")
                        return False, f"File '{file_name}' is not UTF-8 encoded (possibly binary file)", None
                
                logger.info(f"File downloaded successfully: {s3_key}")
                return True, f"File '{file_name}' downloaded successfully", content
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'NoSuchKey':
                    # 文件不存在，不需要重试
                    logger.warning(f"File not found in S3: {file_name}")
                    return False, f"File '{file_name}' does not exist in S3", None
                else:
                    error_msg = e.response['Error']['Message']
                    last_error = f"S3 error: {error_code} - {error_msg}"
                    
                    if attempt < max_retries - 1:
                        # 还有重试机会
                        delay = min(2 ** attempt, 4)  # 指数退避：1s, 2s, 4s
                        logger.warning(f"S3 download failed (attempt {attempt + 1}/{max_retries}), "
                                     f"retrying in {delay}s: {last_error}")
                        await asyncio.sleep(delay)
                    else:
                        # 最后一次尝试也失败了
                        logger.error(f"S3 ClientError during download after {max_retries} attempts: "
                                   f"{error_code} - {error_msg}")
                        
            except Exception as e:
                last_error = f"Download error: {str(e)}"
                
                if attempt < max_retries - 1:
                    # 还有重试机会
                    delay = min(2 ** attempt, 4)  # 指数退避：1s, 2s, 4s
                    logger.warning(f"Download failed (attempt {attempt + 1}/{max_retries}), "
                                 f"retrying in {delay}s: {last_error}")
                    await asyncio.sleep(delay)
                else:
                    # 最后一次尝试也失败了
                    logger.error(f"Error downloading file from S3 after {max_retries} attempts: {str(e)}")
        
        # 所有重试都失败
        return False, last_error or "Download failed", None
    
    async def delete_file(self, file_name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Delete file from S3"""
        try:
            s3_key = self._get_s3_key(file_name)
            
            # Check if file exists first
            exists, _, _ = await self.file_exists(file_name)
            if not exists:
                return False, f"File '{file_name}' does not exist in S3", None
            
            async with self.session.client('s3', **self.s3_config) as s3_client:
                await s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
            
            logger.info(f"File deleted successfully: {s3_key}")
            return True, f"File '{file_name}' deleted from S3 successfully", {
                "file_name": file_name,
                "s3_key": s3_key,
                "s3_uri": f"s3://{self.bucket_name}/{s3_key}"
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            logger.error(f"S3 ClientError during delete: {error_code} - {error_msg}")
            return False, f"S3 error: {error_code} - {error_msg}", None
        except Exception as e:
            logger.error(f"Error deleting file from S3: {str(e)}")
            return False, f"Delete error: {str(e)}", None
    
    async def file_exists(self, file_name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Check if file exists in S3"""
        try:
            s3_key = self._get_s3_key(file_name)
            
            async with self.session.client('s3', **self.s3_config) as s3_client:
                response = await s3_client.head_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
            
            return True, f"File '{file_name}' exists", {
                "file_name": file_name,
                "s3_key": s3_key,
                "content_length": response.get('ContentLength', 0),
                "last_modified": str(response.get('LastModified', '')),
                "content_type": response.get('ContentType', '')
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ('404', 'NoSuchKey'):
                return False, f"File '{file_name}' does not exist", None
            else:
                error_msg = e.response['Error']['Message']
                logger.error(f"S3 ClientError during exists check: {error_code} - {error_msg}")
                return False, f"S3 error: {error_code} - {error_msg}", None
        except Exception as e:
            logger.error(f"Error checking file existence in S3: {str(e)}")
            return False, f"Error: {str(e)}", None
    
    async def list_files(
        self,
        file_extension: Optional[str] = None
    ) -> Tuple[bool, str, Optional[List[Dict[str, Any]]]]:
        """List all files in S3"""
        try:
            files = []
            
            async with self.session.client('s3', **self.s3_config) as s3_client:
                paginator = s3_client.get_paginator('list_objects_v2')
                
                async for page in paginator.paginate(
                    Bucket=self.bucket_name,
                    Prefix=self.base_prefix
                ):
                    if 'Contents' not in page:
                        continue
                        
                    for obj in page['Contents']:
                        s3_key = obj['Key']
                        file_name = s3_key[len(self.base_prefix):]
                        
                        if file_name.endswith('/'):
                            continue
                        
                        if file_extension and not file_name.lower().endswith(file_extension.lower()):
                            continue
                        
                        files.append({
                            "file_name": file_name,
                            "s3_key": s3_key,
                            "size": obj.get('Size', 0),
                            "last_modified": str(obj.get('LastModified', ''))
                        })
            
            logger.info(f"Listed {len(files)} files from S3")
            return True, f"Found {len(files)} files", files
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            logger.error(f"S3 ClientError during list: {error_code} - {error_msg}")
            return False, f"S3 error: {error_code} - {error_msg}", None
        except Exception as e:
            logger.error(f"Error listing files from S3: {str(e)}")
            return False, f"List error: {str(e)}", None
    
    async def copy_file_from(
        self,
        source_storage: 'S3Storage',  # 使用字符串避免循环导入问题（虽然这里不会发生）
        file_name: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Copy a file from another S3Storage instance (same bucket, different prefix).
        
        Uses S3 copy_object API for efficient bucket-internal copying without downloading/uploading.
        
        Args:
            source_storage: Source S3Storage instance to copy from
            file_name: Name of the file to copy
            
        Returns:
            Tuple[bool, str, Optional[Dict[str, Any]]]: (success, message, data)
        """
        try:
            # 验证源和目标在同一个 bucket
            if source_storage.bucket_name != self.bucket_name:
                error_msg = f"源和目标不在同一个 S3 bucket: {source_storage.bucket_name} != {self.bucket_name}"
                logger.error(error_msg)
                return False, error_msg, None
            
            source_key = source_storage._get_s3_key(file_name)
            target_key = self._get_s3_key(file_name)
            copy_source = {"Bucket": source_storage.bucket_name, "Key": source_key}
            
            logger.debug(f"S3复制: {source_storage.bucket_name}/{source_key} -> {self.bucket_name}/{target_key}")
            
            async with self.session.client('s3', **self.s3_config) as s3_client:
                await s3_client.copy_object(
                    Bucket=self.bucket_name,
                    Key=target_key,
                    CopySource=copy_source
                )
            
            logger.info(f"File copied successfully: {source_key} -> {target_key}")
            return True, f"File '{file_name}' copied successfully", {
                "file_name": file_name,
                "source_s3_key": source_key,
                "target_s3_key": target_key,
                "source_s3_uri": f"s3://{source_storage.bucket_name}/{source_key}",
                "target_s3_uri": f"s3://{self.bucket_name}/{target_key}"
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            logger.error(f"S3 ClientError during copy: {error_code} - {error_msg}")
            return False, f"S3 error: {error_code} - {error_msg}", None
        except Exception as e:
            logger.error(f"Error copying file from S3: {str(e)}")
            return False, f"Copy error: {str(e)}", None
