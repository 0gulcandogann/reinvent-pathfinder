import asyncio

from scripts import sync_catalog as command

from app.catalog.sync import SyncResult


def test_login_flag_overrides_environment_token(monkeypatch, capsys) -> None:
    received_tokens: list[str] = []

    async def fake_login() -> str:
        return "private-interactive-token"

    class FakeRestClient:
        def __init__(self, token: str, *, event_id: str) -> None:
            received_tokens.append(token)
            assert event_id == "reinvent2026"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            pass

    async def fake_sync(
        _client: object, _repository: object, _output_path: object
    ) -> SyncResult:
        return SyncResult(fetched=2, normalized=2, skipped=0, errors=0)

    class FakeRepository:
        def __init__(self, _path: object) -> None:
            pass

    monkeypatch.setenv("AWS_EVENTS_ACCESS_TOKEN", "private-env-token")
    monkeypatch.setattr(command, "login_with_browser", fake_login)
    monkeypatch.setattr(command, "AwsEventsRestClient", FakeRestClient)
    monkeypatch.setattr(command, "SqliteSessionRepository", FakeRepository)
    monkeypatch.setattr(command, "sync_catalog", fake_sync)

    assert asyncio.run(command.run(login=True)) == 0
    assert received_tokens == ["private-interactive-token"]
    captured = capsys.readouterr()
    assert "Fetched: 2" in captured.out
    assert "private-interactive-token" not in captured.out + captured.err
    assert "private-env-token" not in captured.out + captured.err
