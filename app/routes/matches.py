import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.langgraph_flows.matching import BrandNotFoundError, CreatorNotFoundError, run_matching_flow
from app.services.gemini_client import GeminiAPIError

router = APIRouter(prefix="/matches", tags=["matches"])


class MatchCreateRequest(BaseModel):
    creator_id: uuid.UUID
    brand_id: uuid.UUID


@router.post("/create")
async def create_match(payload: MatchCreateRequest, db: Session = Depends(get_db)) -> dict:
    try:
        result = await run_in_threadpool(run_matching_flow, payload.creator_id, payload.brand_id, db)
    except (CreatorNotFoundError, BrandNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}") from exc

    return {
        "match_id": str(result["match_id"]),
        "creator_id": str(payload.creator_id),
        "brand_id": str(payload.brand_id),
        "match_score": result["match_score"],
        "match_reasoning": result["match_reasoning"],
        "is_non_obvious": result["is_non_obvious"],
        "status": result["status"],
    }
