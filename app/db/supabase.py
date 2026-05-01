from supabase import AsyncClient, acreate_client

from app.core.config import get_settings

_client: AsyncClient | None = None


async def init_supabase() -> None:
    global _client
    if _client is not None:
        return
    settings = get_settings()
    if not settings.supabase_configured:
        return
    _client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)


async def close_supabase() -> None:
    global _client
    if _client is not None:
        close = getattr(_client, "aclose", None)
        if close is not None:
            await close()
    _client = None


def get_supabase() -> AsyncClient:
    if _client is None:
        raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return _client
