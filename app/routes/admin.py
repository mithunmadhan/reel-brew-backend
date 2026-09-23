from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.account_sync import sync_all_active_accounts

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/sync-all")
async def sync_all(db: Session = Depends(get_db)) -> dict:
    """Manually trigger sync_all_active_accounts immediately, without waiting for the
    scheduled job.
    """
    return await sync_all_active_accounts(db)
