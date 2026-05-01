from uuid import uuid4

from app.core.config import Settings
from app.features.conversations.repository import InMemoryConversationRepository
from app.features.conversations.service import ConversationService
from app.features.appointments.repository import InMemoryAppointmentRepository
from app.features.livekit.service import LiveKitService


def test_create_frontend_token_contains_room_grant() -> None:
    settings = Settings(
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="devkey",
        livekit_api_secret="devsecret",
        livekit_agent_name="kare-appointment-agent",
    )
    conversation_service = ConversationService(
        repository=InMemoryConversationRepository(),
        appointment_repository=InMemoryAppointmentRepository(),
        settings=settings,
    )
    service = LiveKitService(conversation_service, settings=settings)

    token = service._create_frontend_token(  # noqa: SLF001
        room_name="room-a",
        participant_identity="patient-a",
        participant_name="Patient A",
        session_id=uuid4(),
    )

    assert isinstance(token, str)
    assert token.count(".") == 2
