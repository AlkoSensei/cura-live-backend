from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.features.appointments.schemas import Appointment


class CallStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    FAILED = "failed"


class ConversationEventType(StrEnum):
    TRANSCRIPT = "transcript"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    APPOINTMENT_BOOKED = "appointment_booked"
    CALL_ENDED = "call_ended"
    USAGE_METRICS = "usage_metrics"
    AGENT_STATE = "agent_state"
    USER_STATE = "user_state"
    INTERRUPTION = "interruption"


class TranscriptRole(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class ConversationEventCreate(BaseModel):
    session_id: UUID
    event_type: ConversationEventType
    payload: dict[str, object]


class ConversationEvent(BaseModel):
    id: UUID
    session_id: UUID
    event_type: ConversationEventType
    payload: dict[str, object]
    created_at: datetime | None = None


class TranscriptEventPayload(BaseModel):
    role: TranscriptRole
    text: str
    is_final: bool = True


class ToolEventPayload(BaseModel):
    tool_name: str
    message: str
    data: dict[str, object] = Field(default_factory=dict)


class CallSessionCreate(BaseModel):
    room_name: str
    participant_identity: str
    participant_name: str | None = None


class CallSession(BaseModel):
    id: UUID
    room_name: str
    participant_identity: str
    participant_name: str | None = None
    phone_number: str | None = None
    status: CallStatus
    summary: dict[str, object] | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime | None = None


class ProviderUsage(BaseModel):
    stt_audio_seconds: float = 0.0
    tts_characters: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    raw_metrics: list[dict[str, object]] = Field(default_factory=list)


class CallCost(BaseModel):
    session_id: UUID
    usage: ProviderUsage
    stt_cost: float
    tts_cost: float
    llm_input_cost: float
    llm_output_cost: float
    total_cost: float
    currency: str = "USD"


class ExtractedConversationFields(BaseModel):
    name: str | None = None
    phone_number: str | None = None
    date: str | None = None
    time: str | None = None
    intent: str | None = None


class CallAnalytics(BaseModel):
    session: CallSession
    events: list[ConversationEvent]
    appointments: list[Appointment]
    cost: CallCost
    extracted_fields: ExtractedConversationFields


class CallHistoryItem(BaseModel):
    session: CallSession
    tool_call_count: int
    appointment_count: int
    total_cost: float
    extracted_fields: ExtractedConversationFields


class CallHistoryResponse(BaseModel):
    calls: list[CallHistoryItem]
