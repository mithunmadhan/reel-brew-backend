import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class CreatorProfile(Base):
    __tablename__ = "creator_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    niche_category: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="creator_profiles")
    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )
    generated_videos: Mapped[list["GeneratedVideo"]] = relationship(
        back_populates="creator", cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(back_populates="creator", cascade="all, delete-orphan")
    growth_plans: Mapped[list["GrowthPlan"]] = relationship(back_populates="creator", cascade="all, delete-orphan")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="creator", cascade="all, delete-orphan")
