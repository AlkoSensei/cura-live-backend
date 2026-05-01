import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from uuid import UUID

from dotenv import load_dotenv
from livekit import api
from livekit.agents import AgentServer, AgentSession, JobContext, MetricsCollectedEvent, RoomOutputOptions, cli
from livekit.agents.llm import FallbackAdapter
from livekit.plugins import anthropic, deepgram, openai, sarvam

from app.agent.tools import AppointmentAgent
from app.core.config import get_settings
from app.db.supabase import close_supabase, get_supabase, init_supabase
from app.features.appointments.repository import SupabaseAppointmentRepository
from app.features.appointments.service import AppointmentService
from app.features.conversations.repository import SupabaseConversationRepository
from app.features.conversations.schemas import ConversationEventCreate, ConversationEventType, TranscriptRole
from app.features.conversations.service import ConversationService

load_dotenv()
settings = get_settings()
os.environ.setdefault("LIVEKIT_URL", settings.livekit_url)
os.environ.setdefault("LIVEKIT_API_KEY", settings.livekit_api_key)
os.environ.setdefault("LIVEKIT_API_SECRET", settings.livekit_api_secret)
if settings.tavus_api_key.strip():
    os.environ.setdefault("TAVUS_API_KEY", settings.tavus_api_key.strip())
server = AgentServer()


def _parse_session_id(ctx: JobContext) -> UUID:
    metadata_candidates = [
        getattr(getattr(ctx, "job", None), "metadata", None),
        getattr(getattr(ctx, "room", None), "metadata", None),
    ]
    for metadata in metadata_candidates:
        if not metadata:
            continue
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError:
            continue
        if session_id := parsed.get("session_id"):
            return UUID(session_id)
    raise RuntimeError("LiveKit dispatch metadata did not include session_id.")


def _metrics_payload(ev: MetricsCollectedEvent) -> dict[str, object]:
    metrics = ev.metrics
    payload: dict[str, object] = {
        "provider": getattr(metrics, "provider", ""),
        "model": getattr(metrics, "model", ""),
        "metric_type": metrics.__class__.__name__,
    }
    if is_dataclass(metrics):
        payload["raw"] = asdict(metrics)
    payload["llm_input_tokens"] = int(
        getattr(metrics, "prompt_tokens", 0) or getattr(metrics, "input_tokens", 0) or 0
    )
    payload["llm_output_tokens"] = int(
        getattr(metrics, "completion_tokens", 0) or getattr(metrics, "output_tokens", 0) or 0
    )
    payload["tts_characters"] = int(getattr(metrics, "characters_count", 0) or 0)
    payload["stt_audio_seconds"] = float(
        getattr(metrics, "audio_duration", 0.0)
        or getattr(metrics, "duration", 0.0)
        or getattr(metrics, "speech_duration", 0.0)
        or 0.0
    )
    return payload


async def _delete_room(room_name: str) -> None:
    lkapi = api.LiveKitAPI(settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret)
    try:
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
    except Exception:
        pass
    finally:
        await lkapi.aclose()


def _create_llm() -> FallbackAdapter:
    llms = [
        anthropic.LLM(model=settings.claude_model, api_key=settings.anthropic_api_key, temperature=0.2),
    ]
    if settings.openrouter_api_key:
        llms.append(
            openai.LLM(
                model=settings.openrouter_model,
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                temperature=0.2,
                extra_headers={
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": settings.app_name,
                },
            )
        )
    return FallbackAdapter(llm=llms, attempt_timeout=8.0, max_retry_per_llm=1, retry_interval=0.5)


@server.rtc_session(agent_name=settings.livekit_agent_name)
async def entrypoint(ctx: JobContext) -> None:
    await init_supabase()  # no-op if already initialised by the FastAPI lifespan
    client = get_supabase()
    appointment_service = AppointmentService(SupabaseAppointmentRepository(client))
    conversation_service = ConversationService(
        repository=SupabaseConversationRepository(client),
        appointment_repository=SupabaseAppointmentRepository(client),
    )
    session_id = _parse_session_id(ctx)

    prov = settings.livekit_avatar_provider_normalized
    if prov == "bey" and not settings.bey_api_key.strip():
        raise RuntimeError("LIVEKIT_AVATAR_PROVIDER=bey requires BEY_API_KEY.")
    if prov == "tavus":
        if not settings.tavus_api_key.strip():
            raise RuntimeError("LIVEKIT_AVATAR_PROVIDER=tavus requires TAVUS_API_KEY.")
        if not settings.tavus_replica_id.strip():
            raise RuntimeError("LIVEKIT_AVATAR_PROVIDER=tavus requires TAVUS_REPLICA_ID.")
        if not settings.tavus_persona_id.strip():
            raise RuntimeError("LIVEKIT_AVATAR_PROVIDER=tavus requires TAVUS_PERSONA_ID.")

    session = AgentSession(
        stt=deepgram.STT(
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            api_key=settings.deepgram_api_key,
        ),
        llm=_create_llm(),
        tts=sarvam.TTS(
            target_language_code=settings.sarvam_language_code,
            model=settings.sarvam_tts_model,
            speaker=settings.sarvam_speaker,
            api_key=settings.sarvam_api_key,
        ),
    )

    @session.on("metrics_collected")
    def on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        asyncio.create_task(
            conversation_service.add_event(
                ConversationEventCreate(
                    session_id=session_id,
                    event_type=ConversationEventType.USAGE_METRICS,
                    payload=_metrics_payload(ev),
                )
            )
        )

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev: object) -> None:
        text = getattr(ev, "transcript", "")
        if not text:
            return
        asyncio.create_task(
            conversation_service.add_event(
                ConversationEventCreate(
                    session_id=session_id,
                    event_type=ConversationEventType.TRANSCRIPT,
                    payload={
                        "role": TranscriptRole.USER.value,
                        "text": text,
                        "is_final": bool(getattr(ev, "is_final", True)),
                    },
                )
            )
        )

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev: object) -> None:
        asyncio.create_task(
            conversation_service.add_event(
                ConversationEventCreate(
                    session_id=session_id,
                    event_type=ConversationEventType.AGENT_STATE,
                    payload={
                        "old_state": str(getattr(ev, "old_state", "")),
                        "new_state": str(getattr(ev, "new_state", "")),
                    },
                )
            )
        )

    @session.on("user_state_changed")
    def on_user_state_changed(ev: object) -> None:
        asyncio.create_task(
            conversation_service.add_event(
                ConversationEventCreate(
                    session_id=session_id,
                    event_type=ConversationEventType.USER_STATE,
                    payload={
                        "old_state": str(getattr(ev, "old_state", "")),
                        "new_state": str(getattr(ev, "new_state", "")),
                    },
                )
            )
        )

    @session.on("overlapping_speech")
    def on_overlapping_speech(ev: object) -> None:
        asyncio.create_task(
            conversation_service.add_event(
                ConversationEventCreate(
                    session_id=session_id,
                    event_type=ConversationEventType.INTERRUPTION,
                    payload={
                        "is_interruption": bool(getattr(ev, "is_interruption", False)),
                        "detection_delay": float(getattr(ev, "detection_delay", 0.0) or 0.0),
                        "detected_at": float(getattr(ev, "detected_at", 0.0) or 0.0),
                        "overlap_started_at": getattr(ev, "overlap_started_at", None),
                    },
                )
            )
        )

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev: object) -> None:
        item = getattr(ev, "item", None)
        if item is None or getattr(item, "role", "") != "assistant":
            return
        text = getattr(item, "text_content", "")
        if not text:
            return
        asyncio.create_task(
            conversation_service.add_event(
                ConversationEventCreate(
                    session_id=session_id,
                    event_type=ConversationEventType.TRANSCRIPT,
                    payload={"role": TranscriptRole.AGENT.value, "text": text, "is_final": True},
                )
            )
        )

    avatar_enabled = settings.livekit_avatar_enabled
    if settings.livekit_avatar_bey_enabled:
        from livekit.plugins import bey

        bey_kwargs: dict[str, object] = {
            "api_key": settings.bey_api_key,
            "avatar_participant_identity": settings.livekit_avatar_participant_identity,
            "avatar_participant_name": settings.livekit_avatar_participant_name,
        }
        if settings.bey_avatar_id.strip():
            bey_kwargs["avatar_id"] = settings.bey_avatar_id.strip()
        bey_avatar = bey.AvatarSession(**bey_kwargs)
        await bey_avatar.start(session, room=ctx.room)
    elif settings.livekit_avatar_tavus_enabled:
        from livekit.plugins import tavus

        tavus_avatar = tavus.AvatarSession(
            replica_id=settings.tavus_replica_id.strip(),
            persona_id=settings.tavus_persona_id.strip(),
            api_key=settings.tavus_api_key.strip(),
            avatar_participant_identity=settings.livekit_avatar_participant_identity,
            avatar_participant_name=settings.livekit_avatar_participant_name,
        )
        await tavus_avatar.start(session, room=ctx.room)

    start_kwargs: dict[str, object] = {
        "agent": AppointmentAgent(
            appointment_service=appointment_service,
            conversation_service=conversation_service,
            session_id=session_id,
        ),
        "room": ctx.room,
    }
    if avatar_enabled:
        start_kwargs["room_output_options"] = RoomOutputOptions(audio_enabled=False)

    await session.start(**start_kwargs)
    await session.generate_reply(instructions="Greet the user and ask for their phone number to identify them.")

    async def enforce_max_call_duration() -> None:
        await asyncio.sleep(settings.livekit_max_call_seconds)
        await conversation_service.add_event(
            ConversationEventCreate(
                session_id=session_id,
                event_type=ConversationEventType.CALL_ENDED,
                payload={
                    "message": "Maximum web call duration reached",
                    "max_call_seconds": settings.livekit_max_call_seconds,
                },
            )
        )
        await session.generate_reply(
            instructions="Tell the user the five minute call limit has been reached, then say goodbye briefly."
        )
        await asyncio.sleep(4)
        await conversation_service.end_session(
            session_id,
            {"reason": "max_call_duration_reached", "max_call_seconds": settings.livekit_max_call_seconds},
        )
        await session.aclose()
        await _delete_room(ctx.room.name)

    max_call_task = asyncio.create_task(enforce_max_call_duration())

    async def shutdown() -> None:
        max_call_task.cancel()
        try:
            await max_call_task
        except asyncio.CancelledError:
            pass
        await close_supabase()

    ctx.add_shutdown_callback(shutdown)


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        sys.argv.append("start")
    cli.run_app(server)
