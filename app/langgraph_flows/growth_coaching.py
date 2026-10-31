import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from typing import TypedDict

import cv2
import httpx
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AIFeedback, Post
from app.services.gemini_client import GeminiAPIError, generate_json, generate_text, generate_text_with_images

MODEL_NAME = "gemini-2.5-flash"
FRAME_COUNT = 5
RECENT_CONTEXT_POSTS = 10
CATEGORY_KEYS = ('video', 'text', 'content')
MAX_EXAMPLES_PER_CATEGORY = 3


class PostNotFoundError(Exception):
    pass


class VideoProcessingError(Exception):
    pass


class GrowthCoachingState(TypedDict, total=False):
    post_id: uuid.UUID
    caption: str | None
    like_count: int | None
    comments_count: int | None
    media_type: str | None
    media_url: str | None
    caption_feedback: str
    video_path: str
    frame_paths: list[str]
    frame_feedback: str
    social_account_id: uuid.UUID
    posted_at: datetime | None
    recent_posts: list[dict]
    structured: dict | None
    feedback_text: str
    ai_feedback_id: uuid.UUID


def _build_caption_prompt(caption: str | None, like_count: int | None, comments_count: int | None) -> str:
    return (
        "You are a social media growth coach. Based on this Instagram post's data, give ONE "
        "specific, actionable piece of feedback to help improve future posts. Your feedback "
        "must quote or directly reference a specific word, phrase, or detail from THIS caption "
        "— do not give advice generic enough that it could apply to any Instagram post. If the "
        "caption already does something well, say what specifically. Respond in 1-2 sentences "
        "only, with no preamble or bullet points.\n\n"
        f"Caption: {caption or '(no caption)'}\n"
        f"Likes: {like_count if like_count is not None else 'unknown'}\n"
        f"Comments: {comments_count if comments_count is not None else 'unknown'}"
    )


def _build_frame_analysis_prompt(frame_count: int) -> str:
    return (
        f"You are a social media growth coach reviewing {frame_count} evenly-spaced frames "
        "sampled from an Instagram video, in chronological order (the first image is the "
        "opening hook). Describe what is actually visible in these specific frames — subject, "
        "setting, colors, on-screen text, action — and base your feedback on those concrete "
        "details, not generic video-editing checklist advice. Cover:\n"
        "1. The hook — what exactly is in the first frame, and does that specific image grab "
        "attention?\n"
        "2. Pacing — based on how much the frames actually change across the sequence, does "
        "the video feel well-paced or dragging?\n"
        "3. Visual quality — lighting, framing, clarity, specific to what's shown.\n"
        "4. Any text overlays visible — quote them if possible, and say whether they're "
        "readable and well-placed.\n\n"
        "Avoid feedback so generic it would apply to almost any video (e.g. don't just say "
        "'make the hook more dynamic' with no reference to what's actually in this video). "
        "Respond in 3-5 sentences total, no preamble or bullet points."
    )


def _hashtag_count(caption: str | None) -> int:
    return len(re.findall(r"#[^\s#]+", caption or ""))


def _word_count(text: str | None) -> int:
    return len((text or "").split())


def _opening_line(caption: str | None) -> str:
    for line in (caption or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _post_facts(caption: str | None) -> dict:
    return {
        "hashtags": _hashtag_count(caption),
        "words": _word_count(caption),
        "opening_line_words": _word_count(_opening_line(caption)),
    }


def _snippet(caption: str | None, limit: int = 90) -> str:
    text = " ".join((caption or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def _build_structured_prompt(state: "GrowthCoachingState") -> str:
    facts = _post_facts(state.get("caption"))
    recent_lines = []
    for p in state.get("recent_posts") or []:
        recent_lines.append(
            f"{p['ref']} | {p['date'] or 'unknown date'} | {p['media_type'] or 'post'} | "
            f"{p['facts']['hashtags']} hashtags | {p['facts']['words']} words | "
            f"{p['likes']} likes, {p['comments']} comments | caption: {p['snippet'] or '(none)'}"
        )
    recent_block = "\n".join(recent_lines) or "(no other posts on file)"
    video_notes = state.get("frame_feedback") or ""

    return (
        "You are a social media growth coach giving structured feedback on ONE Instagram post, "
        "using only the data below. Never invent numbers, dates or posts. Refer to posts only by "
        "their ref: THIS for the post being reviewed, or P1, P2 and so on for the creator's "
        "other recent posts.\n\n"
        f"THIS POST (ref THIS): {state.get('media_type') or 'post'}, "
        f"{state.get('like_count', 'unknown')} likes, {state.get('comments_count', 'unknown')} comments, "
        f"{facts['hashtags']} hashtags, {facts['words']} words in the caption, "
        f"{facts['opening_line_words']} words in the opening line.\n"
        f"Caption: {state.get('caption') or '(no caption)'}\n\n"
        "CREATOR'S OTHER RECENT POSTS (ref | date | type | hashtags | words | engagement | caption start):\n"
        f"{recent_block}\n\n"
        f"Earlier notes on this post's caption: {state.get('caption_feedback') or '(none)'}\n"
        f"Earlier notes on this post's video frames: {video_notes or '(not a video, or no frames analysed)'}\n\n"
        "Return JSON with exactly these keys:\n"
        '{"working_well": "one or two sentences", "to_fix": "one or two sentences", '
        '"video": null or {"summary": "one sentence", "examples": [...]}, '
        '"text": {"summary": "one sentence", "examples": [...]}, '
        '"content": {"summary": "one sentence", "examples": [...]}}\n'
        'Each example is {"ref": "THIS or P#", "observation": "a concrete fact from that post", '
        '"suggestion": "what to do differently"}.\n\n'
        "Rules:\n"
        "- video: set to null unless video frame notes are provided. It covers the opening/hook, "
        "pacing, visual quality and on-screen text.\n"
        "- text: covers caption wording, the sub-heading or caption structure, and hashtags.\n"
        "- content: covers whether the message is engaging and whether the opening line is too long.\n"
        "- Give one to three examples per category. Each must cite a ref and state a concrete fact "
        "from that post, such as its date and hashtag count, so the creator knows exactly which "
        "post you mean. If the data is too thin for an example, give fewer. Do not pad.\n"
        "- The sample is small. Do not claim one thing caused another.\n"
        "- Do not mention audio or spoken words; you have not heard the video."
    )


def _clean_structured(raw: dict, recent_posts: list[dict], post_id: uuid.UUID, this_caption: str | None,
                      this_posted_at: datetime | None, has_video: bool) -> dict:
    """Keep only what the data supports: drop unknown refs and attach each ref's real post."""
    refs: dict[str, dict] = {
        "THIS": {
            "post_id": str(post_id),
            "date": this_posted_at.date().isoformat() if this_posted_at else None,
            "snippet": _snippet(this_caption),
        }
    }
    for p in recent_posts:
        refs[p["ref"]] = {"post_id": p["post_id"], "date": p["date"], "snippet": p["snippet"]}

    def text_of(value) -> str:
        return value.strip() if isinstance(value, str) else ""

    result: dict = {
        "working_well": text_of(raw.get("working_well")),
        "to_fix": text_of(raw.get("to_fix")),
    }
    for key in CATEGORY_KEYS:
        block = raw.get(key)
        if key == "video" and not has_video:
            result[key] = None
            continue
        if not isinstance(block, dict):
            result[key] = None
            continue
        examples = []
        for ex in (block.get("examples") or [])[:MAX_EXAMPLES_PER_CATEGORY]:
            if not isinstance(ex, dict):
                continue
            ref = refs.get(str(ex.get("ref", "")).strip().upper())
            observation, suggestion = text_of(ex.get("observation")), text_of(ex.get("suggestion"))
            if ref is None or not observation:
                continue
            examples.append({"post": ref, "observation": observation, "suggestion": suggestion})
        result[key] = {"summary": text_of(block.get("summary")), "examples": examples}
    return result


def _render_structured_text(structured: dict) -> str:
    """Plain-text version, so the growth-plan flow (which reads feedback_text) keeps working."""
    parts = []
    if structured.get("working_well"):
        parts.append(f"What is working: {structured['working_well']}")
    if structured.get("to_fix"):
        parts.append(f"What to fix: {structured['to_fix']}")
    for key, label in (("video", "Video"), ("text", "Text"), ("content", "Content")):
        block = structured.get(key)
        if not block:
            continue
        line = f"{label}: {block.get('summary', '')}".strip()
        for ex in block.get("examples", []):
            when = f" ({ex['post']['date']})" if ex["post"].get("date") else ""
            line += f"\n  - Post{when}: {ex['observation']} Suggestion: {ex['suggestion']}"
        parts.append(line)
    return "\n\n".join(parts)


def _download_video(media_url: str, destination_dir: str) -> str:
    video_path = os.path.join(destination_dir, "video.mp4")
    try:
        with httpx.stream("GET", media_url, timeout=30, follow_redirects=True) as response:
            response.raise_for_status()
            with open(video_path, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
    except httpx.HTTPError as exc:
        raise VideoProcessingError(f"Failed to download video from {media_url}: {exc}") from exc
    return video_path


def _extract_frames(video_path: str, destination_dir: str, count: int = FRAME_COUNT) -> list[str]:
    capture = cv2.VideoCapture(video_path)
    frame_paths: list[str] = []
    try:
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            raise VideoProcessingError(f"Could not read any frames from video: {video_path}")

        frame_indices = [min(int(total_frames * i / count), total_frames - 1) for i in range(count)]

        for i, frame_index in enumerate(frame_indices):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            success, frame = capture.read()
            if not success:
                continue
            frame_path = os.path.join(destination_dir, f"frame_{i}.jpg")
            cv2.imwrite(frame_path, frame)
            frame_paths.append(frame_path)
    finally:
        capture.release()

    if not frame_paths:
        raise VideoProcessingError(f"No frames could be extracted from video: {video_path}")

    return frame_paths


def build_graph(db: Session, work_dir: str):
    def fetch_post(state: GrowthCoachingState) -> dict:
        post = db.get(Post, state["post_id"])
        if post is None:
            raise PostNotFoundError(f"No post with id {state['post_id']}")
        others = db.execute(
            select(Post)
            .where(Post.social_account_id == post.social_account_id, Post.id != post.id)
            .order_by(Post.posted_at.desc())
            .limit(RECENT_CONTEXT_POSTS)
        ).scalars().all()
        recent_posts = [
            {
                "ref": f"P{i + 1}",
                "post_id": str(p.id),
                "date": p.posted_at.date().isoformat() if p.posted_at else None,
                "media_type": p.media_type,
                "likes": p.like_count if p.like_count is not None else "?",
                "comments": p.comments_count if p.comments_count is not None else "?",
                "facts": _post_facts(p.caption),
                "snippet": _snippet(p.caption),
            }
            for i, p in enumerate(others)
        ]
        return {
            "caption": post.caption,
            "like_count": post.like_count,
            "comments_count": post.comments_count,
            "media_type": post.media_type,
            "media_url": post.media_url,
            "posted_at": post.posted_at,
            "recent_posts": recent_posts,
        }

    def analyze_caption(state: GrowthCoachingState) -> dict:
        prompt = _build_caption_prompt(state.get("caption"), state.get("like_count"), state.get("comments_count"))
        return {"caption_feedback": generate_text(prompt)}

    def route_after_caption(state: GrowthCoachingState) -> str:
        if state.get("media_type") == "VIDEO" and state.get("media_url"):
            return "download_video"
        return "structure_feedback"

    def download_video(state: GrowthCoachingState) -> dict:
        return {"video_path": _download_video(state["media_url"], work_dir)}

    def extract_frames(state: GrowthCoachingState) -> dict:
        return {"frame_paths": _extract_frames(state["video_path"], work_dir)}

    def analyze_frames(state: GrowthCoachingState) -> dict:
        prompt = _build_frame_analysis_prompt(len(state["frame_paths"]))
        return {"frame_feedback": generate_text_with_images(prompt, state["frame_paths"])}

    def structure_feedback(state: GrowthCoachingState) -> dict:
        """Turn the prose notes into overall + per-category feedback with examples from real posts.
        If this step fails, the plain notes are still saved so feedback never disappears."""
        has_video = bool(state.get("frame_feedback"))
        try:
            raw = generate_json(_build_structured_prompt(state))
            structured = _clean_structured(
                raw, state.get("recent_posts") or [], state["post_id"], state.get("caption"),
                state.get("posted_at"), has_video,
            )
            if not (structured["working_well"] or structured["to_fix"]):
                structured = None
        except (GeminiAPIError, AttributeError, TypeError):
            structured = None
        return {"structured": structured}

    def save_feedback(state: GrowthCoachingState) -> dict:
        structured = state.get("structured")
        if structured:
            feedback_text = _render_structured_text(structured)
        elif state.get("frame_feedback"):
            feedback_text = (
                f"Caption analysis: {state['caption_feedback']}\n\nVideo analysis: {state['frame_feedback']}"
            )
        else:
            feedback_text = state["caption_feedback"]

        feedback = AIFeedback(
            post_id=state["post_id"],
            feedback_text=feedback_text,
            sentiment_notes=json.dumps(structured) if structured else None,
            model_used=MODEL_NAME,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return {"feedback_text": feedback_text, "ai_feedback_id": feedback.id}

    graph = StateGraph(GrowthCoachingState)
    graph.add_node("fetch_post", fetch_post)
    graph.add_node("analyze_caption", analyze_caption)
    graph.add_node("download_video", download_video)
    graph.add_node("extract_frames", extract_frames)
    graph.add_node("analyze_frames", analyze_frames)
    graph.add_node("structure_feedback", structure_feedback)
    graph.add_node("save_feedback", save_feedback)

    graph.add_edge(START, "fetch_post")
    graph.add_edge("fetch_post", "analyze_caption")
    graph.add_conditional_edges(
        "analyze_caption",
        route_after_caption,
        {"download_video": "download_video", "structure_feedback": "structure_feedback"},
    )
    graph.add_edge("download_video", "extract_frames")
    graph.add_edge("extract_frames", "analyze_frames")
    graph.add_edge("analyze_frames", "structure_feedback")
    graph.add_edge("structure_feedback", "save_feedback")
    graph.add_edge("save_feedback", END)

    return graph.compile()


def run_growth_coaching(post_id: uuid.UUID, db: Session) -> GrowthCoachingState:
    # Files land in this directory only; deleted on exit whether the flow succeeds or raises.
    with tempfile.TemporaryDirectory(prefix="growth_coaching_") as work_dir:
        graph = build_graph(db, work_dir)
        return graph.invoke({"post_id": post_id})
