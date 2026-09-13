"""Contract tests for integrations; all provider traffic is mocked."""

import asyncio
import json

import httpx

from runsense.integrations import (
    CalendarClient,
    ElevenLabsClient,
    IntegrationError,
    NotionClient,
    Settings,
    SheetsClient,
)


def run(coro):
    return asyncio.run(coro)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "token")
    monkeypatch.setenv("SHEETS_SPREADSHEET_ID", "sheet")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_model")
    settings = Settings.from_env()
    assert settings.google_access_token == "token"
    assert settings.sheets_spreadsheet_id == "sheet"
    assert settings.sheets_range == "Training!A1:E100"
    assert settings.google_calendar_id == "primary"
    assert settings.notion_version == "2026-03-11"
    assert settings.elevenlabs_model_id == "eleven_model"


def test_sheets_reads_athlete_authored_rows():
    def handler(request):
        assert request.headers["authorization"] == "Bearer google-token"
        assert request.url.path.endswith("/spreadsheets/sheet/values/Training!A1:E100")
        return httpx.Response(200, json={"values": [
            ["date", "km", "kind", "completed", "source"],
            ["2026-09-07", "5", "easy", "TRUE", "athlete_authored"],
        ]})

    settings = Settings(google_access_token="google-token", sheets_spreadsheet_id="sheet")
    async def operation():
        async with SheetsClient(settings, httpx.MockTransport(handler)) as client:
            return await client.get_activities()
    assert run(operation()) == [{
        "date": "2026-09-07", "km": 5.0, "kind": "easy", "completed": True,
        "source": "athlete_authored",
    }]


def test_sheets_rejects_third_party_source():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"values": [
        ["date", "km", "kind", "completed", "source"],
        ["2026-09-07", "5", "easy", "TRUE", "strava"],
    ]}))
    settings = Settings(google_access_token="secret", sheets_spreadsheet_id="sheet")
    async def operation():
        async with SheetsClient(settings, transport) as client:
            await client.get_activities()
    error = None
    try:
        run(operation())
    except IntegrationError as exc:
        error = exc
    assert error is not None
    assert "strava" not in str(error).lower()
    assert "secret" not in str(error)


def test_sheets_rejects_nonfinite_distance_and_bad_date():
    responses = [
        {"values": [["date", "km", "kind", "completed", "source"],
                     ["2026-09-07", "nan", "easy", "TRUE", "athlete_authored"]]},
        {"values": [["date", "km", "kind", "completed", "source"],
                     ["yesterday", "5", "easy", "TRUE", "athlete_authored"]]},
    ]
    settings = Settings(google_access_token="token", sheets_spreadsheet_id="sheet")
    for body in responses:
        async def operation(body=body):
            async with SheetsClient(settings, httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
                await client.get_activities()
        try:
            run(operation())
        except IntegrationError as exc:
            assert "invalid" in str(exc)
        else:
            raise AssertionError("expected malformed activity to be rejected")


def test_retry_429_honors_capped_retry_after(monkeypatch):
    calls = []
    async def fake_sleep(seconds):
        calls.append(seconds)
    monkeypatch.setattr("runsense.integrations.asyncio.sleep", fake_sleep)

    def handler(request):
        if len(calls) == 0:
            return httpx.Response(429, headers={"Retry-After": "999"})
        return httpx.Response(200, json={"values": []})
    settings = Settings(google_access_token="token", sheets_spreadsheet_id="sheet")
    async def operation():
        async with SheetsClient(settings, httpx.MockTransport(handler)) as client:
            return await client.get_activities()
    assert run(operation()) == []
    assert calls == [2.0]


def _session(**overrides):
    value = {
        "id": "01234567-89ab-cdef-0123-456789abcdef",
        "athlete_id": "athlete-1",
        "date": "2026-09-14",
        "kind": "easy",
        "km": 5,
        "venue": "park",
        "guide_status": "accepted",
        "spoken_summary": "Easy five kilometre run.",
        "rationale": "A steady aerobic session.",
    }
    value.update(overrides)
    return value


def test_calendar_insert_is_deterministic_and_has_no_invites():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": json.loads(request.content)["id"], "summary": "ok"})
    settings = Settings(google_access_token="token", google_calendar_id="primary")
    async def operation():
        async with CalendarClient(settings, httpx.MockTransport(handler)) as client:
            return await client.upsert_session(_session())
    result = run(operation())
    assert result["id"] == "0123456789abcdef0123456789abcdef"
    request = requests[0]
    assert request.url.params["sendUpdates"] == "none"
    body = json.loads(request.content)
    assert body["start"]["dateTime"].startswith("2026-09-14T09:00:00")
    assert body["start"]["timeZone"] == "Europe/Zurich"
    assert "attendees" not in body


def test_calendar_conflict_reconciles_only_owned_event_then_patches():
    requests = []
    expected_id = "0123456789abcdef0123456789abcdef"
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(409, json={"error": "conflict"})
        if request.method == "GET":
            return httpx.Response(200, json={"id": expected_id, "extendedProperties": {
                "private": {"runsense_session_id": _session()["id"]}
            }})
        return httpx.Response(200, json={"id": expected_id, "updated": True})
    settings = Settings(google_access_token="token", google_calendar_id="primary")
    async def operation():
        async with CalendarClient(settings, httpx.MockTransport(handler)) as client:
            return await client.upsert_session(_session())
    assert run(operation())["updated"] is True
    assert [request.method for request in requests] == ["POST", "GET", "PATCH"]
    assert requests[0].url.params["sendUpdates"] == "none"
    assert requests[2].url.params["sendUpdates"] == "none"


def test_calendar_conflict_does_not_patch_unowned_event():
    expected_id = "0123456789abcdef0123456789abcdef"
    def handler(request):
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(200, json={"id": expected_id, "extendedProperties": {"private": {}}})
    settings = Settings(google_access_token="token")
    async def operation():
        async with CalendarClient(settings, httpx.MockTransport(handler)) as client:
            await client.upsert_session(_session())
    try:
        run(operation())
    except IntegrationError as exc:
        assert exc.status_code == 409
        assert "another" in str(exc)
    else:
        raise AssertionError("expected ownership conflict")


def test_calendar_timeout_reconciles_accepted_insert_before_patch():
    expected_id = "0123456789abcdef0123456789abcdef"
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            raise httpx.ReadTimeout("provider timeout")
        if request.method == "GET":
            return httpx.Response(200, json={"id": expected_id, "extendedProperties": {
                "private": {"runsense_session_id": _session()["id"]}
            }})
        return httpx.Response(200, json={"id": expected_id, "updated": True})
    settings = Settings(google_access_token="secret")
    async def operation():
        async with CalendarClient(settings, httpx.MockTransport(handler)) as client:
            return await client.upsert_session(_session())
    assert run(operation())["updated"] is True
    assert [request.method for request in requests] == ["POST", "GET", "PATCH"]


def test_calendar_5xx_reconciles_accepted_insert_before_patch():
    expected_id = "0123456789abcdef0123456789abcdef"
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(503, json={"provider_detail": "private"})
        if request.method == "GET":
            return httpx.Response(200, json={"id": expected_id, "extendedProperties": {
                "private": {"runsense_session_id": _session()["id"]}
            }})
        return httpx.Response(200, json={"id": expected_id, "updated": True})
    settings = Settings(google_access_token="secret")
    async def operation():
        async with CalendarClient(settings, httpx.MockTransport(handler)) as client:
            return await client.upsert_session(_session())
    assert run(operation())["updated"] is True
    assert [request.method for request in requests] == ["POST", "GET", "PATCH"]


def _plan(**overrides):
    value = {
        "id": "plan-1",
        "week_start": "2026-09-14",
        "athlete_name": "Sara",
        "rationale": "Keep the week steady.",
        "week_km": 10,
        "sessions": [{"date": "2026-09-14", "kind": "easy", "km": 5}],
    }
    value.update(overrides)
    return value


def test_notion_queries_plan_id_before_create_and_patches_existing():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": [{"id": "page-1"}]})
        return httpx.Response(200, json={"id": "page-1", "object": "page"})
    settings = Settings(notion_api_key="secret", notion_data_source_id="source")
    async def operation():
        async with NotionClient(settings, httpx.MockTransport(handler)) as client:
            return await client.upsert_plan(_plan())
    assert run(operation())["id"] == "page-1"
    assert [request.method for request in requests] == ["POST", "PATCH"]
    assert requests[0].url.path.endswith("/data_sources/source/query")
    assert json.loads(requests[0].content)["filter"]["property"] == "Plan ID"
    assert json.loads(requests[1].content)["properties"]["Name"]["title"]
    assert "secret" not in json.dumps(json.loads(requests[1].content))


def test_notion_unknown_create_conflict_requeries_then_patches():
    methods = []
    query_count = 0
    def handler(request):
        nonlocal query_count
        methods.append(request.method + " " + request.url.path)
        if request.url.path.endswith("/query"):
            query_count += 1
            return httpx.Response(200, json={"results": [{"id": "page-2"}]}) if query_count == 2 else httpx.Response(200, json={"results": []})
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(200, json={"id": "page-2"})
    settings = Settings(notion_api_key="secret", notion_data_source_id="source")
    async def operation():
        async with NotionClient(settings, httpx.MockTransport(handler)) as client:
            return await client.upsert_plan(_plan())
    assert run(operation())["id"] == "page-2"
    assert methods[0].endswith("/query") and methods[1].endswith("/pages")
    assert methods[2].endswith("/query") and methods[3].endswith("/pages/page-2")


def test_notion_create_5xx_reconciles_without_retrying_create():
    requests = []
    settings = Settings(notion_api_key="secret", notion_data_source_id="source")
    # The initial lookup is empty, create is uncertain, reconciliation finds
    # the page, then patch is the only follow-up write.
    count = 0
    def handler_with_race(request):
        nonlocal count
        count += 1
        requests.append(request)
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"results": [] if count == 1 else [{"id": "page-3"}]})
        if request.method == "POST":
            return httpx.Response(503, json={"provider_detail": "do not expose"})
        return httpx.Response(200, json={"id": "page-3"})
    async def raced_operation():
        async with NotionClient(settings, httpx.MockTransport(handler_with_race)) as client:
            return await client.upsert_plan(_plan())
    assert run(raced_operation())["id"] == "page-3"
    assert [r.url.path for r in requests] == [
        "/v1/data_sources/source/query", "/v1/pages", "/v1/data_sources/source/query", "/v1/pages/page-3"
    ]
    assert sum(r.url.path.endswith("/pages") for r in requests) == 1


def test_notion_create_timeout_reconciles_and_does_not_retry_create():
    requests = []
    settings = Settings(notion_api_key="secret", notion_data_source_id="source")
    count = 0
    def timeout_then_reconcile(request):
        nonlocal count
        requests.append(request)
        if request.url.path.endswith("/query"):
            count += 1
            return httpx.Response(200, json={"results": [{"id": "page-4"}]}) if count == 2 else httpx.Response(200, json={"results": []})
        if request.method == "POST":
            raise httpx.ReadTimeout("provider timeout")
        return httpx.Response(200, json={"id": "page-4"})
    async def raced_operation():
        async with NotionClient(settings, httpx.MockTransport(timeout_then_reconcile)) as client:
            return await client.upsert_plan(_plan())
    assert run(raced_operation())["id"] == "page-4"
    assert [r.url.path for r in requests] == [
        "/v1/data_sources/source/query", "/v1/pages", "/v1/data_sources/source/query", "/v1/pages/page-4"
    ]
    assert sum(r.url.path.endswith("/pages") for r in requests) == 1


def test_elevenlabs_returns_audio_bytes():
    def handler(request):
        assert request.headers["xi-api-key"] == "secret"
        assert json.loads(request.content) == {"text": "Go.", "model_id": "model"}
        return httpx.Response(200, content=b"audio")
    settings = Settings(elevenlabs_api_key="secret", elevenlabs_voice_id="voice", elevenlabs_model_id="model")
    async def operation():
        async with ElevenLabsClient(settings, httpx.MockTransport(handler)) as client:
            return await client.synthesize("Go.")
    assert run(operation()) == b"audio"
