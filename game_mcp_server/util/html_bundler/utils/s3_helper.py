#!/usr/bin/env python3
"""
S3 Helper Script for html-bundler
使用 boto3 进行 S3 操作（集成在 game_mcp_server 中）
"""
import os
import sys
import json
import argparse
from typing import Dict, Any, Optional

# 使用 game_mcp_server 的 S3 配置
try:
    # 尝试从环境变量获取（game_mcp_server 会设置这些）
    import boto3
    from botocore.exceptions import ClientError
except ImportError as e:
    print(json.dumps({
        "success": False,
        "error": f"Failed to import boto3: {str(e)}"
    }), file=sys.stderr)
    sys.exit(1)


def _get_s3_client():
    """获取 S3 客户端"""
    access_key = os.getenv('S3_PRIVATE_ACCESS_KEY_ID')
    secret_key = os.getenv('S3_PRIVATE_SECRET_ACCESS_KEY')
    region = os.getenv('S3_PRIVATE_REGION', 'ap-southeast-1')
    
    # 增强错误信息：检查环境变量是否存在
    if not access_key:
        return {
            "success": False,
            "error": "S3_PRIVATE_ACCESS_KEY_ID not found in environment variables"
        }
    if not secret_key:
        return {
            "success": False,
            "error": "S3_PRIVATE_SECRET_ACCESS_KEY not found in environment variables"
        }
    
    try:
        return boto3.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to create S3 client: {str(e)}"
        }


def upload_file_to_s3(local_path: str, s3_url: str, content_type: Optional[str] = None) -> Dict[str, Any]:
    """
    上传文件到 S3
    
    Args:
        local_path: 本地文件路径
        s3_url: S3 URL (格式: s3://bucket/key)
        content_type: 可选的内容类型
    
    Returns:
        Dict with success status
    """
    try:
        # 验证 S3 URL 格式
        if not s3_url.startswith('s3://'):
            return {
                "success": False,
                "error": f"Invalid S3 URL format: {s3_url}. Must start with 's3://'"
            }
        
        # 验证文件存在
        if not os.path.exists(local_path):
            return {
                "success": False,
                "error": f"Local file not found: {local_path}"
            }
        
        # 解析 S3 URL
        parts = s3_url[5:].split('/', 1)  # 移除 's3://' 前缀
        if len(parts) != 2:
            return {
                "success": False,
                "error": f"Invalid S3 URL format: {s3_url}. Expected format: s3://bucket/key"
            }
        
        bucket_name = parts[0]
        object_key = parts[1]
        
        # 获取 S3 客户端
        s3_client = _get_s3_client()
        if isinstance(s3_client, dict):  # 错误情况
            return s3_client
        
        # 上传文件
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type
        
        s3_client.upload_file(local_path, bucket_name, object_key, ExtraArgs=extra_args)
        
        return {
            "success": True
        }
    except ClientError as e:
        # 增强错误信息：输出完整的 ClientError 详情
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        error_details = {
            "error_code": error_code,
            "error_message": error_message,
            "bucket": bucket_name,
            "key": object_key,
            "local_path": local_path,
        }
        return {
            "success": False,
            "error": f"S3 ClientError [{error_code}]: {error_message}",
            "error_details": error_details
        }
    except Exception as e:
        # 增强错误信息：包含异常类型和详细信息
        import traceback
        error_trace = traceback.format_exc()
        return {
            "success": False,
            "error": f"Unexpected error: {type(e).__name__}: {str(e)}",
            "error_details": {
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "traceback": error_trace
            }
        }


def main():
    """主入口点"""
    parser = argparse.ArgumentParser(description='S3 Helper for html-bundler')
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Upload command
    upload_parser = subparsers.add_parser('upload', help='Upload file to S3')
    upload_parser.add_argument('--local-path', required=True, help='Local file path')
    upload_parser.add_argument('--s3-url', required=True, help='S3 URL')
    upload_parser.add_argument('--content-type', help='Content type')
    
    try:
        args = parser.parse_args()
        
        if args.command == 'upload':
            result = upload_file_to_s3(args.local_path, args.s3_url, args.content_type)
        else:
            result = {
                "success": False,
                "error": "Unknown command. Only 'upload' is supported."
            }
        
        # 输出 JSON 结果到 stdout（确保错误信息也能被捕获）
        print(json.dumps(result, ensure_ascii=False))
        
        # 如果失败，也输出到 stderr 以便调试
        if not result.get("success", False):
            error_msg = result.get("error", "Unknown error")
            print(f"ERROR: {error_msg}", file=sys.stderr)
            if "error_details" in result:
                print(f"ERROR DETAILS: {json.dumps(result.get('error_details'), ensure_ascii=False)}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        # 捕获所有未处理的异常
        import traceback
        error_result = {
            "success": False,
            "error": f"Fatal error in main: {type(e).__name__}: {str(e)}",
            "error_details": {
                "exception_type": type(e).__name__,
                "exception_message": str(e),
                "traceback": traceback.format_exc()
            }
        }
        print(json.dumps(error_result, ensure_ascii=False))
        print(f"FATAL ERROR: {str(e)}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()



