"""
上传本地模板 zip 到 S3：TEST/templates/<对象名>，直接覆盖同名文件。

用法（在 game_mcp_server 目录下）:
  uv run python scripts/upload_template_zip.py <本地zip路径> [S3对象名]
  uv run python scripts/upload_template_zip.py "C:/Users/xxx/Downloads/TheAviator.zip"
  uv run python scripts/upload_template_zip.py "C:/Users/xxx/Downloads/TheAviator.zip" TheAviator.zip

S3 key = TEST/templates/<S3对象名>，未传对象名时用本地文件名（如 TheAviator.zip）。
上传为 put_object，同 key 会直接覆盖（替换同名文件）。
"""
import argparse
import asyncio
import os
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

os.environ.setdefault("RUN_PLATFORM", "3js")

_TEMPLATE_PREFIX = "TEST/templates"


def _s3_client_config():
    from config import config
    s3_cfg = config.s3
    return {
        "aws_access_key_id": s3_cfg.private_access_key_id,
        "aws_secret_access_key": s3_cfg.private_secret_key,
        "region_name": s3_cfg.private_region,
        "use_ssl": True,
        "verify": True,
    }


async def upload_zip(local_path: str, s3_object_name: str) -> bool:
    from config import config
    from tools.threejs_tools.storage.s3_helper import get_aioboto3_session

    bucket = config.s3.private_bucket
    key = f"{_TEMPLATE_PREFIX}/{s3_object_name}".replace("\\", "/").strip("/")
    if ".." in key:
        print("Error: S3 object name must not contain '..'", file=sys.stderr)
        return False

    with open(local_path, "rb") as f:
        body = f.read()
    if not body:
        print("Error: File is empty", file=sys.stderr)
        return False

    session = get_aioboto3_session()
    s3_config = _s3_client_config()
    async with session.client("s3", **s3_config) as s3_client:
        await s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/zip",
        )
    print(f"Uploaded: {local_path} -> s3://{bucket}/{key} ({len(body)} bytes)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload local template zip to S3 TEST/templates/<name> (overwrites same key).",
    )
    parser.add_argument("local_zip", help="Local path to the .zip file")
    parser.add_argument(
        "s3_name",
        nargs="?",
        default=None,
        help="S3 object name (e.g. TheAviator.zip). Default: basename of local_zip",
    )
    args = parser.parse_args()

    local_path = os.path.abspath(args.local_zip)
    if not os.path.isfile(local_path):
        print(f"Error: Not a file: {local_path}", file=sys.stderr)
        return 1
    if not local_path.lower().endswith(".zip"):
        print("Warning: File does not end with .zip", file=sys.stderr)

    s3_object_name = (args.s3_name or os.path.basename(local_path)).strip().lstrip("/").replace("\\", "/")
    if not s3_object_name:
        print("Error: S3 object name is empty", file=sys.stderr)
        return 1
    if not s3_object_name.lower().endswith(".zip"):
        s3_object_name = f"{s3_object_name}.zip"

    ok = asyncio.run(upload_zip(local_path, s3_object_name))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
