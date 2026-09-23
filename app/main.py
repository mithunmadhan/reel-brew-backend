import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import (
    accounts,
    admin,
    brands,
    chat,
    creators,
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500"],
    allow_credentials=True,
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


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.app_name} is running"}
