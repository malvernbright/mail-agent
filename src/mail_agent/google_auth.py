"""OAuth for Gmail + Google Calendar (desktop-app flow, token cached locally)."""
from __future__ import annotations

import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import APP_DIR, CREDENTIALS_FILE, TOKEN_FILE

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",   # read mail
    "https://www.googleapis.com/auth/gmail.compose",    # create drafts (the agent never sends)
    "https://www.googleapis.com/auth/calendar.events",  # read/create calendar events
]


def _save(creds: Credentials) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)


def get_credentials(interactive: bool = True) -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except RefreshError:
            creds = None  # token revoked or expired (7-day limit for apps in "Testing")

    if not interactive:
        raise SystemExit("Google authorization missing or expired. Run: mail-agent auth")
    if not CREDENTIALS_FILE.exists():
        raise SystemExit(
            f"OAuth client file not found: {CREDENTIALS_FILE}\n"
            "Download it from Google Cloud Console (OAuth client, type 'Desktop app')."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    _save(creds)
    return creds
