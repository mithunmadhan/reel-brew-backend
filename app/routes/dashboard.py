import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIFeedback, Brand, GrowthPlan, Post, SocialAccount

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _parse_structured(notes: str | None) -> dict | None:
    if not notes:
        return None
    try:
        value = json.loads(notes)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


@router.get("/{social_account_id}")
def get_dashboard(social_account_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """Read-only snapshot for the web dashboard. Never returns the access token."""
    account = db.get(SocialAccount, social_account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")

    posts = db.execute(
        select(Post).where(Post.social_account_id == account.id).order_by(Post.posted_at.desc())
    ).scalars().all()

    latest_feedback: dict[uuid.UUID, AIFeedback] = {}
    if posts:
        rows = db.execute(
            select(AIFeedback)
            .where(AIFeedback.post_id.in_([p.id for p in posts]))
            .order_by(AIFeedback.generated_at.asc())
        ).scalars().all()
        for fb in rows:
            latest_feedback[fb.post_id] = fb  # later rows overwrite earlier -> latest wins

    plan = db.execute(
        select(GrowthPlan)
        .where(GrowthPlan.creator_id == account.creator_id)
        .order_by(GrowthPlan.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    brands = db.execute(select(Brand)).scalars().all()

    return {
        "account": {
            "social_account_id": str(account.id),
            "creator_id": str(account.creator_id),
            "platform": account.platform,
            "username": account.username,
            "follower_count": account.follower_count,
            "audience_demographics": account.audience_demographics,
        },
        "posts": [
            {
                "post_id": str(p.id),
                "caption": p.caption,
                "media_type": p.media_type,
                "like_count": p.like_count,
                "comments_count": p.comments_count,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "feedback_text": latest_feedback[p.id].feedback_text if p.id in latest_feedback else None,
                "feedback_structured": (
                    _parse_structured(latest_feedback[p.id].sentiment_notes) if p.id in latest_feedback else None
                ),
            }
            for p in posts
        ],
        "growth_plan": (
            {
                "plan_text": plan.plan_text,
                "based_on_post_count": plan.based_on_post_count,
                "generated_at": plan.generated_at.isoformat() if plan.generated_at else None,
            }
            if plan
            else None
        ),
        "brands": [
            {"brand_id": str(b.id), "company_name": b.company_name, "industry_category": b.industry_category}
            for b in brands
        ],
    }
