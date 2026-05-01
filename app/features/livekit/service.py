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
    def __init__(
        self,
        conversation_service: ConversationService,
        settings: Settings | None = None,
    ) -> None:
        self.conversation_service = conversation_service
        self.settings = settings or get_settings()

    def _resolved_avatar_provider(self, payload: CreateLiveKitSessionRequest) -> str:
        if payload.avatar_provider is not None:
            return payload.avatar_provider.strip().lower()
        return self.settings.livekit_avatar_provider_normalized

    def _session_metadata_json(self, session_id: UUID, avatar_provider: str) -> str:
        return json.dumps(
            {
                "session_id": str(session_id),
                "call_type": "web",
                "max_call_seconds": self.settings.livekit_max_call_seconds,
                "avatar_provider": avatar_provider,
            }
        )

    def _validate_avatar_credentials(self, avatar_provider: str) -> None:
        if avatar_provider == "bey" and not self.settings.bey_api_key.strip():
            raise AppError("Avatar provider bey requires BEY_API_KEY.")
        if avatar_provider == "tavus":
            if not self.settings.tavus_api_key.strip():
                raise AppError("Avatar provider tavus requires TAVUS_API_KEY.")
            if not self.settings.tavus_replica_id.strip():
                raise AppError("Avatar provider tavus requires TAVUS_REPLICA_ID.")
            if not self.settings.tavus_persona_id.strip():
                raise AppError("Avatar provider tavus requires TAVUS_PERSONA_ID.")

    async def create_session(
        self, payload: CreateLiveKitSessionRequest
    ) -> CreateLiveKitSessionResponse:
        if not self.settings.livekit_configured:
            raise AppError(
                "LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET."
            )

        room_name = payload.room_name or f"kare-web-{uuid4().hex[:12]}"
        avatar_provider = self._resolved_avatar_provider(payload)
        if avatar_provider not in ("none", "bey", "tavus"):
            raise AppError("avatar_provider must be none, bey, or tavus.")
        self._validate_avatar_credentials(avatar_provider)

        session = await self.conversation_service.create_session(
            CallSessionCreate(
                room_name=room_name,
                participant_identity=payload.participant_identity,
                participant_name=payload.participant_name,
            )
        )
        meta = self._session_metadata_json(session.id, avatar_provider)
        await self._create_room(room_name, meta)
        await self._dispatch_agent(room_name, meta)
        token = self._create_frontend_token(
            room_name=room_name,
            participant_identity=payload.participant_identity,
            participant_name=payload.participant_name,
            metadata_json=meta,
        )
        await self.conversation_service.add_event(
            ConversationEventCreate(
                session_id=session.id,
                event_type=ConversationEventType.TOOL_COMPLETED,
                payload={
                    "message": "Agent dispatch created",
                    "agent_name": self.settings.livekit_agent_name,
                },
            )
        )
        avatar_enabled = avatar_provider in ("bey", "tavus")
        return CreateLiveKitSessionResponse(
            session=session,
            room_name=room_name,
            livekit_url=self.settings.livekit_url,
            token=token,
            avatar_enabled=avatar_enabled,
            avatar_provider=avatar_provider if avatar_enabled else None,
            avatar_participant_identity=(
                self.settings.livekit_avatar_participant_identity
                if avatar_enabled
                else None
            ),
        )

    async def end_session(
        self, session_id: UUID, summary: dict[str, object] | None = None
    ) -> EndLiveKitSessionResponse:
        session = await self.conversation_service.get_session(session_id)
        await self._delete_room(session.room_name)
        ended_session = await self.conversation_service.end_session(session_id, summary)
        return EndLiveKitSessionResponse(
            session_id=ended_session.id,
            room_name=ended_session.room_name,
            ended=True,
            message="Call ended successfully.",
        )

    async def _create_room(self, room_name: str, metadata_json: str) -> None:
        lkapi = api.LiveKitAPI(
            self.settings.livekit_url,
            self.settings.livekit_api_key,
            self.settings.livekit_api_secret,
        )
        try:
            await lkapi.room.create_room(
                api.CreateRoomRequest(
                    name=room_name,
                    empty_timeout=self.settings.livekit_max_call_seconds,
                    max_participants=4,
                    metadata=metadata_json,
                )
            )
        except Exception as exc:
            if "already exists" not in str(exc).lower():
                raise
        finally:
            await lkapi.aclose()

    async def _dispatch_agent(self, room_name: str, metadata_json: str) -> None:
        lkapi = api.LiveKitAPI(
            self.settings.livekit_url,
            self.settings.livekit_api_key,
            self.settings.livekit_api_secret,
        )
        try:
            await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=self.settings.livekit_agent_name,
                    room=room_name,
                    metadata=metadata_json,
                )
            )
        finally:
            await lkapi.aclose()

    async def _delete_room(self, room_name: str) -> None:
        lkapi = api.LiveKitAPI(
            self.settings.livekit_url,
            self.settings.livekit_api_key,
            self.settings.livekit_api_secret,
        )
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
        metadata_json: str,
    ) -> str:
        return (
            api.AccessToken(
                self.settings.livekit_api_key, self.settings.livekit_api_secret
            )
            .with_identity(participant_identity)
            .with_name(participant_name or participant_identity)
            .with_metadata(metadata_json)
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
