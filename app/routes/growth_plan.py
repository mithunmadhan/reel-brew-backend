import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.langgraph_flows.growth_plan import CreatorNotFoundError, NoFeedbackFoundError, run_growth_plan
from app.services.gemini_client import GeminiAPIError

router = APIRouter(prefix="/growth-plan", tags=["growth-plan"])


@router.post("/generate/{creator_id}")
async def generate_growth_plan(creator_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    try:
        result = await run_in_threadpool(run_growth_plan, creator_id, db)
    except (CreatorNotFoundError, NoFeedbackFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "growth_plan_id": str(result["growth_plan_id"]),
        "creator_id": str(creator_id),
        "plan_text": result["plan_text"],
        "based_on_post_count": result["based_on_post_count"],
        "generated_at": result["generated_at"].isoformat(),
    }
