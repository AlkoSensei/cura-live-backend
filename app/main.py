import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.supabase import close_supabase, init_supabase
from app.features.appointments.router import router as appointment_router
from app.features.conversations.router import router as conversation_router
from app.features.livekit.router import router as livekit_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await init_supabase()

    worker_task: asyncio.Task[None] | None = None
    server = None
    if settings.start_embedded_livekit_worker:
        from app.agent.worker import server as _server

        server = _server
        worker_task = asyncio.create_task(server.run(), name="livekit-worker")
    try:
        yield
    finally:
        if server is not None:
            await server.aclose()
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except (asyncio.CancelledError, Exception):
                pass
        await close_supabase()


def create_app() -> FastAPI:
    settings = get_settings()
    fastapi_app = FastAPI(title=settings.app_name, lifespan=lifespan)
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @fastapi_app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @fastapi_app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @fastapi_app.get("/api/warmup")
    async def warmup() -> dict[str, object]:
        from app.agent.worker import server

        connecting: bool = getattr(server, "_connecting", False)
        closed: bool = getattr(server, "_closed", True)
        connection_failed: bool = getattr(server, "_connection_failed", False)

        supabase_ready = False
        try:
            from app.db.supabase import get_supabase
            client = get_supabase()
            await client.table("call_sessions").select("id").limit(1).execute()
            supabase_ready = True
        except Exception:
            pass

        worker_ready = not closed and not connecting and not connection_failed
        status = "ready" if (worker_ready and supabase_ready) else "warming"
        return {
            "status": status,
            "checks": {
                "worker": "ready" if worker_ready else ("failed" if connection_failed else "warming"),
                "supabase": "ready" if supabase_ready else "warming",
            },
        }

    fastapi_app.include_router(livekit_router, prefix=settings.api_prefix)
    fastapi_app.include_router(conversation_router, prefix=settings.api_prefix)
    fastapi_app.include_router(appointment_router, prefix=settings.api_prefix)
    return fastapi_app


app = create_app()
