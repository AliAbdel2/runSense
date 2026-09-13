"""Real delivery for the live-session tools: cached ElevenLabs speech and Twilio SMS.

Both channels are optional.  When credentials are absent these helpers return an
honest marker string instead of raising, so an unconfigured optional integration
never fails a planning or adaptation run.  Nothing here silently pretends to have
delivered: every outcome is a distinct, reportable string.

Audio is cached on disk (``RUNSENSE_AUDIO_DIR``, default ``data/audio``) rather
than in a new database table.  The payload is an opaque MP3 blob that the API
route only streams back verbatim, so a file keyed by a deterministic clip ID is
the smaller mechanism and keeps Phase 1's typed schema untouched.  The clip ID is
a hash of text plus voice plus model, giving the same replay safety the Calendar
and Notion upserts get from their deterministic IDs: re-speaking an identical cue
reuses the cached bytes and never bills the provider twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .integrations import ElevenLabsClient, IntegrationError, Settings, TwilioClient

DEFAULT_AUDIO_DIR = "data/audio"
CLIP_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# Honest, machine-checkable outcomes.  ``SMS_NOT_CONFIGURED`` keeps the exact
# string the Phase 2 sms_notify stub already returned.
TTS_NOT_CONFIGURED = "tts_not_configured"
TTS_EMPTY_TEXT = "tts_empty_text"
TTS_FAILED = "tts_failed"
SMS_NOT_CONFIGURED = "not_configured"
SMS_INVALID_REQUEST = "sms_invalid_request"
SMS_FAILED = "sms_failed"


def audio_dir(path: str | None = None) -> Path:
    return Path(path or os.getenv("RUNSENSE_AUDIO_DIR") or DEFAULT_AUDIO_DIR)


def clip_id(text: str, settings: Settings) -> str:
    """Deterministic cache key for one spoken cue in one voice and model."""
    digest = hashlib.sha256(
        "\x00".join([text, settings.elevenlabs_voice_id or "", settings.elevenlabs_model_id or ""]).encode()
    )
    return digest.hexdigest()[:32]


def clip_path(clip: str, path: str | None = None) -> Path | None:
    """Resolve a clip ID to its file, rejecting anything that is not a clip ID.

    The strict pattern is what makes a caller-supplied ID safe to join onto a
    directory: no separators, no traversal, no absolute paths.
    """
    if not isinstance(clip, str) or not CLIP_ID_PATTERN.match(clip):
        return None
    return audio_dir(path) / f"{clip}.mp3"


def read_clip(clip: str, path: str | None = None) -> bytes | None:
    """Return cached audio bytes, or None when the ID is unknown or malformed."""
    resolved = clip_path(clip, path)
    if resolved is None:
        return None
    try:
        return resolved.read_bytes()
    except OSError:
        return None


def write_clip(clip: str, audio: bytes, path: str | None = None) -> Path:
    """Write cached audio atomically so a reader never sees a partial file."""
    resolved = clip_path(clip, path)
    if resolved is None:
        raise ValueError("Audio clip ID is not a valid cache key.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f"{resolved.name}.{os.getpid()}.part")
    temporary.write_bytes(audio)
    os.replace(temporary, resolved)
    return resolved


def elevenlabs_configured(settings: Settings) -> bool:
    return bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id and settings.elevenlabs_model_id)


def twilio_configured(settings: Settings) -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number)


async def speak(text: str, settings: Settings | None = None, transport=None,
                audio_path: str | None = None) -> str:
    """Synthesize and cache one coaching cue; return its clip ID or an honest marker."""
    if not isinstance(text, str) or not text.strip():
        return TTS_EMPTY_TEXT
    settings = settings or Settings.from_env()
    if not elevenlabs_configured(settings):
        return TTS_NOT_CONFIGURED
    clip = clip_id(text, settings)
    if read_clip(clip, audio_path) is not None:
        # Identical cue, voice and model: reuse the cached bytes rather than
        # paying for and waiting on a second identical synthesis.
        return clip
    try:
        async with ElevenLabsClient(settings, transport) as client:
            audio = await client.synthesize(text)
    except IntegrationError:
        # Provider detail stays inside IntegrationError; a failed optional cue
        # must not take down the caller's run.
        return TTS_FAILED
    try:
        write_clip(clip, audio, audio_path)
    except OSError:
        return TTS_FAILED
    return clip


async def send_sms_notice(to: str, text: str, settings: Settings | None = None, transport=None) -> str:
    """Send one SMS; return ``status:sid`` or an honest marker. Never raises."""
    settings = settings or Settings.from_env()
    if not twilio_configured(settings):
        return SMS_NOT_CONFIGURED
    if not isinstance(to, str) or not to.strip() or not isinstance(text, str) or not text.strip():
        return SMS_INVALID_REQUEST
    try:
        async with TwilioClient(settings, transport) as client:
            message = await client.send_sms(to, text)
    except IntegrationError:
        return SMS_FAILED
    status = str(message.get("status") or "unknown")
    sid = str(message.get("sid") or "")
    return f"{status}:{sid}" if sid else status


def blocking(coro):
    """Run an async delivery helper from a synchronous LangChain tool call.

    A sync tool may be invoked from plain code or, via LangChain's executor
    fallback, from a worker thread.  Calling it from inside a live event loop
    would deadlock ``asyncio.run``, so that case is handed to its own thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = [
    "DEFAULT_AUDIO_DIR",
    "SMS_FAILED",
    "SMS_INVALID_REQUEST",
    "SMS_NOT_CONFIGURED",
    "TTS_EMPTY_TEXT",
    "TTS_FAILED",
    "TTS_NOT_CONFIGURED",
    "audio_dir",
    "blocking",
    "clip_id",
    "clip_path",
    "elevenlabs_configured",
    "read_clip",
    "send_sms_notice",
    "speak",
    "twilio_configured",
    "write_clip",
]
