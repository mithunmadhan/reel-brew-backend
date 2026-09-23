import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Post, SocialAccount
from app.services.instagram_oauth import fetch_profile

MEDIA_URL = "https://graph.instagram.com/me/media"
MEDIA_FIELDS = "id,caption,media_type,media_url,timestamp,like_count,comments_count"


class SocialAccountNotFoundError(Exception):
    pass


async def _fetch_all_media(access_token: str) -> list[dict]:
    """Fetch every page of the account's media from the Instagram Graph API."""
    media: list[dict] = []
    url: str | None = MEDIA_URL
    params: dict | None = {"fields": MEDIA_FIELDS, "access_token": access_token}

    async with httpx.AsyncClient(timeout=10) as client:
        while url:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            media.extend(payload.get("data", []))
            url = payload.get("paging", {}).get("next")
            params = None  # the 'next' url already carries all query params

    return media


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


async def fetch_and_save_posts(social_account_id: uuid.UUID, db: Session) -> int:
    """Fetch the account's media from Instagram and insert any posts not yet stored.

    Returns the number of new posts saved.
    """
    social_account = db.get(SocialAccount, social_account_id)
    if social_account is None:
        raise SocialAccountNotFoundError(f"No social_account with id {social_account_id}")

    media_items = await _fetch_all_media(social_account.access_token)

    existing_post_ids = set(
        db.execute(select(Post.platform_post_id).where(Post.social_account_id == social_account_id)).scalars()
    )

    fetched_at = datetime.now(timezone.utc)
    new_posts_count = 0

    for item in media_items:
        platform_post_id = str(item["id"])
        if platform_post_id in existing_post_ids:
            continue

        db.add(
            Post(
                social_account_id=social_account_id,
                platform_post_id=platform_post_id,
                caption=item.get("caption"),
                media_url=item.get("media_url"),
                media_type=item.get("media_type"),
                like_count=item.get("like_count"),
                comments_count=item.get("comments_count"),
                posted_at=_parse_timestamp(item.get("timestamp")),
                fetched_at=fetched_at,
            )
        )
        existing_post_ids.add(platform_post_id)
        new_posts_count += 1

    db.commit()
    return new_posts_count


async def refresh_profile(social_account_id: uuid.UUID, db: Session) -> SocialAccount:
    """Re-fetch the account's profile from Instagram using its existing saved access
    token, and update follower_count with the fresh value.
    """
    social_account = db.get(SocialAccount, social_account_id)
    if social_account is None:
        raise SocialAccountNotFoundError(f"No social_account with id {social_account_id}")

    profile = await fetch_profile(social_account.access_token)
    social_account.follower_count = profile.get("followers_count")
    db.commit()
    db.refresh(social_account)
    return social_account
