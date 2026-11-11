"""Thin Google Calendar API helpers. Times use the system's local timezone."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from googleapiclient.discovery import build


def build_service(creds):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def list_events(svc, days: int = 7) -> list[str]:
    now = datetime.now().astimezone()
    resp = svc.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=(now + timedelta(days=days)).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=100,
    ).execute()
    out = []
    for ev in resp.get("items", []):
        start = ev["start"].get("dateTime") or ev["start"].get("date")
        end = ev["end"].get("dateTime") or ev["end"].get("date")
        out.append(f"{start} -> {end}  {ev.get('summary', '(no title)')}")
    return out


def create_event(
    svc,
    title: str,
    day: date,
    start: time | None,
    duration_minutes: int = 60,
    description: str = "",
    reminder_minutes: int = 30,
) -> dict:
    body: dict = {"summary": title, "description": description}
    if start is None:  # all-day (end date is exclusive)
        body["start"] = {"date": day.isoformat()}
        body["end"] = {"date": (day + timedelta(days=1)).isoformat()}
        reminder_minutes = max(reminder_minutes, 9 * 60)  # morning-of style reminder
    else:
        start_dt = datetime.combine(day, start).astimezone()
        end_dt = start_dt + timedelta(minutes=max(5, duration_minutes))
        body["start"] = {"dateTime": start_dt.isoformat()}
        body["end"] = {"dateTime": end_dt.isoformat()}
    body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": reminder_minutes}]}
    return svc.events().insert(calendarId="primary", body=body).execute()
