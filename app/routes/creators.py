import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.langgraph_flows.matching import BrandNotFoundError, CreatorNotFoundError, run_matching_flow
from app.models import Brand, Match
from app.routes.match_response import match_to_dict, partition_and_sort
from app.services.gemini_client import GeminiAPIError

router = APIRouter(prefix="/creators", tags=["creators"])


@router.get("/{creator_id}/suggested-brands")
async def suggested_brands(creator_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    brand_ids = db.execute(select(Brand.id)).scalars().all()

    existing_matches = db.execute(select(Match).where(Match.creator_id == creator_id)).scalars().all()
    matches_by_brand = {m.brand_id: m for m in existing_matches}

    all_results: list[dict] = []

    for brand_id in brand_ids:
        existing = matches_by_brand.get(brand_id)
        if existing is not None:
            all_results.append(
                match_to_dict(
                    existing.id, "brand_id", existing.brand_id, existing.match_score, existing.match_reasoning,
                    existing.is_non_obvious, existing.status.value,
                )
            )
            continue

        try:
            result = await run_in_threadpool(run_matching_flow, creator_id, brand_id, db)
        except (CreatorNotFoundError, BrandNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GeminiAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        all_results.append(
            match_to_dict(
                result["match_id"], "brand_id", brand_id, result["match_score"], result["match_reasoning"],
                result["is_non_obvious"], result["status"],
            )
        )

    suggested, rejected_count = partition_and_sort(all_results)

    return {
        "creator_id": str(creator_id),
        "matches": suggested,
        "rejected_count": rejected_count,
    }
