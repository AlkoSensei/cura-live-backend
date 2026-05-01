from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.features.livekit.dependencies import get_livekit_service
from app.features.livekit.schemas import (
    CreateLiveKitSessionRequest,
    CreateLiveKitSessionResponse,
    EndLiveKitSessionRequest,
    EndLiveKitSessionResponse,
)
from app.features.livekit.service import LiveKitService

router = APIRouter(prefix="/livekit", tags=["livekit"])


@router.post("/sessions", response_model=CreateLiveKitSessionResponse)
async def create_livekit_session(
    payload: CreateLiveKitSessionRequest,
    service: Annotated[LiveKitService, Depends(get_livekit_service)],
) -> CreateLiveKitSessionResponse:
    return await service.create_session(payload)


@router.post("/sessions/{session_id}/end", response_model=EndLiveKitSessionResponse)
async def end_livekit_session(
    session_id: UUID,
    payload: EndLiveKitSessionRequest,
    service: Annotated[LiveKitService, Depends(get_livekit_service)],
) -> EndLiveKitSessionResponse:
    return await service.end_session(session_id, payload.summary)
