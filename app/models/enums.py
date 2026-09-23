import enum


class UserType(str, enum.Enum):
    creator = "creator"
    brand = "brand"


class VideoStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class MatchStatus(str, enum.Enum):
    suggested = "suggested"
    viewed = "viewed"
    accepted = "accepted"
    rejected = "rejected"


class DealStatus(str, enum.Enum):
    negotiating = "negotiating"
    confirmed = "confirmed"
    delivered = "delivered"
    paid = "paid"
    disputed = "disputed"


class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
