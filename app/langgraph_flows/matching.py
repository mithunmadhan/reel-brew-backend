import uuid
from statistics import mean
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brand, CreatorProfile, Match, Post, SocialAccount
from app.models.enums import MatchStatus
from app.services.gemini_client import generate_json

MAX_SAMPLE_CAPTIONS = 10
# Rough heuristic: treat a ~6% (likes+comments)/followers rate as a "perfect" 1.0 engagement
# score, scaling linearly below that and capping at 1.0 above it. No real benchmark data yet
# (see engagement_quality docstring) — revisit once real engagement-rate baselines exist.
ENGAGEMENT_RATE_FOR_MAX_SCORE = 0.06


class CreatorNotFoundError(Exception):
    pass


class BrandNotFoundError(Exception):
    pass


class MatchingState(TypedDict, total=False):
    creator_id: uuid.UUID
    brand_id: uuid.UUID
    social_account_id: uuid.UUID | None
    follower_count: int | None
    fraud_failed: bool
    fraud_reason: str | None
    audience_fit_score: float
    audience_fit_reason: str
    engagement_score: float
    engagement_reason: str
    content_fit_score: float
    content_fit_reason: str
    is_non_obvious: bool
    match_id: uuid.UUID
    match_score: float | None
    match_reasoning: str
    status: str


def _summarize_breakdown(demographics: dict, key: str, limit: int = 5) -> str:
    breakdown = (demographics or {}).get(key) or {}
    results = breakdown.get("results") or []
    if not results:
        return "(no data)"

    ranked = sorted(results, key=lambda r: r.get("value", 0), reverse=True)[:limit]
    return ", ".join(f"{'/'.join(map(str, r.get('dimension_values', [])))}: {r.get('value')}" for r in ranked)


def _build_audience_fit_prompt(demographics: dict, industry_category: str | None) -> str:
    return (
        "You are evaluating whether an Instagram creator's audience demographics plausibly "
        "fit a brand's target industry for an influencer partnership.\n\n"
        f"Brand industry category: {industry_category or 'unspecified'}\n\n"
        f"Audience by country (top values, follower counts): {_summarize_breakdown(demographics, 'country')}\n"
        f"Audience by city (top values, follower counts): {_summarize_breakdown(demographics, 'city')}\n\n"
        "Score from 0.0 to 1.0 how well this audience could plausibly fit the brand's industry "
        "(1.0 = excellent fit, 0.0 = poor fit). Respond ONLY with JSON in this exact shape: "
        '{"score": <number 0-1>, "reason": "<one or two sentence explanation>"}'
    )


def _build_content_fit_prompt(captions: list[str], company_name: str, industry_category: str | None) -> str:
    if captions:
        caption_block = "\n".join(f"{i + 1}. {caption}" for i, caption in enumerate(captions))
    else:
        caption_block = "(no captions available)"

    return (
        "You are evaluating content/style fit between an Instagram creator and a brand for an "
        "influencer partnership.\n\n"
        f"Brand: {company_name}, industry category: {industry_category or 'unspecified'}\n\n"
        f"Sample of the creator's recent post captions:\n{caption_block}\n\n"
        "Judge whether this brand's industry is a genuine content/style fit for this creator "
        "based on these captions. Also specifically consider whether this could be a "
        "values-based 'non-obvious' fit — i.e. not a literal topic match, but aligned via tone, "
        "values, lifestyle, or audience sensibility.\n\n"
        "Real reference examples of successful non-obvious matches:\n"
        "1. A food delivery app partnered with a wildlife/snake handler creator and saw 50x "
        "normal engagement — both audiences valued unexpected, adventurous content despite no "
        "literal topic overlap.\n"
        "2. A fried chicken brand collaborated with creators known for imitating a rival burger "
        "chain's jingle, driving a 16x engagement lift, by leaning into playful cultural humor "
        "rather than avoiding the connection.\n"
        "3. A telehealth brand partnered with a comedy creator and saw +52% engagement over her "
        "average, by fitting her authentic comedic format rather than forcing serious health "
        "messaging.\n"
        "4. Audience overlaps are often not obvious from category alone: 84% of luxury-fashion "
        "audiences also follow sports content, and male interest in beauty content has risen "
        "21% since 2018.\n\n"
        "These successful matches worked by preserving the creator's authentic existing "
        "format/style, not by forcing the brand's message into an unnatural mismatch. Use this "
        "principle, not just topic similarity, when judging content_fit and is_non_obvious.\n\n"
        "Respond ONLY with JSON in this exact shape: "
        '{"score": <number 0-1>, "reason": "<one to three sentence explanation>", '
        '"is_non_obvious": <true or false>}'
    )


def build_graph(db: Session):
    def fraud_check(state: MatchingState) -> dict:
        creator = db.get(CreatorProfile, state["creator_id"])
        if creator is None:
            raise CreatorNotFoundError(f"No creator_profile with id {state['creator_id']}")
        brand = db.get(Brand, state["brand_id"])
        if brand is None:
            raise BrandNotFoundError(f"No brand with id {state['brand_id']}")

        social_account = db.execute(
            select(SocialAccount)
            .where(SocialAccount.creator_id == state["creator_id"])
            .order_by(SocialAccount.is_active.desc(), SocialAccount.connected_at.desc())
        ).scalars().first()

        if social_account is None:
            return {"fraud_failed": True, "fraud_reason": "Creator has no connected social account."}

        follower_count = social_account.follower_count
        if not follower_count:
            return {
                "social_account_id": social_account.id,
                "follower_count": follower_count,
                "fraud_failed": True,
                "fraud_reason": (
                    "Follower count is missing or zero — data-quality issue, cannot verify "
                    "audience authenticity."
                ),
            }

        return {"social_account_id": social_account.id, "follower_count": follower_count, "fraud_failed": False}

    def reject_match(state: MatchingState) -> dict:
        match = Match(
            creator_id=state["creator_id"],
            brand_id=state["brand_id"],
            match_score=None,
            match_reasoning=state["fraud_reason"],
            is_non_obvious=False,
            status=MatchStatus.rejected,
        )
        db.add(match)
        db.commit()
        db.refresh(match)
        return {
            "match_id": match.id,
            "match_score": match.match_score,
            "match_reasoning": match.match_reasoning,
            "is_non_obvious": match.is_non_obvious,
            "status": match.status.value,
        }

    def audience_fit(state: MatchingState) -> dict:
        social_account = db.get(SocialAccount, state["social_account_id"])
        brand = db.get(Brand, state["brand_id"])
        prompt = _build_audience_fit_prompt(social_account.audience_demographics or {}, brand.industry_category)
        result = generate_json(prompt)
        return {
            "audience_fit_score": float(result["score"]),
            "audience_fit_reason": result["reason"],
        }

    def engagement_quality(state: MatchingState) -> dict:
        """No engagement-rate benchmarks exist yet, so this uses a simple heuristic:
        (avg likes + avg comments) / followers, scaled against ENGAGEMENT_RATE_FOR_MAX_SCORE.
        """
        posts = db.execute(
            select(Post).where(Post.social_account_id == state["social_account_id"])
        ).scalars().all()

        if not posts:
            return {"engagement_score": 0.0, "engagement_reason": "No posts found to evaluate engagement."}

        avg_likes = mean(post.like_count or 0 for post in posts)
        avg_comments = mean(post.comments_count or 0 for post in posts)
        follower_count = state["follower_count"]
        engagement_rate = (avg_likes + avg_comments) / follower_count if follower_count else 0.0
        score = min(engagement_rate / ENGAGEMENT_RATE_FOR_MAX_SCORE, 1.0)

        reason = (
            f"Average {avg_likes:.1f} likes and {avg_comments:.1f} comments across {len(posts)} posts, "
            f"against {follower_count} followers (~{engagement_rate:.2%} engagement rate)."
        )
        return {"engagement_score": score, "engagement_reason": reason}

    def content_fit(state: MatchingState) -> dict:
        captions = db.execute(
            select(Post.caption)
            .where(Post.social_account_id == state["social_account_id"])
            .order_by(Post.posted_at.desc())
            .limit(MAX_SAMPLE_CAPTIONS)
        ).scalars().all()
        captions = [c for c in captions if c]

        brand = db.get(Brand, state["brand_id"])
        prompt = _build_content_fit_prompt(captions, brand.company_name, brand.industry_category)
        result = generate_json(prompt)
        return {
            "content_fit_score": float(result["score"]),
            "content_fit_reason": result["reason"],
            "is_non_obvious": bool(result["is_non_obvious"]),
        }

    def combine_score(state: MatchingState) -> dict:
        scores = [state["audience_fit_score"], state["engagement_score"], state["content_fit_score"]]
        match_score = sum(scores) / len(scores)
        match_reasoning = "\n".join(
            [
                f"Audience fit ({state['audience_fit_score']:.2f}): {state['audience_fit_reason']}",
                f"Engagement quality ({state['engagement_score']:.2f}): {state['engagement_reason']}",
                f"Content fit ({state['content_fit_score']:.2f}): {state['content_fit_reason']}",
            ]
        )

        match = Match(
            creator_id=state["creator_id"],
            brand_id=state["brand_id"],
            match_score=match_score,
            match_reasoning=match_reasoning,
            is_non_obvious=state["is_non_obvious"],
            status=MatchStatus.suggested,
        )
        db.add(match)
        db.commit()
        db.refresh(match)

        return {
            "match_id": match.id,
            "match_score": match.match_score,
            "match_reasoning": match.match_reasoning,
            "is_non_obvious": match.is_non_obvious,
            "status": match.status.value,
        }

    graph = StateGraph(MatchingState)
    graph.add_node("fraud_check", fraud_check)
    graph.add_node("reject_match", reject_match)
    graph.add_node("audience_fit", audience_fit)
    graph.add_node("engagement_quality", engagement_quality)
    graph.add_node("content_fit", content_fit)
    graph.add_node("combine_score", combine_score)

    graph.add_edge(START, "fraud_check")
    graph.add_conditional_edges(
        "fraud_check",
        lambda state: "reject_match" if state.get("fraud_failed") else "audience_fit",
        {"reject_match": "reject_match", "audience_fit": "audience_fit"},
    )
    graph.add_edge("reject_match", END)
    graph.add_edge("audience_fit", "engagement_quality")
    graph.add_edge("engagement_quality", "content_fit")
    graph.add_edge("content_fit", "combine_score")
    graph.add_edge("combine_score", END)

    return graph.compile()


def run_matching_flow(creator_id: uuid.UUID, brand_id: uuid.UUID, db: Session) -> MatchingState:
    graph = build_graph(db)
    return graph.invoke({"creator_id": creator_id, "brand_id": brand_id})
