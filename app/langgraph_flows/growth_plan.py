import uuid
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AIFeedback, CreatorProfile, GrowthPlan, Post, SocialAccount
from app.services.gemini_client import generate_text

MODEL_NAME = "gemini-2.5-flash"
# Cap the prompt to the most recent N feedback notes rather than every one ever generated.
MAX_FEEDBACK_SAMPLE = 40


class CreatorNotFoundError(Exception):
    pass


class NoFeedbackFoundError(Exception):
    pass


class GrowthPlanState(TypedDict, total=False):
    creator_id: uuid.UUID
    feedback_texts: list[str]
    post_count: int
    plan_text: str
    growth_plan_id: uuid.UUID
    based_on_post_count: int
    generated_at: datetime


def _build_synthesis_prompt(feedback_texts: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(feedback_texts))
    return (
        "You are a social media growth coach. Below are individual, per-post AI feedback "
        f"notes previously generated for one creator, covering {len(feedback_texts)} posts.\n\n"
        f"{numbered}\n\n"
        "Identify recurring patterns across these notes, then write ONE holistic growth "
        "roadmap for this creator with exactly these three sections:\n"
        "1. What's working well\n"
        "2. What to fix\n"
        "3. 3 concrete next steps\n\n"
        "Ground every point in a specific detail, example, or quote pulled from the notes "
        "above (a caption phrase, a visual element, a recurring subject) — not generic social "
        "media advice that would apply to any creator regardless of what they post. If a "
        "pattern you'd otherwise flag (like 'add a call to action') is genuinely common to "
        "nearly all creators, explain it in terms of THIS creator's specific content so it's "
        "clear the advice was derived from their actual posts, not a generic checklist. "
        "Write it as a clear, actionable roadmap in plain text under those three headers. "
        "Synthesize the patterns — don't just repeat the individual notes verbatim."
    )


def build_graph(db: Session):
    def gather_feedback(state: GrowthPlanState) -> dict:
        creator = db.get(CreatorProfile, state["creator_id"])
        if creator is None:
            raise CreatorNotFoundError(f"No creator_profile with id {state['creator_id']}")

        rows = db.execute(
            select(AIFeedback.feedback_text, AIFeedback.post_id)
            .join(Post, AIFeedback.post_id == Post.id)
            .join(SocialAccount, Post.social_account_id == SocialAccount.id)
            .where(SocialAccount.creator_id == state["creator_id"])
            .where(AIFeedback.feedback_text.is_not(None))
            .order_by(AIFeedback.generated_at.desc())
        ).all()

        if not rows:
            raise NoFeedbackFoundError(
                f"No ai_feedback found for creator {state['creator_id']} — generate feedback "
                "for some posts first."
            )

        distinct_post_ids = {row.post_id for row in rows}
        feedback_texts = [row.feedback_text for row in rows[:MAX_FEEDBACK_SAMPLE]]

        return {"feedback_texts": feedback_texts, "post_count": len(distinct_post_ids)}

    def synthesize_plan(state: GrowthPlanState) -> dict:
        prompt = _build_synthesis_prompt(state["feedback_texts"])
        return {"plan_text": generate_text(prompt)}

    def save_plan(state: GrowthPlanState) -> dict:
        plan = GrowthPlan(
            creator_id=state["creator_id"],
            plan_text=state["plan_text"],
            based_on_post_count=state["post_count"],
            generated_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return {
            "growth_plan_id": plan.id,
            "based_on_post_count": plan.based_on_post_count,
            "generated_at": plan.generated_at,
        }

    graph = StateGraph(GrowthPlanState)
    graph.add_node("gather_feedback", gather_feedback)
    graph.add_node("synthesize_plan", synthesize_plan)
    graph.add_node("save_plan", save_plan)
    graph.add_edge(START, "gather_feedback")
    graph.add_edge("gather_feedback", "synthesize_plan")
    graph.add_edge("synthesize_plan", "save_plan")
    graph.add_edge("save_plan", END)

    return graph.compile()


def run_growth_plan(creator_id: uuid.UUID, db: Session) -> GrowthPlanState:
    graph = build_graph(db)
    return graph.invoke({"creator_id": creator_id})
