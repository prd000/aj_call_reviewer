from fastapi import APIRouter, Depends
from pydantic import BaseModel

from modules.auth import require_bds_rep
from modules.tags import create_tag, list_tags

router = APIRouter()


class CreateTagBody(BaseModel):
    name: str


@router.get("/tags")
async def get_tags(user: dict = Depends(require_bds_rep)):
    return await list_tags()


@router.post("/tags")
async def post_tag(body: CreateTagBody, user: dict = Depends(require_bds_rep)):
    return await create_tag(body.name)
