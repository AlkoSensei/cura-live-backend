import json
from uuid import UUID, uuid4

from livekit import api

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.features.conversations.schemas import (
    CallSessionCreate,
    ConversationEventCreate,
    ConversationEventType,
)
from app.features.conversations.service import ConversationService
from app.features.livekit.schemas import (
    CreateLiveKitSessionRequest,
    CreateLiveKitSessionResponse,
    EndLiveKitSessionResponse,
)


class LiveKitService:
    def __init__(self, conversation_service: ConversationService, settings: Settings | None = None) -> None:
        self.conversation_service = conversation_service
        self.settings = settings or get_settings()

    async def create_session(self, payload: CreateLiveKitSessionRequest) -> CreateLiveKitSessionResponse:
        if not self.settings.livekit_configured:
            raise AppError("LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.")

        room_name = payload.room_name or f"kare-web-{uuid4().hex[:12]}"
        session = await self.conversation_service.create_session(
            CallSessionCreate(
                room_name=room_name,
                participant_identity=payload.participant_identity,
                participant_name=payload.participant_name,
            )
        )
        await self._create_room(room_name, session.id)
        await self._dispatch_agent(room_name, session.id)
        token = self._create_frontend_token(
            room_name=room_name,
            participant_identity=payload.participant_identity,
            participant_name=payload.participant_name,
            session_id=session.id,
        )
        await self.conversation_service.add_event(
            ConversationEventCreate(
                session_id=session.id,
                event_type=ConversationEventType.TOOL_COMPLETED,
                payload={"message": "Agent dispatch created", "agent_name": self.settings.livekit_agent_name},
            )
        )
        return CreateLiveKitSessionResponse(
            session=session,
            room_name=room_name,
            livekit_url=self.settings.livekit_url,
            token=token,
        )

    async def end_session(self, session_id: UUID, summary: dict[str, object] | None = None) -> EndLiveKitSessionResponse:
        session = await self.conversation_service.get_session(session_id)
        await self._delete_room(session.room_name)
        ended_session = await self.conversation_service.end_session(session_id, summary)
        return EndLiveKitSessionResponse(
            session_id=ended_session.id,
            room_name=ended_session.room_name,
            ended=True,
            message="Call ended successfully.",
        )

    def _room_metadata(self, session_id: UUID) -> str:
        return json.dumps(
            {
                "session_id": str(session_id),
                "call_type": "web",
                "max_call_seconds": self.settings.livekit_max_call_seconds,
            }
        )

    async def _create_room(self, room_name: str, session_id: UUID) -> None:
        lkapi = api.LiveKitAPI(self.settings.livekit_url, self.settings.livekit_api_key, self.settings.livekit_api_secret)
        try:
            await lkapi.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=self.settings.livekit_max_call_seconds,
                    max_participants=4,
                    metadata=self._room_metadata(session_id),
                )
            )
        except Exception as exc:
            if "already exists" not in str(exc).lower():
                raise
        finally:
            await lkapi.aclose()

    async def _dispatch_agent(self, room_name: str, session_id: UUID) -> None:
        lkapi = api.LiveKitAPI(self.settings.livekit_url, self.settings.livekit_api_key, self.settings.livekit_api_secret)
        try:
            await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=self.settings.livekit_agent_name,
                    room=room_name,
                    metadata=self._room_metadata(session_id),
                )
            )
        finally:
            await lkapi.aclose()

    async def _delete_room(self, room_name: str) -> None:
        lkapi = api.LiveKitAPI(self.settings.livekit_url, self.settings.livekit_api_key, self.settings.livekit_api_secret)
        try:
            await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass
        finally:
            await lkapi.aclose()

    def _create_frontend_token(
        self,
        room_name: str,
        participant_identity: str,
        participant_name: str | None,
        session_id: UUID,
    ) -> str:
        metadata = self._room_metadata(session_id)
        return (
            api.AccessToken(self.settings.livekit_api_key, self.settings.livekit_api_secret)
            .with_identity(participant_identity)
            .with_name(participant_name or participant_identity)
            .with_metadata(metadata)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                    can_update_own_metadata=True,
                )
            )
            .to_jwt()
        )
