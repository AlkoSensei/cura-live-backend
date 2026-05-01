from app.core.config import Settings


def test_livekit_avatar_bey_enabled_requires_provider_and_key() -> None:
    assert not Settings(livekit_avatar_provider="none", bey_api_key="").livekit_avatar_bey_enabled

    assert Settings(livekit_avatar_provider="bey", bey_api_key="sk-test").livekit_avatar_bey_enabled

    assert not Settings(livekit_avatar_provider="none", bey_api_key="sk-test").livekit_avatar_bey_enabled

    assert not Settings(livekit_avatar_provider="bey", bey_api_key="").livekit_avatar_bey_enabled


def test_livekit_avatar_tavus_enabled_requires_provider_and_credentials() -> None:
    base = dict(
        livekit_avatar_provider="tavus",
        tavus_api_key="tk-test",
        tavus_replica_id="replica-1",
        tavus_persona_id="persona-1",
    )
    assert Settings(**base).livekit_avatar_tavus_enabled

    assert not Settings(livekit_avatar_provider="none", **{k: v for k, v in base.items() if k != "livekit_avatar_provider"}).livekit_avatar_tavus_enabled

    assert not Settings(**{**base, "tavus_api_key": ""}).livekit_avatar_tavus_enabled

    assert not Settings(**{**base, "tavus_replica_id": ""}).livekit_avatar_tavus_enabled

    assert not Settings(**{**base, "tavus_persona_id": ""}).livekit_avatar_tavus_enabled


def test_livekit_avatar_enabled_union() -> None:
    assert Settings(livekit_avatar_provider="none").livekit_avatar_enabled is False

    assert Settings(livekit_avatar_provider="bey", bey_api_key="x").livekit_avatar_enabled is True

    assert (
        Settings(
            livekit_avatar_provider="tavus",
            tavus_api_key="k",
            tavus_replica_id="r",
            tavus_persona_id="p",
        ).livekit_avatar_enabled
        is True
    )
