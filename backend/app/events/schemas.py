import datetime

from pydantic import BaseModel, Field

from app.core.ids import new_id


class Event(BaseModel):
    id: str = Field(default_factory=new_id)
    type: str
    correlation_id: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
