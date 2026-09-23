import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.langgraph_flows.growth_coaching import PostNotFoundError, VideoProcessingError, run_growth_coaching
from app.services.gemini_client import GeminiAPIError

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("/generate/{post_id}")
async def generate_feedback(post_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    try:
        result = await run_in_threadpool(run_growth_coaching, post_id, db)
    except PostNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (GeminiAPIError, VideoProcessingError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "post_id": str(post_id),
        "ai_feedback_id": str(result["ai_feedback_id"]),
        "feedback_text": result["feedback_text"],
        "model_used": "gemini-2.5-flash",
    }
