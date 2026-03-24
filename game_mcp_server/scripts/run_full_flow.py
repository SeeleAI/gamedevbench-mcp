"""
本地跑通完整流程：部署模板 → 打包 + runtime（read_console 同逻辑）→ 下载打包结果到本地。

用法（在 game_mcp_server 目录下）:
  uv run python scripts/run_full_flow.py <canvas_id> <template_id> [--out path/to/bundled.html]
  uv run python scripts/run_full_flow.py my-canvas-123 TheAviator --out ./bundled.html

可选:
  --http-deploy    使用 HTTP 接口部署模板（需先启动服务，默认 http://127.0.0.1:6600）
  --out FILE       将打包好的 index.html 复制到指定路径
  --skip-runtime   只部署+打包，不跑 runtime（不测执行日志）

前置:
  1. 在 game_mcp_server/util/html_bundler 下执行 npm install
  2. 模板 zip 已在 S3：TEST/templates/<template_id>.zip（如 TheAviator.zip）
  3. 若用 --http-deploy，需先：uv run python server_threejs_streamablehttp.py
"""
import argparse
import asyncio
import logging
import os
import shutil
import sys

if __name__ == "__main__":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)

# 必须在 add path 之后、其他业务 import 之前设置 RUN_PLATFORM（与 server_threejs_streamablehttp 一致）
os.environ.setdefault("RUN_PLATFORM", "3js")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from util.logging_context import init_logging

init_logging()
logger = logging.getLogger(__name__)

# 模板 S3 前缀（与 http_register 一致）
_TEMPLATE_PREFIX = "TEST/templates"


def _template_path(template_id: str) -> str:
    tid = (template_id or "").strip().lstrip("/").replace("\\", "/")
    if not tid:
        raise ValueError("template_id is required")
    if ".." in tid or "/" in tid:
        raise ValueError("template_id must not contain '..' or '/'")
    s3_name = tid if tid.lower().endswith(".zip") else f"{tid}.zip"
    return f"{_TEMPLATE_PREFIX}/{s3_name}"


async def _deploy_direct(canvas_id: str, template_path: str) -> tuple[bool, str, dict | None]:
    """直接调用 deploy_template_to_canvas（与 HTTP 接口同逻辑）。"""
    from util.deploy_template import deploy_template_to_canvas
    return await deploy_template_to_canvas(canvas_id=canvas_id, template_path=template_path)


async def _deploy_http(canvas_id: str, template_id: str, base_url: str) -> tuple[bool, str, dict | None]:
    """通过 HTTP 调用部署接口。"""
    import aiohttp
    url = f"{base_url.rstrip('/')}/threejs/deploy-template"
    payload = {"template_id": template_id}
    headers = {"x-canvas-id": canvas_id, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                return False, f"HTTP {resp.status}: {text}", None
            try:
                data = __import__("json").loads(text)
            except Exception as e:
                return False, f"Invalid JSON: {e}", None
            if data.get("success"):
                return True, data.get("message", "ok"), data.get("data")
            return False, data.get("message", "deploy failed"), data.get("data")


async def _bundle_and_runtime(canvas_id: str, skip_runtime: bool) -> tuple[bool, str, str | None]:
    """
    打包画布 + 可选 runtime。返回 (success, message, bundled_html_path)。
    bundled_html_path 为绝对路径，供后续复制到 --out。
    """
    from util.threejs_utils import bundle_canvas_files
    from util.threejs_runtime import execute_threejs_code
    from config import config

    bundle_result = await bundle_canvas_files(canvas_id)
    if not bundle_result.get("success"):
        return False, bundle_result.get("message", "bundle failed"), None

    data = bundle_result.get("data", {})
    html_path = data.get("bundled_html_path")
    if not html_path or not os.path.isfile(html_path):
        return False, "bundled_html_path not found or file missing", None

    if skip_runtime:
        return True, "bundle ok (runtime skipped)", html_path

    timeout = getattr(config.threejs, "runtime_timeout", 30)
    try:
        result = await execute_threejs_code(
            html_file_path=html_path,
            console_type="error",
            lines=10,
            timeout=timeout,
        )
        logs = result.get("logs", "")
        has_errors = (result.get("filtered_logs", 0) > 0)
        msg = "No errors found. Code check passed." if not has_errors else logs
        return True, msg, html_path
    except Exception as e:
        return False, str(e), html_path  # 仍返回路径，方便用户复制


async def _main(
    canvas_id: str,
    template_id: str,
    use_http_deploy: bool,
    http_base_url: str,
    out_path: str | None,
    skip_runtime: bool,
) -> int:
    from remote_config import init_all_configs
    await init_all_configs()

    canvas_id = (canvas_id or "").strip()
    if not canvas_id:
        logger.error("canvas_id is required")
        return 1
    if ".." in canvas_id or "/" in canvas_id or "\\" in canvas_id:
        logger.error("canvas_id must not contain '..', '/', or '\\'")
        return 1

    try:
        template_path = _template_path(template_id)
    except ValueError as e:
        logger.error("%s", e)
        return 1

    # 1. 部署模板
    logger.info("Step 1: Deploy template to canvas %s (template=%s)", canvas_id, template_path)
    if use_http_deploy:
        ok, msg, data = await _deploy_http(canvas_id, template_id, http_base_url)
    else:
        ok, msg, data = await _deploy_direct(canvas_id, template_path)
    if not ok:
        logger.error("Deploy failed: %s", msg)
        return 1
    logger.info("Deploy ok: %s", msg)

    # 2. 打包 + runtime
    logger.info("Step 2: Bundle + runtime (read_console logic) for canvas %s", canvas_id)
    ok, msg, html_path = await _bundle_and_runtime(canvas_id, skip_runtime)
    if not ok:
        logger.error("Bundle/runtime failed: %s", msg)
        return 1
    logger.info("Bundle+runtime ok: %s", msg)

    # 3. 可选：复制到 --out
    if out_path and html_path:
        out_path = os.path.abspath(out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        shutil.copy2(html_path, out_path)
        logger.info("Step 3: Copied bundled HTML to %s", out_path)
    else:
        logger.info("Step 3: Bundled file at %s (use --out to copy)", html_path)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Full flow: deploy template → bundle + runtime → optional download bundled file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("canvas_id", help="Target canvas ID")
    parser.add_argument("template_id", help="Template short id (e.g. TheAviator) -> TEST/templates/TheAviator.zip")
    parser.add_argument("--out", "-o", metavar="FILE", help="Copy bundled index.html to this path")
    parser.add_argument("--http-deploy", action="store_true", help="Use HTTP POST to deploy (server must be running)")
    parser.add_argument(
        "--http-base",
        default=os.environ.get("FULL_FLOW_BASE_URL", "http://127.0.0.1:6600"),
        help="Base URL when using --http-deploy (default: http://127.0.0.1:6600)",
    )
    parser.add_argument("--skip-runtime", action="store_true", help="Only deploy + bundle, do not run runtime")
    args = parser.parse_args()

    return asyncio.run(
        _main(
            canvas_id=args.canvas_id,
            template_id=args.template_id,
            use_http_deploy=args.http_deploy,
            http_base_url=args.http_base,
            out_path=args.out,
            skip_runtime=args.skip_runtime,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
