import asyncio
from collections import defaultdict
from uuid import UUID

from app.features.conversations.schemas import ConversationEvent


class ConversationEventBus:
    def __init__(self) -> None:
        self._queues: dict[UUID, set[asyncio.Queue[ConversationEvent]]] = defaultdict(set)

    async def publish(self, event: ConversationEvent) -> None:
        for queue in self._queues[event.session_id].copy():
            await queue.put(event)

    async def subscribe(self, session_id: UUID) -> asyncio.Queue[ConversationEvent]:
        queue: asyncio.Queue[ConversationEvent] = asyncio.Queue()
        self._queues[session_id].add(queue)
        return queue

    def unsubscribe(self, session_id: UUID, queue: asyncio.Queue[ConversationEvent]) -> None:
        queues = self._queues.get(session_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._queues.pop(session_id, None)


event_bus = ConversationEventBus()
