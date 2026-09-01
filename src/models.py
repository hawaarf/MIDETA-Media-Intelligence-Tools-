"""Typed domain models shared by services and pages."""
from __future__ import annotations
from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field

class FieldStatus(StrEnum):
    AVAILABLE = "Available"
    NOT_PUBLIC = "Not publicly visible"
    LOGIN_REQUIRED = "Login required"
    NOT_SUPPORTED = "Not supported"
    BLOCKED = "Collection blocked"
    FAILED = "Collection failed"

class DataField(BaseModel):
    value: str | int | float | None = None
    status: FieldStatus

class SocialResult(BaseModel):
    url: str
    platform: str
    username: DataField
    caption: DataField
    posted_at: DataField
    followers: DataField
    likes: DataField
    comments: DataField
    shares: DataField
    views: DataField
    bookmarks: DataField
    reposts: DataField
    collected_at: datetime = Field(default_factory=datetime.now)
    is_mock: bool = False
    note: str | None = None

class PublicComment(BaseModel):
    author: str | None = None
    comment: str
    commented_at: str | None = None
    likes: int | None = None
    reply_count: int = 0
    comment_type: str = "parent"
    rank: int | None = None
    source_url: str
    collected_at: datetime = Field(default_factory=datetime.now)

class CommentCollection(BaseModel):
    url: str
    platform: str
    comments: list[PublicComment] = Field(default_factory=list)
    status: FieldStatus
    reason: str | None = None
    is_mock: bool = False
    collected_at: datetime = Field(default_factory=datetime.now)

class HistoryRecord(BaseModel):
    id: int
    feature: str
    platform: str | None
    source_url: str
    status: str
    result: dict[str, Any]
    created_at: datetime
