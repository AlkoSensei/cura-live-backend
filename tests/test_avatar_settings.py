from app.core.config import Settings


def test_livekit_avatar_bey_enabled_requires_provider_and_key() -> None:
    assert not Settings(livekit_avatar_provider="none", bey_api_key="").livekit_avatar_bey_enabled

    assert Settings(livekit_avatar_provider="bey", bey_api_key="sk-test").livekit_avatar_bey_enabled

    assert not Settings(livekit_avatar_provider="none", bey_api_key="sk-test").livekit_avatar_bey_enabled

    assert not Settings(livekit_avatar_provider="bey", bey_api_key="").livekit_avatar_bey_enabled
