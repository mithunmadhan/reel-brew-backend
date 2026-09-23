from urllib.parse import urlencode

import httpx

from app.config import get_settings

# Instagram API with Instagram Login (Business/Creator accounts) — not Facebook Login.
AUTHORIZATION_URL = "https://www.instagram.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"
GRAPH_BASE_URL = "https://graph.instagram.com"

SCOPES = (
    "instagram_business_basic",
    "instagram_business_manage_insights",
    "instagram_business_manage_comments",
)


def build_authorization_url(state: str | None = None) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.instagram_redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
    }
    if state:
        params["state"] = state
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> dict:
    """Exchange the authorization code for a short-lived (1 hour) access token."""
    settings = get_settings()
    data = {
        "client_id": settings.meta_app_id,
        "client_secret": settings.meta_app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": settings.instagram_redirect_uri,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(ACCESS_TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


async def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    """Exchange a short-lived token for a long-lived (60 day) access token."""
    settings = get_settings()
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": settings.meta_app_secret,
        "access_token": short_lived_token,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(LONG_LIVED_TOKEN_URL, params=params)
    response.raise_for_status()
    return response.json()


async def fetch_profile(access_token: str) -> dict:
    """Fetch the connected account's basic profile (id, username, followers_count)."""
    params = {"fields": "id,username,followers_count", "access_token": access_token}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{GRAPH_BASE_URL}/me", params=params)
    response.raise_for_status()
    return response.json()
