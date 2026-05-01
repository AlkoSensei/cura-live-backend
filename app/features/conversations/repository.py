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
    ConversationEventType,
)


class ConversationRepository(Protocol):
    async def create_session(self, payload: CallSessionCreate) -> CallSession: ...

    async def get_session(self, session_id: UUID) -> CallSession | None: ...

    async def list_sessions(self, phone_number: str | None, limit: int) -> list[CallSession]: ...

    async def count_sessions(self, phone_number: str | None) -> int: ...

    async def list_sessions_page(
        self, phone_number: str | None, offset: int, limit: int
    ) -> list[CallSession]: ...

    async def list_session_ids_ordered(self, phone_number: str | None) -> list[UUID]: ...

    async def list_sessions_by_ids(self, session_ids: list[UUID]) -> dict[UUID, CallSession]: ...

    async def list_usage_events_for_sessions(self, session_ids: list[UUID]) -> list[ConversationEvent]: ...

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
        return await self.list_sessions_page(phone_number, 0, limit)

    async def count_sessions(self, phone_number: str | None) -> int:
        query = self.client.table("call_sessions").select("id", count="exact")
        if phone_number:
            query = query.eq("phone_number", phone_number)
        response = await query.execute()
        return int(response.count or 0)

    async def list_sessions_page(
        self, phone_number: str | None, offset: int, limit: int
    ) -> list[CallSession]:
        query = self.client.table("call_sessions").select("*").order("created_at", desc=True)
        if phone_number:
            query = query.eq("phone_number", phone_number)
        response = await query.range(offset, offset + max(limit, 1) - 1).execute()
        return [CallSession.model_validate(row) for row in response.data]

    async def list_session_ids_ordered(self, phone_number: str | None) -> list[UUID]:
        batch = 500
        start = 0
        ids: list[UUID] = []
        while True:
            query = self.client.table("call_sessions").select("id").order("created_at", desc=True)
            if phone_number:
                query = query.eq("phone_number", phone_number)
            response = await query.range(start, start + batch - 1).execute()
            rows = response.data or []
            if not rows:
                break
            ids.extend(UUID(str(row["id"])) for row in rows)
            if len(rows) < batch:
                break
            start += batch
        return ids

    async def list_sessions_by_ids(self, session_ids: list[UUID]) -> dict[UUID, CallSession]:
        if not session_ids:
            return {}
        out: dict[UUID, CallSession] = {}
        chunk_size = 80
        for i in range(0, len(session_ids), chunk_size):
            chunk = session_ids[i : i + chunk_size]
            response = await (
                self.client.table("call_sessions").select("*").in_("id", [str(x) for x in chunk]).execute()
            )
            for row in response.data or []:
                session = CallSession.model_validate(row)
                out[session.id] = session
        return out

    async def list_usage_events_for_sessions(self, session_ids: list[UUID]) -> list[ConversationEvent]:
        if not session_ids:
            return []
        events: list[ConversationEvent] = []
        chunk_size = 80
        for i in range(0, len(session_ids), chunk_size):
            chunk = session_ids[i : i + chunk_size]
            response = await (
                self.client.table("conversation_events")
                .select("*")
                .eq("event_type", ConversationEventType.USAGE_METRICS.value)
                .in_("session_id", [str(x) for x in chunk])
                .execute()
            )
            events.extend(ConversationEvent.model_validate(row) for row in (response.data or []))
        return events

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
        return await self.list_sessions_page(phone_number, 0, limit)

    async def count_sessions(self, phone_number: str | None) -> int:
        sessions = list(self.sessions.values())
        if phone_number:
            sessions = [session for session in sessions if session.phone_number == phone_number]
        return len(sessions)

    async def list_sessions_page(
        self, phone_number: str | None, offset: int, limit: int
    ) -> list[CallSession]:
        sessions = list(self.sessions.values())
        if phone_number:
            sessions = [session for session in sessions if session.phone_number == phone_number]
        ordered = sorted(sessions, key=lambda session: session.created_at or datetime.min, reverse=True)
        return ordered[offset : offset + limit]

    async def list_session_ids_ordered(self, phone_number: str | None) -> list[UUID]:
        sessions = list(self.sessions.values())
        if phone_number:
            sessions = [s for s in sessions if s.phone_number == phone_number]
        ordered = sorted(sessions, key=lambda s: s.created_at or datetime.min, reverse=True)
        return [s.id for s in ordered]

    async def list_sessions_by_ids(self, session_ids: list[UUID]) -> dict[UUID, CallSession]:
        return {sid: self.sessions[sid] for sid in session_ids if sid in self.sessions}

    async def list_usage_events_for_sessions(self, session_ids: list[UUID]) -> list[ConversationEvent]:
        out: list[ConversationEvent] = []
        for sid in session_ids:
            for event in self.events.get(sid, []):
                if event.event_type == ConversationEventType.USAGE_METRICS:
                    out.append(event)
        return out

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
