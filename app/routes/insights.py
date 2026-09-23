import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.instagram_insights import SocialAccountNotFoundError, fetch_audience_insights

router = APIRouter(prefix="/insights", tags=["insights"])


@router.post("/sync/{social_account_id}")
async def sync_insights(social_account_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    try:
        demographics = await fetch_audience_insights(social_account_id, db)
    except SocialAccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Instagram API error: {exc.response.text}") from exc

    return {"social_account_id": str(social_account_id), "audience_demographics": demographics}
