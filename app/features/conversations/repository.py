from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from supabase import AsyncClient

from app.features.conversations.schemas import (
    CallSession,
    CallSessionCreate,
    CallStatus,
    ConversationEvent,
    ConversationEventCreate,
)


class ConversationRepository(Protocol):
    async def create_session(self, payload: CallSessionCreate) -> CallSession: ...

    async def get_session(self, session_id: UUID) -> CallSession | None: ...

    async def list_sessions(self, phone_number: str | None, limit: int) -> list[CallSession]: ...

    async def end_session(self, session_id: UUID, summary: dict[str, object] | None = None) -> CallSession: ...

    async def update_phone_number(self, session_id: UUID, phone_number: str) -> CallSession: ...

    async def add_event(self, payload: ConversationEventCreate) -> ConversationEvent: ...

    async def list_events(self, session_id: UUID, after_event_id: UUID | None = None) -> list[ConversationEvent]: ...


class SupabaseConversationRepository:
    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def create_session(self, payload: CallSessionCreate) -> CallSession:
        response = await (
            self.client.table("call_sessions")
            .insert(
                {
                    "room_name": payload.room_name,
                    "participant_identity": payload.participant_identity,
                    "participant_name": payload.participant_name,
                    "status": CallStatus.ACTIVE.value,
                }
            )
            .execute()
        )
        return CallSession.model_validate(response.data[0])

    async def get_session(self, session_id: UUID) -> CallSession | None:
        response = await self.client.table("call_sessions").select("*").eq("id", str(session_id)).limit(1).execute()
        return CallSession.model_validate(response.data[0]) if response.data else None

    async def list_sessions(self, phone_number: str | None, limit: int) -> list[CallSession]:
        query = self.client.table("call_sessions").select("*").order("created_at", desc=True).limit(limit)
        if phone_number:
            query = query.eq("phone_number", phone_number)
        response = await query.execute()
        return [CallSession.model_validate(row) for row in response.data]

    async def end_session(self, session_id: UUID, summary: dict[str, object] | None = None) -> CallSession:
        response = await (
            self.client.table("call_sessions")
            .update({"status": CallStatus.ENDED.value, "ended_at": datetime.now(UTC).isoformat(), "summary": summary})
            .eq("id", str(session_id))
            .execute()
        )
        return CallSession.model_validate(response.data[0])

    async def update_phone_number(self, session_id: UUID, phone_number: str) -> CallSession:
        response = await self.client.table("call_sessions").update({"phone_number": phone_number}).eq("id", str(session_id)).execute()
        return CallSession.model_validate(response.data[0])

    async def add_event(self, payload: ConversationEventCreate) -> ConversationEvent:
        response = await (
            self.client.table("conversation_events")
            .insert(
                {
                    "session_id": str(payload.session_id),
                    "event_type": payload.event_type.value,
                    "payload": payload.payload,
                }
            )
            .execute()
        )
        return ConversationEvent.model_validate(response.data[0])

    async def list_events(self, session_id: UUID, after_event_id: UUID | None = None) -> list[ConversationEvent]:
        response = await (
            self.client.table("conversation_events")
            .select("*")
            .eq("session_id", str(session_id))
            .order("created_at")
            .order("id")
            .execute()
        )
        events = [ConversationEvent.model_validate(row) for row in response.data]
        if after_event_id is None:
            return events
        try:
            index = next(index for index, event in enumerate(events) if event.id == after_event_id)
        except StopIteration:
            return events
        return events[index + 1 :]


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, CallSession] = {}
        self.events: dict[UUID, list[ConversationEvent]] = {}

    async def create_session(self, payload: CallSessionCreate) -> CallSession:
        session = CallSession(
            id=uuid4(),
            room_name=payload.room_name,
            participant_identity=payload.participant_identity,
            participant_name=payload.participant_name,
            status=CallStatus.ACTIVE,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        self.sessions[session.id] = session
        self.events[session.id] = []
        return session

    async def get_session(self, session_id: UUID) -> CallSession | None:
        return self.sessions.get(session_id)

    async def list_sessions(self, phone_number: str | None, limit: int) -> list[CallSession]:
        sessions = list(self.sessions.values())
        if phone_number:
            sessions = [session for session in sessions if session.phone_number == phone_number]
        return sorted(sessions, key=lambda session: session.created_at or datetime.min, reverse=True)[:limit]

    async def end_session(self, session_id: UUID, summary: dict[str, object] | None = None) -> CallSession:
        session = self.sessions[session_id].model_copy(
            update={"status": CallStatus.ENDED, "ended_at": datetime.now(UTC), "summary": summary}
        )
        self.sessions[session_id] = session
        return session

    async def update_phone_number(self, session_id: UUID, phone_number: str) -> CallSession:
        session = self.sessions[session_id].model_copy(update={"phone_number": phone_number})
        self.sessions[session_id] = session
        return session

    async def add_event(self, payload: ConversationEventCreate) -> ConversationEvent:
        event = ConversationEvent(
            id=uuid4(),
            session_id=payload.session_id,
            event_type=payload.event_type,
            payload=payload.payload,
            created_at=datetime.now(UTC),
        )
        self.events.setdefault(payload.session_id, []).append(event)
        return event

    async def list_events(self, session_id: UUID, after_event_id: UUID | None = None) -> list[ConversationEvent]:
        events = self.events.get(session_id, [])
        if after_event_id is None:
            return events
        try:
            index = next(index for index, event in enumerate(events) if event.id == after_event_id)
        except StopIteration:
            return events
        return events[index + 1 :]
