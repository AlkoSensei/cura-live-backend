from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.features.conversations.dependencies import get_conversation_service
from app.features.conversations.schemas import CallAnalytics, CallCost, CallHistoryResponse
from app.features.conversations.service import ConversationService

router = APIRouter(tags=["conversations"])


@router.get("/conversations/{session_id}/stream")
async def stream_conversation(
    session_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> StreamingResponse:
    return StreamingResponse(service.stream_events(session_id), media_type="text/event-stream")


@router.get("/conversations/{session_id}/analytics", response_model=CallAnalytics)
async def get_analytics(
    session_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> CallAnalytics:
    return await service.get_analytics(session_id)


@router.get("/calls/history", response_model=CallHistoryResponse)
async def get_call_history(
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    phone_number: str | None = None,
    limit: int = 25,
) -> CallHistoryResponse:
    return await service.get_history(phone_number=phone_number, limit=limit)


@router.get("/calls/{session_id}/cost", response_model=CallCost)
async def get_call_cost(
    session_id: UUID,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> CallCost:
    return await service.get_cost(session_id)
