from uuid import UUID

from pydantic import BaseModel, Field

from app.features.conversations.schemas import CallSession


class CreateLiveKitSessionRequest(BaseModel):
    participant_identity: str = Field(min_length=1, max_length=120)
    participant_name: str | None = Field(default=None, max_length=120)
    room_name: str | None = Field(default=None, max_length=120)


class CreateLiveKitSessionResponse(BaseModel):
    session: CallSession
    room_name: str
    livekit_url: str
    token: str


class EndLiveKitSessionRequest(BaseModel):
    summary: dict[str, object] | None = None


class EndLiveKitSessionResponse(BaseModel):
    session_id: UUID
    room_name: str
    ended: bool
    message: str
