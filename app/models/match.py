import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import MatchStatus


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("creator_profiles.id"), nullable=False, index=True
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id"), nullable=False, index=True
    )
    match_score: Mapped[float | None] = mapped_column(Float)
    match_reasoning: Mapped[str | None] = mapped_column(Text)
    is_non_obvious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[MatchStatus] = mapped_column(
        SAEnum(MatchStatus, name="match_status"), nullable=False, default=MatchStatus.suggested
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    creator: Mapped["CreatorProfile"] = relationship(back_populates="matches")
    brand: Mapped["Brand"] = relationship(back_populates="matches")
    deals: Mapped[list["Deal"]] = relationship(back_populates="match", cascade="all, delete-orphan")
