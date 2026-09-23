import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.instagram_posts import SocialAccountNotFoundError, refresh_profile

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.post("/refresh/{social_account_id}")
async def refresh_account(social_account_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    try:
        social_account = await refresh_profile(social_account_id, db)
    except SocialAccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Instagram API error: {exc.response.text}") from exc

    return {
        "social_account_id": str(social_account.id),
        "username": social_account.username,
        "follower_count": social_account.follower_count,
    }
