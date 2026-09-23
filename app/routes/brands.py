import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.langgraph_flows.matching import BrandNotFoundError, CreatorNotFoundError, run_matching_flow
from app.models import Brand, CreatorProfile, Match, User
from app.models.enums import UserType
from app.routes.match_response import match_to_dict, partition_and_sort
from app.services.gemini_client import GeminiAPIError

router = APIRouter(prefix="/brands", tags=["brands"])


class BrandTestCreate(BaseModel):
    company_name: str
    industry_category: str | None = None
    budget_range_min: int | None = None
    budget_range_max: int | None = None


@router.post("/test")
def create_test_brand(payload: BrandTestCreate, db: Session = Depends(get_db)) -> dict:
    """Create a placeholder Brand (+ linked User) for exercising the matching engine
    before real brand signup exists. Not for production use.
    """
    user = User(
        email=f"brand_{uuid.uuid4().hex}@placeholder.creatorplatform.local",
        # Test/admin-created account: no password login exists for it, so this is an
        # unusable placeholder rather than a real credential.
        password_hash=secrets.token_hex(32),
        user_type=UserType.brand,
    )
    db.add(user)
    db.flush()

    brand = Brand(
        user_id=user.id,
        company_name=payload.company_name,
        industry_category=payload.industry_category,
        budget_range_min=payload.budget_range_min,
        budget_range_max=payload.budget_range_max,
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)

    return {
        "brand_id": str(brand.id),
        "user_id": str(user.id),
        "company_name": brand.company_name,
        "industry_category": brand.industry_category,
        "budget_range_min": brand.budget_range_min,
        "budget_range_max": brand.budget_range_max,
    }


@router.get("/{brand_id}/suggested-creators")
async def suggested_creators(brand_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    creator_ids = db.execute(select(CreatorProfile.id)).scalars().all()

    existing_matches = db.execute(select(Match).where(Match.brand_id == brand_id)).scalars().all()
    matches_by_creator = {m.creator_id: m for m in existing_matches}

    all_results: list[dict] = []

    for creator_id in creator_ids:
        existing = matches_by_creator.get(creator_id)
        if existing is not None:
            all_results.append(
                match_to_dict(
                    existing.id, "creator_id", existing.creator_id, existing.match_score, existing.match_reasoning,
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
                result["match_id"], "creator_id", creator_id, result["match_score"], result["match_reasoning"],
                result["is_non_obvious"], result["status"],
            )
        )

    suggested, rejected_count = partition_and_sort(all_results)

    return {
        "brand_id": str(brand_id),
        "matches": suggested,
        "rejected_count": rejected_count,
    }
