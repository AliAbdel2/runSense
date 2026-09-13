"""Contract tests for integrations; all provider traffic is mocked."""

import asyncio
import base64
import json
from dataclasses import replace
from urllib.parse import parse_qsl

import httpx

from runsense.delivery import (
    clip_id,
    clip_path,
    read_clip,
    send_sms_notice,
    speak,
    twilio_configured,
)
from runsense.integrations import (
    CalendarClient,
    ElevenLabsClient,
    IntegrationError,
    NotionClient,
    Settings,
    SheetsClient,
    TwilioClient,
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


def test_elevenlabs_rejects_empty_audio_response():
    settings = Settings(elevenlabs_api_key="secret", elevenlabs_voice_id="voice", elevenlabs_model_id="model")
    async def operation():
        async with ElevenLabsClient(settings, httpx.MockTransport(lambda r: httpx.Response(200, content=b""))) as client:
            await client.synthesize("Go.")
    try:
        run(operation())
    except IntegrationError as exc:
        assert "empty audio" in str(exc)
        assert "secret" not in str(exc)
    else:
        raise AssertionError("expected empty audio to be rejected")


def _twilio_settings(**overrides):
    value = {"twilio_account_sid": "AC123", "twilio_auth_token": "secret-token",
             "twilio_from_number": "+15550000000"}
    value.update(overrides)
    return Settings(**value)


def test_twilio_posts_form_encoded_message_with_basic_auth():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"sid": "SM1", "status": "queued", "to": "+15551234567"})

    async def operation():
        async with TwilioClient(_twilio_settings(), httpx.MockTransport(handler)) as client:
            return await client.send_sms("+15551234567", "Your guide cancelled.")
    result = run(operation())
    assert result["sid"] == "SM1" and result["status"] == "queued"
    request = requests[0]
    assert request.url.path == "/2010-04-01/Accounts/AC123/Messages.json"
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    credentials = base64.b64decode(request.headers["authorization"].split()[1]).decode()
    assert credentials == "AC123:secret-token"
    form = dict(parse_qsl(request.content.decode()))
    assert form == {"To": "+15551234567", "From": "+15550000000", "Body": "Your guide cancelled."}


def test_twilio_error_response_is_sanitized_and_not_resent():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"code": 21211, "message": "The 'To' number is not a valid phone number"})

    async def operation():
        async with TwilioClient(_twilio_settings(), httpx.MockTransport(handler)) as client:
            await client.send_sms("+15551234567", "Your guide cancelled.")
    try:
        run(operation())
    except IntegrationError as exc:
        assert exc.status_code == 400
        assert "secret-token" not in str(exc)
        assert "21211" not in str(exc) and "not a valid phone number" not in str(exc)
    else:
        raise AssertionError("expected a provider error")
    # An SMS has no idempotency key, so a failed send is never retried into a duplicate.
    assert len(requests) == 1


def test_twilio_server_error_is_not_retried_into_duplicate_messages():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(503)

    async def operation():
        async with TwilioClient(_twilio_settings(), httpx.MockTransport(handler)) as client:
            await client.send_sms("+15551234567", "Hello.")
    try:
        run(operation())
    except IntegrationError as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("expected a provider error")
    assert len(requests) == 1


def test_twilio_requires_configuration_and_nonempty_message():
    def unreachable(request):
        raise AssertionError("no request should be made without valid inputs")
    transport = httpx.MockTransport(unreachable)

    async def missing_credentials():
        async with TwilioClient(Settings(), transport) as client:
            await client.send_sms("+15551234567", "Hello.")
    try:
        run(missing_credentials())
    except IntegrationError as exc:
        assert "TWILIO_ACCOUNT_SID" in str(exc)
    else:
        raise AssertionError("expected missing configuration to be reported")

    for to, body, expected in [("", "Hello.", "phone number is empty"), ("+1555", "  ", "message body is empty")]:
        async def bad_input(to=to, body=body):
            async with TwilioClient(_twilio_settings(), transport) as client:
                await client.send_sms(to, body)
        try:
            run(bad_input())
        except IntegrationError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected invalid SMS input to be rejected")


def test_twilio_settings_from_env(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC999")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "")
    settings = Settings.from_env()
    assert settings.twilio_account_sid == "AC999"
    assert settings.twilio_auth_token == "token"
    # An empty environment variable is absent, so the integration stays unconfigured.
    assert settings.twilio_from_number is None
    assert twilio_configured(settings) is False


# --- delivery layer: honest no-ops, deterministic cache, real provider calls ---


def _voice_settings():
    return Settings(elevenlabs_api_key="secret", elevenlabs_voice_id="voice", elevenlabs_model_id="model")


def test_speak_caches_audio_under_a_deterministic_clip_id(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"ID3-audio")
    transport = httpx.MockTransport(handler)
    settings, directory = _voice_settings(), str(tmp_path / "audio")

    clip = run(speak("Turn left in ten metres.", settings, transport, directory))
    assert clip == clip_id("Turn left in ten metres.", settings)
    assert read_clip(clip, directory) == b"ID3-audio"
    # A repeated identical cue is served from the cache; the provider is called once.
    assert run(speak("Turn left in ten metres.", settings, transport, directory)) == clip
    assert len(calls) == 1
    # A different cue, voice or model is a different clip.
    assert run(speak("Turn right.", settings, transport, directory)) != clip
    assert len(calls) == 2
    other = replace(settings, elevenlabs_voice_id="other-voice")
    assert clip_id("Turn left in ten metres.", other) != clip


def test_speak_without_credentials_is_an_honest_noop(tmp_path):
    def unreachable(request):
        raise AssertionError("an unconfigured integration must not be called")
    transport = httpx.MockTransport(unreachable)
    directory = str(tmp_path / "audio")
    assert run(speak("Turn left.", Settings(), transport, directory)) == "tts_not_configured"
    assert run(speak("Turn left.", replace(_voice_settings(), elevenlabs_voice_id=None), transport, directory)) == "tts_not_configured"
    assert run(speak("   ", _voice_settings(), transport, directory)) == "tts_empty_text"
    assert not list(tmp_path.glob("audio/*"))


def test_speak_provider_failure_does_not_raise_into_the_caller(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"detail": "do not expose"}))
    assert run(speak("Turn left.", _voice_settings(), transport, str(tmp_path / "audio"))) == "tts_failed"
    assert not list(tmp_path.glob("audio/*"))


def test_read_clip_rejects_ids_that_are_not_cache_keys(tmp_path):
    directory = str(tmp_path / "audio")
    (tmp_path / "secret.mp3").write_bytes(b"private")
    for bad in ["../secret", "/etc/passwd", "not-hex-at-all", "AB" * 16, "", "a" * 31]:
        assert clip_path(bad, directory) is None
        assert read_clip(bad, directory) is None


def test_send_sms_notice_reports_status_and_never_raises():
    def handler(request):
        return httpx.Response(201, json={"sid": "SM7", "status": "queued"})
    assert run(send_sms_notice("+15551234567", "Rescheduled.", _twilio_settings(),
                               httpx.MockTransport(handler))) == "queued:SM7"

    def unreachable(request):
        raise AssertionError("an unconfigured integration must not be called")
    assert run(send_sms_notice("+15551234567", "Rescheduled.", Settings(),
                               httpx.MockTransport(unreachable))) == "not_configured"
    assert run(send_sms_notice("", "Rescheduled.", _twilio_settings(),
                               httpx.MockTransport(unreachable))) == "sms_invalid_request"
    assert run(send_sms_notice("+15551234567", "Rescheduled.", _twilio_settings(),
                               httpx.MockTransport(lambda r: httpx.Response(500)))) == "sms_failed"
