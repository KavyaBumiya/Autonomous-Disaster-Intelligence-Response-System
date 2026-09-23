import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class SocialMediaPoll(Base):
    __tablename__ = "social_media_polls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hashtag: Mapped[str] = mapped_column(String(100), nullable=False)
    api_source: Mapped[str] = mapped_column(String(30), nullable=False)  # twitter_v2 | mastodon
    posts_fetched: Mapped[int] = mapped_column(Integer, default=0)
    posts_stored: Mapped[int] = mapped_column(Integer, default=0)
    posts_filtered: Mapped[int] = mapped_column(Integer, default=0)
    polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
