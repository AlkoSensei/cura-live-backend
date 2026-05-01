import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import status

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.features.appointments.repository import AppointmentRepository
from app.features.appointments.schemas import Appointment
from app.features.conversations.ai_extraction import PostCallExtractionService
from app.features.conversations.event_bus import ConversationEventBus, event_bus
from app.features.conversations.repository import ConversationRepository
from app.features.conversations.schemas import (
    CallAnalytics,
    CallCost,
    CallHistoryItem,
    CallHistoryResponse,
    CallSession,
    CallSessionCreate,
    ConversationEvent,
    ConversationEventCreate,
    ConversationEventType,
    ExtractedConversationFields,
    ProviderUsage,
)


class ConversationService:
    agent_tool_names = {
        "get_today_date",
        "identify_user",
        "fetch_slots",
        "book_appointment",
        "retrieve_appointments",
        "cancel_appointment",
        "modify_appointment",
        "end_call",
        "end_conversation",
    }

    def __init__(
        self,
        repository: ConversationRepository,
        appointment_repository: AppointmentRepository,
        settings: Settings | None = None,
        bus: ConversationEventBus = event_bus,
    ) -> None:
        self.repository = repository
        self.appointment_repository = appointment_repository
        self.settings = settings or get_settings()
        self.bus = bus
        self.ai_extraction_service = PostCallExtractionService(self.settings)

    async def create_session(self, payload: CallSessionCreate) -> CallSession:
        session = await self.repository.create_session(payload)
        await self.add_event(
            ConversationEventCreate(
                session_id=session.id,
                event_type=ConversationEventType.TOOL_COMPLETED,
                payload={"message": "LiveKit room created", "room_name": session.room_name},
            )
        )
        return session

    async def get_session(self, session_id: UUID) -> CallSession:
        session = await self.repository.get_session(session_id)
        if session is None:
            raise AppError("Call session not found.", status.HTTP_404_NOT_FOUND)
        return session

    async def end_session(self, session_id: UUID, summary: dict[str, object] | None = None) -> CallSession:
        session = await self.repository.end_session(session_id, summary)
        await self.add_event(
            ConversationEventCreate(
                session_id=session_id,
                event_type=ConversationEventType.CALL_ENDED,
                payload={"message": "Call ended", "summary": summary or {}},
            )
        )
        return session

    async def add_event(self, payload: ConversationEventCreate) -> ConversationEvent:
        event = await self.repository.add_event(payload)
        await self.bus.publish(event)
        return event

    async def update_phone_number(self, session_id: UUID, phone_number: str) -> CallSession:
        return await self.repository.update_phone_number(session_id, phone_number)

    async def stream_events(self, session_id: UUID) -> AsyncIterator[str]:
        await self.get_session(session_id)
        last_event_id: UUID | None = None
        queue = await self.bus.subscribe(session_id)
        try:
            for event in await self.repository.list_events(session_id):
                last_event_id = event.id
                yield self._format_sse(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    last_event_id = event.id
                    yield self._format_sse(event)
                except TimeoutError:
                    for event in await self.repository.list_events(session_id, last_event_id):
                        last_event_id = event.id
                        yield self._format_sse(event)
                    yield ": keep-alive\n\n"
        finally:
            self.bus.unsubscribe(session_id, queue)

    async def get_analytics(self, session_id: UUID) -> CallAnalytics:
        session = await self.get_session(session_id)
        events = await self.repository.list_events(session_id)
        phone_number = session.phone_number
        appointments = await self.appointment_repository.list_by_phone(phone_number) if phone_number else []
        extracted_fields = self.extract_fields(session, events, appointments)
        ai_extraction = await self.ai_extraction_service.extract(events)
        if ai_extraction is not None:
            extracted_fields = self._merge_extracted_fields(extracted_fields, ai_extraction.extracted_fields)
            session = session.model_copy(
                update={
                    "summary": {
                        **(session.summary or {}),
                        "ai_summary": ai_extraction.summary,
                        "ai_outcome": ai_extraction.outcome,
                        "ai_next_action": ai_extraction.next_action,
                        "ai_provider": "anthropic_with_openrouter_fallback",
                    }
                }
            )
        return CallAnalytics(
            session=session,
            events=events,
            appointments=appointments,
            cost=self.calculate_cost(session_id, events),
            extracted_fields=extracted_fields,
        )

    async def get_history(self, phone_number: str | None = None, limit: int = 25) -> CallHistoryResponse:
        sessions = await self.repository.list_sessions(phone_number, min(limit, 100))
        calls: list[CallHistoryItem] = []
        for session in sessions:
            events = await self.repository.list_events(session.id)
            tool_call_count = self.count_agent_tool_calls(events)
            appointments: list[Appointment] = []
            if session.phone_number:
                appointments = await self.appointment_repository.list_by_phone(session.phone_number)
            calls.append(
                CallHistoryItem(
                    session=session,
                    tool_call_count=tool_call_count,
                    appointment_count=len(appointments),
                    total_cost=self.calculate_cost(session.id, events).total_cost,
                    extracted_fields=self.extract_fields(session, events, appointments),
                )
            )
        return CallHistoryResponse(calls=calls)

    def count_agent_tool_calls(self, events: list[ConversationEvent]) -> int:
        return sum(
            1
            for event in events
            if event.event_type in {ConversationEventType.TOOL_COMPLETED, ConversationEventType.APPOINTMENT_BOOKED}
            and event.payload.get("tool_name") in self.agent_tool_names
        )

    async def get_cost(self, session_id: UUID) -> CallCost:
        await self.get_session(session_id)
        events = await self.repository.list_events(session_id)
        return self.calculate_cost(session_id, events)

    def calculate_cost(self, session_id: UUID, events: list[ConversationEvent]) -> CallCost:
        usage = ProviderUsage()
        for event in events:
            if event.event_type != ConversationEventType.USAGE_METRICS:
                continue
            usage.raw_metrics.append(event.payload)
            usage.stt_audio_seconds += float(event.payload.get("stt_audio_seconds", 0.0) or 0.0)
            usage.tts_characters += int(event.payload.get("tts_characters", 0) or 0)
            usage.llm_input_tokens += int(event.payload.get("llm_input_tokens", 0) or 0)
            usage.llm_output_tokens += int(event.payload.get("llm_output_tokens", 0) or 0)

        stt_cost = (usage.stt_audio_seconds / 60) * self.settings.cost_stt_per_minute
        tts_cost = (usage.tts_characters / 1000) * self.settings.cost_tts_per_1k_chars
        llm_input_cost = (usage.llm_input_tokens / 1_000_000) * self.settings.cost_llm_input_per_1m_tokens
        llm_output_cost = (usage.llm_output_tokens / 1_000_000) * self.settings.cost_llm_output_per_1m_tokens
        total_cost = stt_cost + tts_cost + llm_input_cost + llm_output_cost
        return CallCost(
            session_id=session_id,
            usage=usage,
            stt_cost=round(stt_cost, 6),
            tts_cost=round(tts_cost, 6),
            llm_input_cost=round(llm_input_cost, 6),
            llm_output_cost=round(llm_output_cost, 6),
            total_cost=round(total_cost, 6),
        )

    def extract_fields(
        self,
        session: CallSession,
        events: list[ConversationEvent],
        appointments: list[Appointment],
    ) -> ExtractedConversationFields:
        extracted = ExtractedConversationFields(phone_number=session.phone_number)

        if appointments:
            latest_appointment = appointments[-1]
            extracted.name = latest_appointment.patient_name
            extracted.phone_number = latest_appointment.phone_number
            extracted.date = latest_appointment.appointment_date.isoformat()
            extracted.time = latest_appointment.appointment_time.isoformat()

        for event in events:
            payload = event.payload
            tool_name = payload.get("tool_name")

            if isinstance(tool_name, str) and tool_name != "identify_user":
                extracted.intent = tool_name

            if event.event_type == ConversationEventType.APPOINTMENT_BOOKED:
                extracted.intent = "book_appointment"
                self._merge_appointment_payload(extracted, payload)
                continue

            if tool_name == "identify_user":
                data = payload.get("data")
                if isinstance(data, dict):
                    phone_number = data.get("phone_number")
                    if isinstance(phone_number, str):
                        extracted.phone_number = phone_number
                continue

            if tool_name in {"book_appointment", "cancel_appointment", "modify_appointment"}:
                self._merge_appointment_payload(extracted, payload)

        return extracted

    @staticmethod
    def _merge_appointment_payload(extracted: ExtractedConversationFields, payload: dict[str, object]) -> None:
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        appointment = data.get("appointment")
        if not isinstance(appointment, dict):
            return

        patient_name = appointment.get("patient_name")
        phone_number = appointment.get("phone_number")
        appointment_date = appointment.get("appointment_date")
        appointment_time = appointment.get("appointment_time")

        if isinstance(patient_name, str):
            extracted.name = patient_name
        if isinstance(phone_number, str):
            extracted.phone_number = phone_number
        if isinstance(appointment_date, str):
            extracted.date = appointment_date
        if isinstance(appointment_time, str):
            extracted.time = appointment_time

    @staticmethod
    def _merge_extracted_fields(
        fallback: ExtractedConversationFields,
        ai_fields: ExtractedConversationFields,
    ) -> ExtractedConversationFields:
        return ExtractedConversationFields(
            name=ai_fields.name or fallback.name,
            phone_number=ai_fields.phone_number or fallback.phone_number,
            date=ai_fields.date or fallback.date,
            time=ai_fields.time or fallback.time,
            intent=ai_fields.intent or fallback.intent,
        )

    @staticmethod
    def _format_sse(event: ConversationEvent) -> str:
        data = event.model_dump(mode="json")
        return f"id: {event.id}\nevent: {event.event_type.value}\ndata: {json.dumps(data)}\n\n"
