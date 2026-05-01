from datetime import date, time

import pytest

from app.core.config import Settings
from app.features.appointments.repository import InMemoryAppointmentRepository
from app.features.appointments.schemas import AppointmentCreate
from app.features.appointments.service import AppointmentService
from app.features.conversations.repository import InMemoryConversationRepository
from app.features.conversations.schemas import (
    CallSessionCreate,
    ConversationEventCreate,
    ConversationEventType,
)
from app.features.conversations.service import ConversationService


@pytest.mark.asyncio
async def test_analytics_and_history_include_extracted_fields() -> None:
    appointment_repository = InMemoryAppointmentRepository()
    conversation_repository = InMemoryConversationRepository()
    settings = Settings(
        anthropic_api_key="",
        openrouter_api_key="",
        post_call_ai_extraction_enabled=True,
    )
    conversation_service = ConversationService(conversation_repository, appointment_repository, settings=settings)
    appointment_service = AppointmentService(appointment_repository)

    session = await conversation_service.create_session(
        CallSessionCreate(room_name="room-a", participant_identity="patient-a")
    )
    appointment = await appointment_service.book_appointment(
        AppointmentCreate(
            patient_name="Asha Rao",
            phone_number="9876543210",
            appointment_date=date(2026, 5, 5),
            appointment_time=time(10),
        )
    )
    await conversation_service.update_phone_number(session.id, appointment.phone_number)
    await conversation_service.add_event(
        ConversationEventCreate(
            session_id=session.id,
            event_type=ConversationEventType.APPOINTMENT_BOOKED,
            payload={
                "tool_name": "book_appointment",
                "message": "Appointment booked",
                "data": {"appointment": appointment.model_dump(mode="json")},
            },
        )
    )

    analytics = await conversation_service.get_analytics(session.id)
    history = await conversation_service.get_history()

    assert analytics.extracted_fields.name == "Asha Rao"
    assert analytics.extracted_fields.phone_number == "9876543210"
    assert analytics.extracted_fields.date == "2026-05-05"
    assert analytics.extracted_fields.time == "10:00:00"
    assert analytics.extracted_fields.intent == "book_appointment"
    assert history.calls[0].extracted_fields == analytics.extracted_fields
    assert history.calls[0].tool_call_count == 1
