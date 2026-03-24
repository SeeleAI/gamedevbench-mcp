from pydantic import BaseModel


class GameRemixRequest(BaseModel):
    canvas_id: str
    remix_from_canvas_id: str


class DeployTemplateRequest(BaseModel):
    """Request body for POST /threejs/deploy-template. canvas_id from header x-canvas-id; body has template_id only, server builds template_path = TEST/templates/<template_id>."""

    template_id: str