import logging
import os
from json.decoder import JSONDecodeError

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.status import HTTP_400_BAD_REQUEST

from http_logic.entity import DeployTemplateRequest, GameRemixRequest
from http_logic.remix_handler import get_remix_handler
from util.deploy_template import deploy_template_to_canvas

logger = logging.getLogger(__name__)


def init_http_server(app: Starlette) -> None:
    """Register /remix and /threejs/deploy-template. Insert at head so they match before MCP catch-all."""
    app.routes.insert(0, Route("/remix", _remix, methods=["POST"]))
    app.routes.insert(0, Route("/threejs/deploy-template", _deploy_template, methods=["POST"]))


async def _remix(req: Request) -> Response:
    try:
        payload = await req.json()
    except JSONDecodeError:
        logger.warning("remix request has invalid JSON body")
        return JSONResponse(
            {"success": False, "message": "invalid JSON payload"},
            status_code=HTTP_400_BAD_REQUEST,
        )

    try:
        remix_request = GameRemixRequest.model_validate(payload)
    except ValidationError as exc:
        logger.warning("remix request validation failed", exc_info=exc)
        return JSONResponse(
            {
                "success": False,
                "message": "request validation failed",
            },
            status_code=HTTP_400_BAD_REQUEST,
        )

    handler = get_remix_handler()
    result = await handler.remix(remix_request)
    logger.info("remix request processed payload=%s result=%s", payload, result)
    return JSONResponse(result)


# S3 prefix for template zips: prod -> PROD/templates, others -> TEST/templates
# Priority: THREEJS_TEMPLATE_PREFIX env var > SERVER_ENV/ENV > default TEST
_TEMPLATE_PREFIX = os.environ.get(
    "THREEJS_TEMPLATE_PREFIX",
    "PROD/templates" if os.environ.get("SERVER_ENV", os.environ.get("ENV", "")).lower() == "prod" else "TEST/templates",
)


async def _deploy_template(req: Request) -> Response:
    """POST /threejs/deploy-template. canvas_id from header x-canvas-id; body: template_id (short id, server builds template_path).
    Response: { success, message, data: { README } }."""
    try:
        payload = await req.json()
    except JSONDecodeError:
        logger.warning("deploy-template request has invalid JSON body")
        return JSONResponse(
            {"success": False, "message": "invalid JSON payload", "data": {}},
            status_code=HTTP_400_BAD_REQUEST,
        )

    try:
        body = DeployTemplateRequest.model_validate(payload)
    except ValidationError as exc:
        logger.warning("deploy-template request validation failed", exc_info=exc)
        return JSONResponse(
            {"success": False, "message": "request validation failed", "data": {}},
            status_code=HTTP_400_BAD_REQUEST,
        )

    canvas_id = (req.headers.get("x-canvas-id") or "").strip()
    if not canvas_id:
        return JSONResponse(
            {"success": False, "message": "missing header x-canvas-id", "data": {}},
            status_code=HTTP_400_BAD_REQUEST,
        )
    if ".." in canvas_id or "/" in canvas_id or "\\" in canvas_id:
        return JSONResponse(
            {"success": False, "message": "canvas_id must not contain '..', '/', or '\\'", "data": {}},
            status_code=HTTP_400_BAD_REQUEST,
        )

    template_id = (body.template_id or "").strip().lstrip("/").replace("\\", "/")
    if not template_id:
        return JSONResponse(
            {"success": False, "message": "template_id is required", "data": {}},
            status_code=HTTP_400_BAD_REQUEST,
        )
    if ".." in template_id or "/" in template_id:
        return JSONResponse(
            {"success": False, "message": "template_id must not contain '..' or '/'", "data": {}},
            status_code=HTTP_400_BAD_REQUEST,
        )
    # Server appends .zip so llmbase only passes short id (e.g. TheAviator)
    s3_object_name = template_id if template_id.lower().endswith(".zip") else f"{template_id}.zip"
    template_path = f"{_TEMPLATE_PREFIX}/{s3_object_name}"

    success, message, data = await deploy_template_to_canvas(
        canvas_id=canvas_id,
        template_path=template_path,
    )
    if success:
        return JSONResponse({"success": True, "message": message, "data": data or {"README": ""}})
    return JSONResponse({"success": False, "message": message, "data": {}})
