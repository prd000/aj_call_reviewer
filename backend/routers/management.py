import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from modules.auth import get_current_user, require_bds_rep
from modules.firms import delete_firm, get_firm, get_firm_users, list_firms, save_firm
from modules.user_profiles import (
    create_advisor_only,
    create_user,
    delete_user,
    get_profile,
    list_bds_reps,
    mark_password_set,
    promote_advisor_to_user,
    set_active,
    update_profile,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class FirmBody(BaseModel):
    name: str
    template_id: str | None = None
    bds_rep_id: str | None = None


class UserBody(BaseModel):
    email: str | None = None
    name: str
    role: str
    firm_id: str | None = None
    send_invite: bool = True


class UpdateUserBody(BaseModel):
    name: str | None = None
    firm_id: str | None = None


class ActiveBody(BaseModel):
    active: bool


class PromoteUserBody(BaseModel):
    email: str


# ── Firms ─────────────────────────────────────────────────────────────────────


@router.get("/firms")
async def get_firms(user: dict = Depends(require_bds_rep)):
    return await list_firms()


@router.post("/firms")
async def create_firm(body: FirmBody, user: dict = Depends(require_bds_rep)):
    data = body.model_dump()
    if not data.get("bds_rep_id"):
        data["bds_rep_id"] = user["user_id"]
    return await save_firm(data)


@router.get("/firms/{firm_id}")
async def get_firm_detail(firm_id: str, user: dict = Depends(require_bds_rep)):
    firm = await get_firm(firm_id)
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    return {"firm": firm, "users": await get_firm_users(firm_id)}


@router.put("/firms/{firm_id}")
async def update_firm(firm_id: str, body: FirmBody, user: dict = Depends(require_bds_rep)):
    existing = await get_firm(firm_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    data = {**existing, **body.model_dump(exclude_unset=True), "id": firm_id}
    return await save_firm(data)


@router.delete("/firms/{firm_id}", status_code=204)
async def remove_firm(firm_id: str, user: dict = Depends(require_bds_rep)):
    if await get_firm(firm_id) is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    await delete_firm(firm_id)
    return Response(status_code=204)


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/users/me")
async def get_me(user: dict = Depends(get_current_user)):
    profile = await get_profile(user["user_id"])
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    # Include firm name so the frontend doesn't need a separate firm fetch
    if profile.get("firm_id"):
        firm = await get_firm(profile["firm_id"])
        profile["firm_name"] = firm["name"] if firm else None
    else:
        profile["firm_name"] = None
    return profile


@router.post("/users/me/password-set")
async def confirm_password_set(user: dict = Depends(get_current_user)):
    profile = await mark_password_set(user["user_id"])
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.get("/users/bds-reps")
async def get_bds_reps(user: dict = Depends(require_bds_rep)):
    return await list_bds_reps()


@router.post("/users")
async def create_new_user(body: UserBody, user: dict = Depends(require_bds_rep)):
    try:
        if not body.send_invite:
            if not body.firm_id:
                raise ValueError("firm_id is required for advisor-only records.")
            if body.role != "financial_advisor":
                raise ValueError("Advisor-only records must have role 'financial_advisor'.")
            return await create_advisor_only(name=body.name, firm_id=body.firm_id)
        if not body.email:
            raise ValueError("email is required when send_invite is true.")
        return await create_user(
            email=body.email,
            name=body.name,
            role=body.role,
            firm_id=body.firm_id,
        )
    except Exception as exc:
        logger.error("Failed to create user: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/users/{user_id}")
async def update_user(
    user_id: str, body: UpdateUserBody, user: dict = Depends(require_bds_rep)
):
    profile = await update_profile(user_id, body.model_dump(exclude_unset=True))
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@router.patch("/users/{user_id}/active")
async def toggle_user_active(
    user_id: str, body: ActiveBody, user: dict = Depends(require_bds_rep)
):
    try:
        await set_active(user_id, body.active)
        return {"user_id": user_id, "active": body.active}
    except Exception as exc:
        logger.error("Failed to set active=%s for user %s: %s", body.active, user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/users/{user_id}/promote")
async def promote_user(
    user_id: str, body: PromoteUserBody, user: dict = Depends(require_bds_rep)
):
    try:
        return await promote_advisor_to_user(user_id, body.email.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to promote user %s: %s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/users/{user_id}", status_code=204)
async def remove_user(user_id: str, user: dict = Depends(require_bds_rep)):
    try:
        await delete_user(user_id)
    except Exception as exc:
        logger.error("Failed to delete user %s: %s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(status_code=204)
