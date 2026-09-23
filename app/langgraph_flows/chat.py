import uuid
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatMessage, CreatorProfile, GrowthPlan, Post, SocialAccount
from app.models.enums import ChatRole
from app.services.gemini_client import generate_text

RECENT_POSTS_LIMIT = 10
HISTORY_LIMIT = 10


class CreatorNotFoundError(Exception):
    pass


class ChatState(TypedDict, total=False):
    creator_id: uuid.UUID
    user_message: str
    recent_posts: list[dict]
    latest_growth_plan: str | None
    audience_demographics: dict | None
    history: list[dict]
    assistant_reply: str
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID


def _summarize_posts(posts: list[dict]) -> str:
    if not posts:
        return "(no posts on file yet)"

    lines = []
    for post in posts:
        caption = (post["caption"] or "(no caption)")[:140]
        likes = post["like_count"] if post["like_count"] is not None else "?"
        comments = post["comments_count"] if post["comments_count"] is not None else "?"
        lines.append(f'- "{caption}" — {likes} likes, {comments} comments')
    return "\n".join(lines)


def _summarize_demographics(demographics: dict | None) -> str:
    if not demographics:
        return "(no audience demographics on file yet)"

    parts = []
    for key, breakdown in demographics.items():
        results = (breakdown or {}).get("results") or []
        if not results:
            continue
        top = sorted(results, key=lambda r: r.get("value", 0), reverse=True)[:3]
        summary = ", ".join(f"{'/'.join(map(str, r.get('dimension_values', [])))}: {r.get('value')}" for r in top)
        parts.append(f"{key}: {summary}")
    return "; ".join(parts) if parts else "(no audience demographics on file yet)"


def _build_chat_prompt(
    recent_posts: list[dict],
    latest_growth_plan: str | None,
    audience_demographics: dict | None,
    history: list[dict],
    user_message: str,
) -> str:
    history_block = (
        "\n".join(f"{turn['role'].capitalize()}: {turn['message_text']}" for turn in history)
        or "(no prior conversation)"
    )

    return (
        "You are a knowledgeable, friendly social media growth coach chatting directly with "
        "a creator. You have real data about this specific creator below — use it naturally "
        "to inform your answer rather than reciting it back. Be conversational, specific, "
        "and concise.\n\n"
        f"Recent posts (up to {RECENT_POSTS_LIMIT}):\n{_summarize_posts(recent_posts)}\n\n"
        f"Latest growth plan on file: {latest_growth_plan or '(no growth plan generated yet)'}\n\n"
        f"Audience demographics: {_summarize_demographics(audience_demographics)}\n\n"
        f"Conversation so far:\n{history_block}\n\n"
        f"Creator's new message: {user_message}\n\n"
        "Respond naturally as the coach, directly addressing the creator's message."
    )


def build_graph(db: Session):
    def gather_context(state: ChatState) -> dict:
        creator = db.get(CreatorProfile, state["creator_id"])
        if creator is None:
            raise CreatorNotFoundError(f"No creator_profile with id {state['creator_id']}")

        posts = db.execute(
            select(Post)
            .join(SocialAccount, Post.social_account_id == SocialAccount.id)
            .where(SocialAccount.creator_id == state["creator_id"])
            .order_by(Post.posted_at.desc())
            .limit(RECENT_POSTS_LIMIT)
        ).scalars().all()

        latest_plan = db.execute(
            select(GrowthPlan)
            .where(GrowthPlan.creator_id == state["creator_id"])
            .order_by(GrowthPlan.generated_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        social_account = db.execute(
            select(SocialAccount)
            .where(SocialAccount.creator_id == state["creator_id"])
            .order_by(SocialAccount.is_active.desc(), SocialAccount.connected_at.desc())
        ).scalars().first()

        return {
            "recent_posts": [
                {"caption": p.caption, "like_count": p.like_count, "comments_count": p.comments_count}
                for p in posts
            ],
            "latest_growth_plan": latest_plan.plan_text if latest_plan else None,
            "audience_demographics": social_account.audience_demographics if social_account else None,
        }

    def load_history(state: ChatState) -> dict:
        rows = db.execute(
            select(ChatMessage)
            .where(ChatMessage.creator_id == state["creator_id"])
            .order_by(ChatMessage.created_at.desc())
            .limit(HISTORY_LIMIT)
        ).scalars().all()

        return {"history": [{"role": m.role.value, "message_text": m.message_text} for m in reversed(rows)]}

    def generate_response(state: ChatState) -> dict:
        prompt = _build_chat_prompt(
            recent_posts=state.get("recent_posts") or [],
            latest_growth_plan=state.get("latest_growth_plan"),
            audience_demographics=state.get("audience_demographics"),
            history=state.get("history") or [],
            user_message=state["user_message"],
        )
        return {"assistant_reply": generate_text(prompt)}

    def save_messages(state: ChatState) -> dict:
        user_msg = ChatMessage(
            creator_id=state["creator_id"],
            role=ChatRole.user,
            message_text=state["user_message"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_msg)
        db.flush()

        assistant_msg = ChatMessage(
            creator_id=state["creator_id"],
            role=ChatRole.assistant,
            message_text=state["assistant_reply"],
            created_at=datetime.now(timezone.utc),
        )
        db.add(assistant_msg)
        db.commit()
        db.refresh(user_msg)
        db.refresh(assistant_msg)

        return {"user_message_id": user_msg.id, "assistant_message_id": assistant_msg.id}

    graph = StateGraph(ChatState)
    graph.add_node("gather_context", gather_context)
    graph.add_node("load_history", load_history)
    graph.add_node("generate_response", generate_response)
    graph.add_node("save_messages", save_messages)
    graph.add_edge(START, "gather_context")
    graph.add_edge("gather_context", "load_history")
    graph.add_edge("load_history", "generate_response")
    graph.add_edge("generate_response", "save_messages")
    graph.add_edge("save_messages", END)

    return graph.compile()


def run_chat(creator_id: uuid.UUID, user_message: str, db: Session) -> ChatState:
    graph = build_graph(db)
    return graph.invoke({"creator_id": creator_id, "user_message": user_message})
