import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CreatorProfile, SocialAccount, User
from app.models.enums import UserType
from app.services import instagram_oauth

router = APIRouter(prefix="/auth/instagram", tags=["instagram-oauth"])


@router.get("/connect")
def connect(state: str | None = None) -> RedirectResponse:
    return RedirectResponse(instagram_oauth.build_authorization_url(state=state))


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=error_description or error)
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        short_lived = await instagram_oauth.exchange_code_for_token(code)
        long_lived = await instagram_oauth.exchange_for_long_lived_token(short_lived["access_token"])
        profile = await instagram_oauth.fetch_profile(long_lived["access_token"])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Instagram API error: {exc.response.text}") from exc

    platform_user_id = str(profile["id"])
    username = profile["username"]
    follower_count = profile.get("followers_count")
    access_token = long_lived["access_token"]
    expires_in = long_lived.get("expires_in", 60 * 24 * 60 * 60)
    token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    social_account = db.execute(
        select(SocialAccount).where(
            SocialAccount.platform == "instagram",
            SocialAccount.platform_user_id == platform_user_id,
        )
    ).scalar_one_or_none()

    if social_account is not None:
        social_account.username = username
        social_account.access_token = access_token
        social_account.token_expires_at = token_expires_at
        social_account.is_active = True
        social_account.follower_count = follower_count
    else:
        user = User(
            email=f"instagram_{platform_user_id}@placeholder.creatorplatform.local",
            # OAuth-only account: no password login exists for it, so this is an
            # unusable placeholder rather than a real credential.
            password_hash=secrets.token_hex(32),
            user_type=UserType.creator,
        )
        db.add(user)
        db.flush()

        creator_profile = CreatorProfile(user_id=user.id, display_name=username)
        db.add(creator_profile)
        db.flush()

        social_account = SocialAccount(
            creator_id=creator_profile.id,
            platform="instagram",
            platform_user_id=platform_user_id,
            username=username,
            access_token=access_token,
            token_expires_at=token_expires_at,
            is_active=True,
            follower_count=follower_count,
        )
        db.add(social_account)

    db.commit()
    db.refresh(social_account)

    # Send the person to the dashboard, which reads these ids from the URL.
    return RedirectResponse(
        f"/app/dashboard.html?social_account_id={social_account.id}&creator_id={social_account.creator_id}"
    )
