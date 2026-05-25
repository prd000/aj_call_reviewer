from fastapi import Depends, HTTPException, Header
from modules.supabase_client import get_client


async def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")
    try:
        client = await get_client()
        resp = await client.auth.get_user(token)
        auth_user = resp.user
        if auth_user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    client = await get_client()
    profile_resp = await (
        client.table("profiles").select("*").eq("id", str(auth_user.id)).execute()
    )
    if not profile_resp.data:
        raise HTTPException(status_code=401, detail="No profile found")
    p = profile_resp.data[0]
    if not p["is_active"]:
        raise HTTPException(status_code=403, detail="Account deactivated")
    return {
        "user_id": str(auth_user.id),
        "role": p["role"],
        "firm_id": p.get("firm_id"),
        "name": p["name"],
    }


def require_bds_rep(user: dict = Depends(get_current_user)):
    if user["role"] != "bds_rep":
        raise HTTPException(status_code=403, detail="BDS reps only")
    return user
