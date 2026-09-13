import secrets
from fastapi import HTTPException, Request


def require_api_key(request: Request) -> None:
    """Protect provider-backed endpoints when an API key is configured."""
    expected = getattr(request.app.state.settings, "runsense_api_key", "")
    if expected and not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {expected}"):
        raise HTTPException(status_code=401, detail="Missing or invalid RunSense API key")
