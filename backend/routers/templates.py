import uuid
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from modules.templates import list_templates, get_template, save_template, delete_template

logger = logging.getLogger(__name__)
router = APIRouter()


class CriterionBody(BaseModel):
    id: str | None = None
    title: str | None = None
    description: str
    success_condition: str
    max_score: int | None = None


class TemplateBody(BaseModel):
    name: str | None = None
    criteria: list[CriterionBody] | None = None


@router.get("/templates")
async def get_templates():
    templates = await list_templates()
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "criteria_count": len(t.get("criteria", [])),
            "updated_at": t.get("updated_at"),
        }
        for t in templates
    ]


def _criterion_dict(c: CriterionBody) -> dict:
    d = {
        "id": c.id or str(uuid.uuid4()),
        "description": c.description,
        "success_condition": c.success_condition,
        "max_score": c.max_score if c.max_score is not None else 10,
    }
    if c.title is not None:
        d["title"] = c.title
    return d


@router.post("/templates", status_code=201)
async def create_template(body: TemplateBody):
    criteria = [_criterion_dict(c) for c in (body.criteria or [])]
    template = {"name": body.name or "", "criteria": criteria}
    return await save_template(template)


@router.get("/templates/{template_id}")
async def get_template_by_id(template_id: str):
    template = await get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return template


@router.put("/templates/{template_id}")
async def update_template(template_id: str, body: TemplateBody):
    template = await get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    if body.name is not None:
        template["name"] = body.name
    if body.criteria is not None:
        template["criteria"] = [_criterion_dict(c) for c in body.criteria]
    return await save_template(template)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template_by_id(template_id: str):
    templates = await list_templates()
    if len(templates) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the only remaining template.",
        )
    if not await delete_template(template_id):
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
