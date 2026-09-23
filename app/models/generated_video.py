import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import VideoStatus


class GeneratedVideo(Base):
    __tablename__ = "generated_videos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("creator_profiles.id"), nullable=False, index=True
    )
    topic: Mapped[str | None] = mapped_column(Text)
    script_text: Mapped[str | None] = mapped_column(Text)
    voice_language: Mapped[str | None] = mapped_column(Text)
    video_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[VideoStatus] = mapped_column(
        SAEnum(VideoStatus, name="video_status"), nullable=False, default=VideoStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    creator: Mapped["CreatorProfile"] = relationship(back_populates="generated_videos")
