import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.langgraph_flows.growth_coaching import run_growth_coaching
from app.langgraph_flows.growth_plan import NoFeedbackFoundError, run_growth_plan
from app.models import AIFeedback, GrowthPlan, Post, SocialAccount
from app.services.instagram_insights import fetch_audience_insights
from app.services.instagram_posts import fetch_and_save_posts, refresh_profile

logger = logging.getLogger(__name__)

FEEDBACK_BATCH_LIMIT = 5
GROWTH_PLAN_MIN_INTERVAL = timedelta(hours=24)
INSIGHTS_SYNC_INTERVAL = timedelta(days=7)


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite round-trips strip tzinfo; normalize so interval comparisons are safe."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _analyze_unanalyzed_posts(social_account_id: uuid.UUID, db: Session) -> int:
    """Run growth-coaching feedback for this account's posts that have no ai_feedback row
    yet, capped at the FEEDBACK_BATCH_LIMIT most recent — the rest get picked up next run.
    Each post is isolated so one bad post doesn't cost the others in the same batch.
    """
    post_ids = db.execute(
        select(Post.id)
        .outerjoin(AIFeedback, AIFeedback.post_id == Post.id)
        .where(Post.social_account_id == social_account_id)
        .where(AIFeedback.id.is_(None))
        .order_by(Post.posted_at.desc())
        .limit(FEEDBACK_BATCH_LIMIT)
    ).scalars().all()

    analyzed = 0
    for post_id in post_ids:
        try:
            run_growth_coaching(post_id, db)
            analyzed += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to generate feedback for post %s", post_id)

    return analyzed


def _generate_growth_plan_if_due(creator_id: uuid.UUID, db: Session) -> bool:
    """Generate a fresh growth plan if the creator has none, or their latest one is more
    than GROWTH_PLAN_MIN_INTERVAL old.
    """
    latest_generated_at = db.execute(
        select(GrowthPlan.generated_at)
        .where(GrowthPlan.creator_id == creator_id)
        .order_by(GrowthPlan.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if latest_generated_at is not None:
        if datetime.now(timezone.utc) - _as_aware_utc(latest_generated_at) < GROWTH_PLAN_MIN_INTERVAL:
            return False

    try:
        run_growth_plan(creator_id, db)
    except NoFeedbackFoundError:
        # Nothing to synthesize yet — not a failure, just not due.
        return False

    return True


async def _refresh_insights_if_due(social_account: SocialAccount, db: Session) -> bool:
    """Refresh audience_demographics at most once every INSIGHTS_SYNC_INTERVAL per account."""
    last_synced = social_account.demographics_synced_at
    if last_synced is not None and datetime.now(timezone.utc) - _as_aware_utc(last_synced) < INSIGHTS_SYNC_INTERVAL:
        return False

    await fetch_audience_insights(social_account.id, db)
    return True


async def sync_all_active_accounts(db: Session) -> dict:
    """Sync posts + profile for every active social_account, then opportunistically run
    feedback generation, a growth-plan refresh, and an audience-insights refresh for each.

    Every account, and each of these follow-up steps per account, is isolated in its own
    try/except: one failure (expired token, API error, etc.) never stops the others or
    affects other creators.
    """
    social_account_ids = db.execute(
        select(SocialAccount.id).where(SocialAccount.is_active.is_(True))
    ).scalars().all()

    succeeded = 0
    failed = 0
    posts_analyzed = 0
    growth_plans_generated = 0
    insights_refreshed = 0

    for social_account_id in social_account_ids:
        try:
            await fetch_and_save_posts(social_account_id, db)
            await refresh_profile(social_account_id, db)
            succeeded += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to sync social_account %s", social_account_id)
            failed += 1
            continue

        social_account = db.get(SocialAccount, social_account_id)
        if social_account is None:
            continue

        try:
            posts_analyzed += _analyze_unanalyzed_posts(social_account_id, db)
        except Exception:
            db.rollback()
            logger.exception("Failed to run feedback analysis for social_account %s", social_account_id)

        try:
            if _generate_growth_plan_if_due(social_account.creator_id, db):
                growth_plans_generated += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to check/generate growth plan for creator %s", social_account.creator_id)

        try:
            if await _refresh_insights_if_due(social_account, db):
                insights_refreshed += 1
        except Exception:
            db.rollback()
            logger.exception("Failed to refresh insights for social_account %s", social_account_id)

    logger.info(
        "sync_all_active_accounts complete: %d succeeded, %d failed, %d posts analyzed, "
        "%d growth plans generated, %d insights refreshed",
        succeeded,
        failed,
        posts_analyzed,
        growth_plans_generated,
        insights_refreshed,
    )
    return {
        "succeeded": succeeded,
        "failed": failed,
        "posts_analyzed": posts_analyzed,
        "growth_plans_generated": growth_plans_generated,
        "insights_refreshed": insights_refreshed,
    }
