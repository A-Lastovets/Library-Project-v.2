from sqlalchemy import Column, DateTime, ForeignKey, Text, String, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
from app.dependencies.database import Base

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reader_id = Column(Integer, ForeignKey("users.id"))
    librarian_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")  # pending | active | closed
    created_at = Column(DateTime, default=datetime.now)

    reader = relationship("User", foreign_keys=[reader_id])
    librarian = relationship("User", foreign_keys=[librarian_id])
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete", passive_deletes=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.now)

    session = relationship("ChatSession", back_populates="messages", passive_deletes=True)
    sender = relationship("User")
