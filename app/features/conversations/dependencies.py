from app.db.supabase import get_supabase
from app.features.appointments.repository import SupabaseAppointmentRepository
from app.features.conversations.repository import SupabaseConversationRepository
from app.features.conversations.service import ConversationService


def get_conversation_service() -> ConversationService:
    client = get_supabase()
    return ConversationService(
        repository=SupabaseConversationRepository(client),
        appointment_repository=SupabaseAppointmentRepository(client),
    )
