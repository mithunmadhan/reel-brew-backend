import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import SocialAccount

INSIGHTS_URL_TEMPLATE = "https://graph.instagram.com/{ig_user_id}/insights"

# `follower_demographics` (metric_type=total_value) is the current Instagram Platform API
# metric for audience breakdowns — it replaced the deprecated audience_gender_age /
# audience_city / audience_country metrics. age+gender are requested together as a combined
# breakdown (the documented replacement for the old audience_gender_age metric); city and
# country are requested separately since they're independent breakdown dimensions.
DEMOGRAPHIC_BREAKDOWNS = {
    "age_gender": "age,gender",
    "city": "city",
    "country": "country",
}


class SocialAccountNotFoundError(Exception):
    pass


async def _fetch_breakdown(client: httpx.AsyncClient, ig_user_id: str, access_token: str, breakdown: str) -> dict:
    params = {
        "metric": "follower_demographics",
        "period": "lifetime",
        "metric_type": "total_value",
        "breakdown": breakdown,
        "timeframe": "this_month",
        "access_token": access_token,
    }
    response = await client.get(INSIGHTS_URL_TEMPLATE.format(ig_user_id=ig_user_id), params=params)
    response.raise_for_status()
    payload = response.json()

    data = payload.get("data") or []
    if not data:
        return {}

    breakdowns = data[0].get("total_value", {}).get("breakdowns") or []
    if not breakdowns:
        return {}

    return breakdowns[0]


async def fetch_audience_insights(social_account_id: uuid.UUID, db: Session) -> dict:
    """Fetch follower demographic insights (age+gender, city, country) and persist them
    onto the social_account row. Returns the saved audience_demographics dict.
    """
    social_account = db.get(SocialAccount, social_account_id)
    if social_account is None:
        raise SocialAccountNotFoundError(f"No social_account with id {social_account_id}")

    async with httpx.AsyncClient(timeout=10) as client:
        demographics = {
            key: await _fetch_breakdown(client, social_account.platform_user_id, social_account.access_token, breakdown)
            for key, breakdown in DEMOGRAPHIC_BREAKDOWNS.items()
        }

    social_account.audience_demographics = demographics
    social_account.demographics_synced_at = datetime.now(timezone.utc)
    db.commit()

    return demographics
