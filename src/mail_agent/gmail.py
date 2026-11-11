"""Thin Gmail API helpers."""
from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Skip Gmail's own low-value tabs.
NOISE_FILTER = "-category:promotions -category:social -category:forums"
AUTOMATED_HINTS = ("noreply", "no-reply", "donotreply", "do-not-reply", "notifications@", "mailer-daemon")


@dataclass
class Email:
    id: str
    thread_id: str
    sender: str
    reply_to: str
    subject: str
    date: str
    snippet: str
    body: str
    message_id: str
    references: str
    unread: bool

    @property
    def sender_name(self) -> str:
        name, addr = parseaddr(self.sender)
        return name or addr

    @property
    def is_automated(self) -> bool:
        addr = parseaddr(self.sender)[1].lower()
        return any(h in addr for h in AUTOMATED_HINTS)

    def as_prompt(self, max_chars: int = 1500) -> str:
        body = self.body or self.snippet
        if len(body) > max_chars:
            body = body[:max_chars] + "\n[...truncated]"
        return f"From: {self.sender}\nDate: {self.date}\nSubject: {self.subject}\n\n{body}"


def build_service(creds):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\r\f\v\u00a0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _extract_body(payload: dict) -> str:
    plain: list[str] = []
    htmls: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            htmls.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    if htmls:
        return _html_to_text("\n".join(htmls))
    return ""


def _parse(msg: dict) -> Email:
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return Email(
        id=msg["id"],
        thread_id=msg["threadId"],
        sender=headers.get("from", ""),
        reply_to=headers.get("reply-to", ""),
        subject=headers.get("subject", "(no subject)"),
        date=headers.get("date", ""),
        snippet=html.unescape(msg.get("snippet", "")),
        body=_extract_body(msg["payload"]),
        message_id=headers.get("message-id", ""),
        references=headers.get("references", ""),
        unread="UNREAD" in msg.get("labelIds", []),
    )


def get_email(svc, msg_id: str) -> Email:
    return _parse(svc.users().messages().get(userId="me", id=msg_id, format="full").execute())


def search(svc, query: str, max_results: int = 10) -> list[Email]:
    resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return [get_email(svc, m["id"]) for m in resp.get("messages", [])]


def fetch_new(svc, since_epoch: int, max_results: int) -> list[Email]:
    return search(svc, f"in:inbox is:unread after:{since_epoch} {NOISE_FILTER}", max_results)


def is_unread(svc, msg_id: str) -> bool:
    try:
        msg = svc.users().messages().get(userId="me", id=msg_id, format="minimal").execute()
    except HttpError:
        return False  # deleted or inaccessible
    return "UNREAD" in msg.get("labelIds", [])


def create_reply_draft(svc, original: Email, body: str) -> str:
    """Save a reply as a Gmail draft in the same thread. Never sends."""
    msg = EmailMessage()
    msg["To"] = original.reply_to or original.sender
    subject = original.subject
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if original.message_id:
        msg["In-Reply-To"] = original.message_id
        msg["References"] = f"{original.references} {original.message_id}".strip()
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = svc.users().drafts().create(
        userId="me", body={"message": {"raw": raw, "threadId": original.thread_id}}
    ).execute()
    return draft["id"]
