import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import TypedDict

import cv2
import httpx
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.models import AIFeedback, Post
from app.services.gemini_client import generate_text, generate_text_with_images

MODEL_NAME = "gemini-2.5-flash"
FRAME_COUNT = 5


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
    feedback_text: str
    ai_feedback_id: uuid.UUID


def _build_caption_prompt(caption: str | None, like_count: int | None, comments_count: int | None) -> str:
    return (
        "You are a social media growth coach. Based on this Instagram post's data, give ONE "
        "specific, actionable piece of feedback to help improve future posts. Respond in "
        "1-2 sentences only, with no preamble or bullet points.\n\n"
        f"Caption: {caption or '(no caption)'}\n"
        f"Likes: {like_count if like_count is not None else 'unknown'}\n"
        f"Comments: {comments_count if comments_count is not None else 'unknown'}"
    )


def _build_frame_analysis_prompt(frame_count: int) -> str:
    return (
        f"You are a social media growth coach reviewing {frame_count} evenly-spaced frames "
        "sampled from an Instagram video, in chronological order (the first image is the "
        "opening hook). Give specific, actionable feedback covering:\n"
        "1. The hook — does the first frame grab attention?\n"
        "2. Pacing — based on how much the frames change across the sequence, does the video "
        "feel well-paced or dragging?\n"
        "3. Visual quality — lighting, framing, clarity.\n"
        "4. Any text overlays visible — are they readable and well-placed?\n\n"
        "Respond in 3-5 sentences total, no preamble or bullet points."
    )


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
        return {
            "caption": post.caption,
            "like_count": post.like_count,
            "comments_count": post.comments_count,
            "media_type": post.media_type,
            "media_url": post.media_url,
        }

    def analyze_caption(state: GrowthCoachingState) -> dict:
        prompt = _build_caption_prompt(state.get("caption"), state.get("like_count"), state.get("comments_count"))
        return {"caption_feedback": generate_text(prompt)}

    def route_after_caption(state: GrowthCoachingState) -> str:
        if state.get("media_type") == "VIDEO" and state.get("media_url"):
            return "download_video"
        return "save_feedback"

    def download_video(state: GrowthCoachingState) -> dict:
        return {"video_path": _download_video(state["media_url"], work_dir)}

    def extract_frames(state: GrowthCoachingState) -> dict:
        return {"frame_paths": _extract_frames(state["video_path"], work_dir)}

    def analyze_frames(state: GrowthCoachingState) -> dict:
        prompt = _build_frame_analysis_prompt(len(state["frame_paths"]))
        return {"frame_feedback": generate_text_with_images(prompt, state["frame_paths"])}

    def save_feedback(state: GrowthCoachingState) -> dict:
        if state.get("frame_feedback"):
            feedback_text = (
                f"Caption analysis: {state['caption_feedback']}\n\nVideo analysis: {state['frame_feedback']}"
            )
        else:
            feedback_text = state["caption_feedback"]

        feedback = AIFeedback(
            post_id=state["post_id"],
            feedback_text=feedback_text,
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
    graph.add_node("save_feedback", save_feedback)

    graph.add_edge(START, "fetch_post")
    graph.add_edge("fetch_post", "analyze_caption")
    graph.add_conditional_edges(
        "analyze_caption",
        route_after_caption,
        {"download_video": "download_video", "save_feedback": "save_feedback"},
    )
    graph.add_edge("download_video", "extract_frames")
    graph.add_edge("extract_frames", "analyze_frames")
    graph.add_edge("analyze_frames", "save_feedback")
    graph.add_edge("save_feedback", END)

    return graph.compile()


def run_growth_coaching(post_id: uuid.UUID, db: Session) -> GrowthCoachingState:
    # Files land in this directory only; deleted on exit whether the flow succeeds or raises.
    with tempfile.TemporaryDirectory(prefix="growth_coaching_") as work_dir:
        graph = build_graph(db, work_dir)
        return graph.invoke({"post_id": post_id})
