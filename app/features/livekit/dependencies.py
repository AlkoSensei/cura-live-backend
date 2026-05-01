from app.features.conversations.dependencies import get_conversation_service
from app.features.livekit.service import LiveKitService


def get_livekit_service() -> LiveKitService:
    return LiveKitService(get_conversation_service())
