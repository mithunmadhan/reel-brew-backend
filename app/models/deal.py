import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import DealStatus


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matches.id"), nullable=False, index=True
    )
    agreed_price: Mapped[int | None] = mapped_column(Integer)
    commission_amount: Mapped[int | None] = mapped_column(Integer)
    deliverables: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DealStatus] = mapped_column(
        SAEnum(DealStatus, name="deal_status"), nullable=False, default=DealStatus.negotiating
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    match: Mapped["Match"] = relationship(back_populates="deals")
