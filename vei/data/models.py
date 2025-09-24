from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Canonical event envelope for replay datasets."""

    time_ms: int
    actor_id: str
    channel: str
    type: str
    correlation_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class DatasetMetadata(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    transform_hash: Optional[str] = None


class VEIDataset(BaseModel):
    metadata: DatasetMetadata = Field(default_factory=DatasetMetadata)
    events: list[BaseEvent] = Field(default_factory=list)
