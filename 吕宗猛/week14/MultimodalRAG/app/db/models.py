"""Database models for documents, chunks, images and chat."""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import relationship

from app.core.db import Base


class Document(Base):
    __tablename__ = "mm_document"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_name = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    file_size = Column(BigInteger, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending", index=True)
    tier = Column(String(20), nullable=False, default="basic")
    page_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    image_count = Column(Integer, nullable=False, default=0)
    markdown_path = Column(String(1024), nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    parsed_at = Column(DateTime, nullable=True)

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    images = relationship("Image", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "mm_chunk"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_id = Column(BigInteger, ForeignKey("mm_document.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    image_ids = Column(JSON, nullable=True)
    embedding = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")


class Image(Base):
    __tablename__ = "mm_image"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_id = Column(BigInteger, ForeignKey("mm_document.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=False, default="image/jpeg")
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    document = relationship("Document", back_populates="images")


class ChatSession(Base):
    __tablename__ = "mm_chat_session"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False, default="新会话")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "mm_chat_message"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("mm_chat_session.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False, default="")
    image_path = Column(String(1024), nullable=True)
    image_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")
