import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.langgraph_flows.chat import CreatorNotFoundError, run_chat
from app.models import ChatMessage
from app.services.gemini_client import GeminiAPIError

router = APIRouter(prefix="/chat", tags=["chat"])

HISTORY_WINDOW = 10


class ChatMessageRequest(BaseModel):
    message: str


@router.post("/{creator_id}/message")
async def send_chat_message(
    creator_id: uuid.UUID, payload: ChatMessageRequest, db: Session = Depends(get_db)
) -> dict:
    try:
        result = await run_in_threadpool(run_chat, creator_id, payload.message, db)
    except CreatorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GeminiAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    history_rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.creator_id == creator_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_WINDOW)
    ).scalars().all()

    return {
        "creator_id": str(creator_id),
        "reply": result["assistant_reply"],
        "history": [
            {"role": m.role.value, "message_text": m.message_text, "created_at": m.created_at.isoformat()}
            for m in reversed(history_rows)
        ],
    }
