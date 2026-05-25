import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from modules.auth import get_current_user, require_bds_rep
from modules.firms import delete_firm, get_firm, get_firm_users, list_firms, save_firm
from modules.user_profiles import (
    create_user,
    delete_user,
    get_profile,
    list_bds_reps,
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
    email: str
    name: str
    role: str
    firm_id: str | None = None


class UpdateUserBody(BaseModel):
    name: str | None = None
    firm_id: str | None = None


class ActiveBody(BaseModel):
    active: bool


# ── Firms ─────────────────────────────────────────────────────────────────────


@router.get("/firms")
def get_firms(user: dict = Depends(require_bds_rep)):
    return list_firms()


@router.post("/firms")
def create_firm(body: FirmBody, user: dict = Depends(require_bds_rep)):
    return save_firm(body.model_dump())


@router.get("/firms/{firm_id}")
def get_firm_detail(firm_id: str, user: dict = Depends(require_bds_rep)):
    firm = get_firm(firm_id)
    if firm is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    return {"firm": firm, "users": get_firm_users(firm_id)}


@router.put("/firms/{firm_id}")
def update_firm(firm_id: str, body: FirmBody, user: dict = Depends(require_bds_rep)):
    existing = get_firm(firm_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    data = {**existing, **body.model_dump(exclude_unset=True), "id": firm_id}
    return save_firm(data)


@router.delete("/firms/{firm_id}", status_code=204)
def remove_firm(firm_id: str, user: dict = Depends(require_bds_rep)):
    if get_firm(firm_id) is None:
        raise HTTPException(status_code=404, detail="Firm not found")
    delete_firm(firm_id)
    return Response(status_code=204)


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/users/me")
def get_me(user: dict = Depends(get_current_user)):
    profile = get_profile(user["user_id"])
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    # Include firm name so the frontend doesn't need a separate firm fetch
    if profile.get("firm_id"):
        firm = get_firm(profile["firm_id"])
        profile["firm_name"] = firm["name"] if firm else None
    else:
        profile["firm_name"] = None
    return profile


@router.get("/users/bds-reps")
def get_bds_reps(user: dict = Depends(require_bds_rep)):
    return list_bds_reps()


@router.post("/users")
def create_new_user(body: UserBody, user: dict = Depends(require_bds_rep)):
    try:
        return create_user(
            email=body.email,
            name=body.name,
            role=body.role,
            firm_id=body.firm_id,
        )
    except Exception as exc:
        logger.error("Failed to create user %s: %s", body.email, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/users/{user_id}")
def update_user(
    user_id: str, body: UpdateUserBody, user: dict = Depends(require_bds_rep)
):
    profile = update_profile(user_id, body.model_dump(exclude_unset=True))
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@router.patch("/users/{user_id}/active")
def toggle_user_active(
    user_id: str, body: ActiveBody, user: dict = Depends(require_bds_rep)
):
    try:
        set_active(user_id, body.active)
        return {"user_id": user_id, "active": body.active}
    except Exception as exc:
        logger.error("Failed to set active=%s for user %s: %s", body.active, user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/users/{user_id}", status_code=204)
def remove_user(user_id: str, user: dict = Depends(require_bds_rep)):
    try:
        delete_user(user_id)
    except Exception as exc:
        logger.error("Failed to delete user %s: %s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(status_code=204)
