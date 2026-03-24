"""
Deploy game template from S3 zip to canvas.
HTTP API only. Path handling matches threejs S3Storage: relative paths, forward slashes, no leading slash.
"""
import asyncio
import io
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from typing import Optional, Tuple

from config import config
from tools.threejs_tools.storage.s3_helper import get_s3_storage, get_aioboto3_session

logger = logging.getLogger(__name__)

# Max concurrent uploads when deploying template files to canvas (concurrency limit, not batch size).
UPLOAD_CONCURRENCY = 10


async def _suggestion_for_upload_failure(canvas_id: str) -> str:
    """Async: suggest recovery in message when deploy failed during upload (partial state)."""
    try:
        from util.threejs_utils import read_versions_json
        versions_data = await read_versions_json(canvas_id)
        current = versions_data.get("current_version", 0)
        if current and int(current) >= 1:
            return "Canvas may be in a partial state. Consider switching back to the previous version or retrying the same template deploy."
    except Exception as e:
        logger.debug("Could not read versions for suggestion: %s", e)
    return "Canvas may be in a partial state. Consider retrying the same template deploy, or switching back to the previous version if one was published."


def _normalize_rel_path(name: str) -> str:
    """
    Normalize zip entry name to S3 relative path (same convention as S3Storage._get_s3_key / list_files).
    Result: forward slashes, no leading . or /, no trailing /. Reject absolute paths in caller.
    """
    p = name.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p.lstrip("/")
    return p.strip("/")


def _s3_client_config() -> dict:
    """Same credentials as S3Storage for private bucket."""
    s3_cfg = config.s3
    return {
        "aws_access_key_id": s3_cfg.private_access_key_id,
        "aws_secret_access_key": s3_cfg.private_secret_key,
        "region_name": s3_cfg.private_region,
        "use_ssl": True,
        "verify": True,
    }


async def _upload_one_file(
    canvas_storage,
    rel_path: str,
    original_name: str,
    temp_dir: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[Optional[str], bool, Optional[str]]:
    """Upload a single file; semaphore limits concurrent uploads. Returns (rel_path or None if skipped, success, error_msg)."""
    async with semaphore:
        local_path = os.path.normpath(os.path.join(temp_dir, original_name))
        if not os.path.isfile(local_path):
            return (None, True, None)
        try:
            success, msg, _ = await canvas_storage.upload_file(
                file_name=rel_path,
                source_file_path=local_path,
            )
            return (rel_path, success, msg)
        except Exception as e:
            logger.exception("Upload failed for %s", rel_path)
            return (rel_path, False, str(e))


async def deploy_template_to_canvas(
    canvas_id: str,
    template_path: str,
) -> Tuple[bool, str, Optional[dict]]:
    """
    Download template zip from S3, unzip, upload all files to canvas, then delete
    any canvas files not in the template (full replace).

    Args:
        canvas_id: Target canvas ID (same bucket, script_base_prefix/{canvas_id}/).
        template_path: S3 key of the template zip (e.g. "TEST/templates/xxx.zip").
                       Leading slash is stripped.

    Returns:
        (success, message, data or None). On success data has only README (template README.md content, if any).
    """
    # S3 key: forward slashes, no leading slash, no ".." (same bucket key convention as threejs)
    template_path = (template_path or "").strip().lstrip("/").replace("\\", "/")
    if not template_path:
        return False, "template_path is required", None
    if ".." in template_path:
        return False, "template_path must not contain '..'", None

    canvas_id = (canvas_id or "").strip()
    if not canvas_id:
        return False, "canvas_id is required", None
    if ".." in canvas_id or "/" in canvas_id or "\\" in canvas_id:
        return False, "canvas_id must not contain '..', '/', or '\\'", None

    bucket = config.s3.private_bucket
    session = get_aioboto3_session()
    s3_config = _s3_client_config()
    temp_dir = None

    try:
        # 1. Download zip from S3
        async with session.client("s3", **s3_config) as s3_client:
            try:
                response = await s3_client.get_object(Bucket=bucket, Key=template_path)
            except Exception as e:
                logger.warning(f"Failed to get template from S3: {e}")
                return False, f"Template not found or failed to download: {e}", None

            zip_bytes = await response["Body"].read()

        if not zip_bytes:
            return False, "Template file is empty", None

        # 2. Unzip to temp dir (skip directory entries)
        temp_dir = tempfile.mkdtemp(prefix="deploy_template_")
        try:
            if sys.version_info >= (3, 11):
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes), "r", metadata_encoding="utf-8")
            else:
                zf = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
        except Exception as e:
            return False, f"Invalid zip file: {e}", None

        try:
            members_to_extract = []
            with zf:
                for name in zf.namelist():
                    if ".." in name:
                        continue
                    info = zf.getinfo(name)
                    if name.endswith("/") or info.file_size == 0:
                        continue
                    members_to_extract.append(name)
                for name in members_to_extract:
                    zf.extract(name, temp_dir)
        except Exception as e:
            return False, f"Failed to extract zip: {e}", None

        if not members_to_extract:
            return False, "Template zip contains no files", None

        # 3. Normalize paths (same convention as S3Storage list_files file_name: relative, forward slash, no leading /)
        path_pairs = []
        for name in members_to_extract:
            rel = _normalize_rel_path(name)
            if not rel or ".." in rel or os.path.isabs(rel):
                continue
            path_pairs.append((rel, name))
        if not path_pairs:
            return False, "Template zip contains no valid files after path normalization", None

        # 3.0 若 zip 内所有文件都在「同一层根目录」下（如 TheAviator-master/），则剥掉这一层，使画布根目录为 index.html、js/、css/ 等，便于打包
        first_segments = set()
        for rel, _ in path_pairs:
            parts = rel.replace("\\", "/").strip("/").split("/")
            if len(parts) >= 1 and parts[0]:
                first_segments.add(parts[0])
        if len(first_segments) == 1 and len(path_pairs) > 0:
            prefix = next(iter(first_segments)) + "/"
            if all(rel.startswith(prefix) for rel, _ in path_pairs):
                path_pairs = [(rel[len(prefix):] if rel.startswith(prefix) else rel, orig) for rel, orig in path_pairs]
                path_pairs = [(r, o) for r, o in path_pairs if r]  # 剥完后不允许空路径
                logger.debug("Deploy template: stripped single root dir %s", prefix.rstrip("/"))

        # 3.1 Find README.md (any path) and read content for response
        readme_content = ""
        for rel, original_name in path_pairs:
            if rel.replace("\\", "/").strip("/").split("/")[-1].upper() == "README.MD":
                local_path = os.path.normpath(os.path.join(temp_dir, original_name))
                if os.path.isfile(local_path):
                    try:
                        with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                            readme_content = f.read()
                    except Exception as e:
                        logger.debug("Could not read README.md: %s", e)
                break

        # 4. Upload each file to canvas (max UPLOAD_CONCURRENCY concurrent uploads)
        canvas_storage = await get_s3_storage(canvas_id)
        semaphore = asyncio.Semaphore(UPLOAD_CONCURRENCY)
        tasks = [
            _upload_one_file(canvas_storage, rel_path, original_name, temp_dir, semaphore)
            for rel_path, original_name in path_pairs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        uploaded = []
        for r in results:
            if isinstance(r, BaseException):
                logger.exception("Upload task raised or cancelled")
                suggestion = await _suggestion_for_upload_failure(canvas_id)
                return False, f"Upload failed: {r}. {suggestion}", None
            if not isinstance(r, tuple) or len(r) != 3:
                logger.warning("Unexpected upload result: %s", type(r))
                suggestion = await _suggestion_for_upload_failure(canvas_id)
                return False, f"Upload failed: unexpected result. {suggestion}", None
            rel_path, success, msg = r
            if not success:
                suggestion = await _suggestion_for_upload_failure(canvas_id)
                return False, f"Failed to upload {rel_path}: {msg}. {suggestion}", None
            if rel_path is not None:
                uploaded.append(rel_path)

        # 5. Delete canvas files not in template (full replace)
        list_ok, list_msg, current_files = await canvas_storage.list_files()
        if list_ok and current_files:
            current_names = {f["file_name"] for f in current_files}
            to_delete = current_names - set(uploaded)
            for name in to_delete:
                await canvas_storage.delete_file(name)
                logger.debug(f"Deleted obsolete file: {name}")
        elif not list_ok:
            logger.warning(f"List canvas files failed after upload: {list_msg}")

        return True, "Template deployed successfully", {"README": readme_content}

    except Exception as e:
        logger.exception("deploy_template_to_canvas error")
        return False, str(e), None
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Cleanup temp dir failed: {e}")
