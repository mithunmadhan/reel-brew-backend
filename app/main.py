import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routes import (
    accounts,
    admin,
    brands,
    chat,
    creators,
    dashboard,
    feedback,
    growth_plan,
    health,
    insights,
    instagram_auth,
    matches,
    posts,
)
from app.services.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Demo setup: no cookies/credentials are used, so any origin may call the API.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(instagram_auth.router)
app.include_router(posts.router)
app.include_router(feedback.router)
app.include_router(insights.router)
app.include_router(brands.router)
app.include_router(matches.router)
app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(growth_plan.router)
app.include_router(chat.router)
app.include_router(creators.router)
app.include_router(dashboard.router)


# Serve the landing page + dashboard from the same service (same origin as the API).
_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.app_name} is running"}
