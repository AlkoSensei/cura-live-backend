from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Kare Live Voice Backend"
    app_env: str = "local"
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_agent_name: str = "kare-appointment-agent"
    livekit_max_call_seconds: int = 300
    # Virtual avatar: LIVEKIT_AVATAR_PROVIDER none | bey | tavus
    livekit_avatar_provider: str = "none"
    livekit_avatar_participant_identity: str = "kare-avatar-agent"
    livekit_avatar_participant_name: str = "Kare Avatar"

    bey_api_key: str = ""
    bey_avatar_id: str = ""

    tavus_api_key: str = ""
    tavus_replica_id: str = ""
    tavus_persona_id: str = ""

    supabase_url: str = ""
    supabase_service_role_key: str = ""

    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en-IN"

    sarvam_api_key: str = ""
    sarvam_language_code: str = "en-IN"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_speaker: str = "shubh"

    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemini-3-flash"
    post_call_ai_extraction_enabled: bool = True

    # Deployment: when true, start the LiveKit worker inside the FastAPI process (simple local dev).
    # On Render/Fly web: set START_EMBEDDED_LIVEKIT_WORKER=false and run `python -m app.agent.run_worker start` separately.
    start_embedded_livekit_worker: bool = True

    cost_stt_per_minute: float = 0.0
    cost_tts_per_1k_chars: float = 0.0
    cost_llm_input_per_1m_tokens: float = 0.80
    cost_llm_output_per_1m_tokens: float = 4.00

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def livekit_configured(self) -> bool:
        return bool(
            self.livekit_url and self.livekit_api_key and self.livekit_api_secret
        )

    @property
    def livekit_avatar_provider_normalized(self) -> str:
        return self.livekit_avatar_provider.strip().lower()

    @property
    def livekit_avatar_bey_enabled(self) -> bool:
        return self.livekit_avatar_provider_normalized == "bey" and bool(
            self.bey_api_key.strip()
        )

    @property
    def livekit_avatar_tavus_enabled(self) -> bool:
        return (
            self.livekit_avatar_provider_normalized == "tavus"
            and bool(self.tavus_api_key.strip())
            and bool(self.tavus_replica_id.strip())
            and bool(self.tavus_persona_id.strip())
        )

    @property
    def livekit_avatar_enabled(self) -> bool:
        return self.livekit_avatar_bey_enabled or self.livekit_avatar_tavus_enabled

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
