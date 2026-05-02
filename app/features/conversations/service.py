import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import status
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.features.appointments.repository import AppointmentRepository
from app.features.appointments.schemas import Appointment
from app.features.conversations.ai_extraction import (
    PostCallExtraction,
    PostCallExtractionService,
)
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
                payload={
                    "message": "LiveKit room created",
                    "room_name": session.room_name,
                },
            )
        )
        return session

    async def get_session(self, session_id: UUID) -> CallSession:
        session = await self.repository.get_session(session_id)
        if session is None:
            raise AppError("Call session not found.", status.HTTP_404_NOT_FOUND)
        return session

    async def end_session(
        self, session_id: UUID, summary: dict[str, object] | None = None
    ) -> CallSession:
        events = await self.repository.list_events(session_id)
        final_summary: dict[str, object] = dict(summary or {})
        if (
            self.settings.post_call_ai_extraction_enabled
            and PostCallExtractionService.events_have_transcript_text(events)
        ):
            ai = await self.ai_extraction_service.extract(events)
            if ai is not None:
                final_summary["ai_summary"] = ai.summary
                final_summary["ai_outcome"] = ai.outcome
                final_summary["ai_next_action"] = ai.next_action
                final_summary["ai_provider"] = "anthropic_with_openrouter_fallback"
                final_summary["ai_extracted_fields"] = ai.extracted_fields.model_dump(
                    mode="json"
                )

        session = await self.repository.end_session(session_id, final_summary)
        await self.add_event(
            ConversationEventCreate(
                session_id=session_id,
                event_type=ConversationEventType.CALL_ENDED,
                payload={"message": "Call ended", "summary": final_summary},
            )
        )
        return session

    async def add_event(self, payload: ConversationEventCreate) -> ConversationEvent:
        event = await self.repository.add_event(payload)
        await self.bus.publish(event)
        return event

    async def update_phone_number(
        self, session_id: UUID, phone_number: str
    ) -> CallSession:
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
                    for event in await self.repository.list_events(
                        session_id, last_event_id
                    ):
                        last_event_id = event.id
                        yield self._format_sse(event)
                    yield ": keep-alive\n\n"
        finally:
            self.bus.unsubscribe(session_id, queue)

    async def get_analytics(self, session_id: UUID) -> CallAnalytics:
        session = await self.get_session(session_id)
        events = await self.repository.list_events(session_id)
        phone_number = session.phone_number
        appointments = (
            await self.appointment_repository.list_by_phone(phone_number)
            if phone_number
            else []
        )
        extracted_fields = self.extract_fields(session, events, appointments)

        summ = session.summary or {}
        cached_summary_text = summ.get("ai_summary")
        has_cached_ai = isinstance(cached_summary_text, str) and bool(
            cached_summary_text.strip()
        )

        if has_cached_ai:
            try:
                cached_extracted = ExtractedConversationFields.model_validate(
                    summ.get("ai_extracted_fields") or {}
                )
            except ValidationError:
                cached_extracted = ExtractedConversationFields()
            ai_extraction = PostCallExtraction(
                extracted_fields=cached_extracted,
                summary=(
                    cached_summary_text
                    if isinstance(cached_summary_text, str)
                    else None
                ),
                outcome=(
                    summ.get("ai_outcome")
                    if isinstance(summ.get("ai_outcome"), str)
                    else None
                ),
                next_action=(
                    summ.get("ai_next_action")
                    if isinstance(summ.get("ai_next_action"), str)
                    else None
                ),
            )
        else:
            ai_extraction = await self.ai_extraction_service.extract(events)

        if ai_extraction is not None:
            extracted_fields = self._merge_extracted_fields(
                extracted_fields, ai_extraction.extracted_fields
            )
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
        extracted_fields = self._overlay_call_datetime_ist(
            session, extracted_fields, include_generated_iso=True
        )

        return CallAnalytics(
            session=session,
            events=events,
            appointments=appointments,
            cost=self.calculate_cost(session_id, events, session),
            extracted_fields=extracted_fields,
        )

    async def get_history(
        self,
        phone_number: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> CallHistoryResponse:
        page = max(1, page)
        page_size = min(max(1, page_size), 100)
        offset = (page - 1) * page_size

        total_calls = await self.repository.count_sessions(phone_number)
        sessions_page = await self.repository.list_sessions_page(
            phone_number, offset, page_size
        )

        ids_all = await self.repository.list_session_ids_ordered(phone_number)
        sessions_by_id = await self.repository.list_sessions_by_ids(ids_all)
        usage_all = await self.repository.list_usage_events_for_sessions(ids_all)

        usage_by_session: dict[UUID, list[ConversationEvent]] = defaultdict(list)
        for ev in usage_all:
            usage_by_session[ev.session_id].append(ev)

        cost_by_session: dict[UUID, CallCost] = {}
        total_cost_usd = 0.0
        for sid in ids_all:
            sess = sessions_by_id.get(sid)
            cost = self.calculate_cost(sid, usage_by_session[sid], sess)
            cost_by_session[sid] = cost
            total_cost_usd += cost.total_cost

        calls: list[CallHistoryItem] = []
        for session in sessions_page:
            events = await self.repository.list_events(session.id)
            tool_call_count = self.count_agent_tool_calls(events)
            appointments: list[Appointment] = []
            if session.phone_number:
                appointments = await self.appointment_repository.list_by_phone(
                    session.phone_number
                )
            cost = cost_by_session[session.id]
            raw_extracted = self.extract_fields(session, events, appointments)
            calls.append(
                CallHistoryItem(
                    session=session,
                    tool_call_count=tool_call_count,
                    appointment_count=len(appointments),
                    total_cost=cost.total_cost,
                    cost=cost,
                    extracted_fields=self._overlay_call_datetime_ist(
                        session, raw_extracted, include_generated_iso=False
                    ),
                )
            )

        has_next = offset + len(sessions_page) < total_calls

        return CallHistoryResponse(
            calls=calls,
            page=page,
            page_size=page_size,
            total_calls=total_calls,
            total_cost_usd=round(total_cost_usd, 6),
            has_next=has_next,
        )

    def count_agent_tool_calls(self, events: list[ConversationEvent]) -> int:
        return sum(
            1
            for event in events
            if event.event_type
            in {
                ConversationEventType.TOOL_COMPLETED,
                ConversationEventType.APPOINTMENT_BOOKED,
            }
            and event.payload.get("tool_name") in self.agent_tool_names
        )

    async def get_cost(self, session_id: UUID) -> CallCost:
        session = await self.get_session(session_id)
        events = await self.repository.list_events(session_id)
        return self.calculate_cost(session_id, events, session)

    @staticmethod
    def _call_duration_seconds(session: CallSession | None) -> float | None:
        if session is None:
            return None
        start = session.started_at
        end = session.ended_at
        if start is None:
            return None
        if end is None:
            end = datetime.now(UTC)
        try:
            delta = end - start
        except TypeError:
            return None
        return max(0.0, delta.total_seconds())

    def calculate_cost(
        self,
        session_id: UUID,
        events: list[ConversationEvent],
        session: CallSession | None = None,
    ) -> CallCost:
        usage = ProviderUsage()
        for event in events:
            if event.event_type != ConversationEventType.USAGE_METRICS:
                continue
            usage.raw_metrics.append(event.payload)
            usage.stt_audio_seconds += float(
                event.payload.get("stt_audio_seconds", 0.0) or 0.0
            )
            usage.tts_characters += int(event.payload.get("tts_characters", 0) or 0)
            usage.llm_input_tokens += int(event.payload.get("llm_input_tokens", 0) or 0)
            usage.llm_output_tokens += int(
                event.payload.get("llm_output_tokens", 0) or 0
            )

        duration_sec = self._call_duration_seconds(session)
        estimate_parts: list[str] = []

        stt_sec = usage.stt_audio_seconds
        if (
            stt_sec <= 0
            and self.settings.cost_fallback_use_call_duration
            and duration_sec
        ):
            stt_sec = (
                duration_sec * self.settings.cost_fallback_stt_ratio_of_call_duration
            )
            estimate_parts.append("STT estimated from call duration")

        tts_chars = usage.tts_characters
        if (
            tts_chars <= 0
            and self.settings.cost_fallback_use_call_duration
            and duration_sec
        ):
            tts_chars = int(
                duration_sec * self.settings.cost_fallback_tts_chars_per_call_second
            )
            estimate_parts.append("TTS estimated from call duration")

        stt_cost = (stt_sec / 60.0) * self.settings.cost_stt_per_minute
        tts_cost = (tts_chars / 1000.0) * self.settings.cost_tts_per_1k_chars
        llm_input_cost = (
            usage.llm_input_tokens / 1_000_000
        ) * self.settings.cost_llm_input_per_1m_tokens
        llm_output_cost = (
            usage.llm_output_tokens / 1_000_000
        ) * self.settings.cost_llm_output_per_1m_tokens
        llm_total_cost = llm_input_cost + llm_output_cost
        total_cost = stt_cost + tts_cost + llm_total_cost

        estimate_note = "; ".join(estimate_parts) if estimate_parts else None

        return CallCost(
            session_id=session_id,
            usage=usage,
            call_duration_seconds=duration_sec,
            stt_seconds_charged=round(stt_sec, 6),
            tts_characters_charged=tts_chars,
            stt_cost=round(stt_cost, 6),
            tts_cost=round(tts_cost, 6),
            llm_input_cost=round(llm_input_cost, 6),
            llm_output_cost=round(llm_output_cost, 6),
            llm_total_cost=round(llm_total_cost, 6),
            total_cost=round(total_cost, 6),
            estimate_note=estimate_note,
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

            if tool_name in {
                "book_appointment",
                "cancel_appointment",
                "modify_appointment",
            }:
                self._merge_appointment_payload(extracted, payload)

        return extracted

    @staticmethod
    def _merge_appointment_payload(
        extracted: ExtractedConversationFields, payload: dict[str, object]
    ) -> None:
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        appointment = data.get("appointment")
        if not isinstance(appointment, dict):
            return

        patient_name = appointment.get("patient_name")
        phone_number = appointment.get("phone_number")

        if isinstance(patient_name, str):
            extracted.name = patient_name
        if isinstance(phone_number, str):
            extracted.phone_number = phone_number

    @staticmethod
    def _call_instant_utc(session: CallSession) -> datetime:
        raw = session.ended_at or session.started_at
        if raw is None:
            return datetime.now(UTC)
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)

    @classmethod
    def _overlay_call_datetime_ist(
        cls,
        session: CallSession,
        extracted: ExtractedConversationFields,
        *,
        include_generated_iso: bool,
    ) -> ExtractedConversationFields:
        dt_ist = cls._call_instant_utc(session).astimezone(ZoneInfo("Asia/Kolkata"))
        updates: dict[str, str | None] = {
            "date": dt_ist.strftime("%Y-%m-%d"),
            "time": dt_ist.strftime("%H:%M:%S"),
        }
        if include_generated_iso:
            updates["generated_at_ist"] = dt_ist.isoformat()
        return extracted.model_copy(update=updates)

    @staticmethod
    def _merge_extracted_fields(
        fallback: ExtractedConversationFields,
        ai_fields: ExtractedConversationFields,
    ) -> ExtractedConversationFields:
        return ExtractedConversationFields(
            name=ai_fields.name or "Not Recorded",
            phone_number=ai_fields.phone_number or fallback.phone_number,
            date=fallback.date,
            time=fallback.time,
            intent=ai_fields.intent or fallback.intent,
            generated_at_ist=fallback.generated_at_ist,
        )

    @staticmethod
    def _format_sse(event: ConversationEvent) -> str:
        data = event.model_dump(mode="json")
        return f"id: {event.id}\nevent: {event.event_type.value}\ndata: {json.dumps(data)}\n\n"
