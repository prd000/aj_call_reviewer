import uuid
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from modules.templates import list_templates, get_template, save_template, delete_template

logger = logging.getLogger(__name__)
router = APIRouter()


class CriterionBody(BaseModel):
    id: str | None = None
    description: str
    success_condition: str


class TemplateBody(BaseModel):
    name: str | None = None
    criteria: list[CriterionBody] | None = None


@router.get("/templates")
def get_templates():
    templates = list_templates()
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "criteria_count": len(t.get("criteria", [])),
            "updated_at": t.get("updated_at"),
        }
        for t in templates
    ]


@router.post("/templates", status_code=201)
def create_template(body: TemplateBody):
    criteria = [
        {
            "id": c.id or str(uuid.uuid4()),
            "description": c.description,
            "success_condition": c.success_condition,
        }
        for c in (body.criteria or [])
    ]
    template = {"name": body.name or "", "criteria": criteria}
    return save_template(template)


@router.get("/templates/{template_id}")
def get_template_by_id(template_id: str):
    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return template


@router.put("/templates/{template_id}")
def update_template(template_id: str, body: TemplateBody):
    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    if body.name is not None:
        template["name"] = body.name
    if body.criteria is not None:
        template["criteria"] = [
            {
                "id": c.id or str(uuid.uuid4()),
                "description": c.description,
                "success_condition": c.success_condition,
            }
            for c in body.criteria
        ]
    return save_template(template)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template_by_id(template_id: str):
    templates = list_templates()
    if len(templates) <= 1:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the only remaining template.",
        )
    if not delete_template(template_id):
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
