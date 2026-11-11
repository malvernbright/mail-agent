"""mail-agent command line: auth, check, plan, chat, pending, config."""
from __future__ import annotations

import sys
import time
from contextlib import nullcontext
from datetime import date, time as dtime
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from . import gcal, gmail
from .config import CONFIG_FILE, Config, State
from .google_auth import get_credentials
from .llm import LLM
from .notify import notify

app = typer.Typer(help="Local Ollama assistant for Gmail and Google Calendar.", no_args_is_help=True)
console = Console()

PLAN_TEMPLATE = """\
# Write your tasks below, one per line. Lines starting with # are ignored.
# Examples:
#   Gym Mon/Wed/Fri at 6am, 1 hour
#   Finish the client report by Thursday
#   Dentist on the 20th at 14:30
#   This month: renew car insurance, call the bank about the card
"""


def _llm(cfg: Config) -> LLM:
    llm = LLM(cfg)
    try:
        llm.client.show(cfg.model)
    except Exception as exc:
        console.print(f"[red]Can't use model '{cfg.model}' at {cfg.ollama_host}:[/] {exc}")
        console.print("Is Ollama running?  sudo systemctl enable --now ollama")
        raise typer.Exit(1)
    return llm


def _importance_style(n: int) -> str:
    return "bold red" if n >= 9 else "yellow" if n >= 7 else "dim"


@app.command()
def auth() -> None:
    """Sign in to Google (opens your browser once)."""
    get_credentials(interactive=True)
    console.print("[green]Authorized for Gmail and Google Calendar.[/]")


@app.command()
def config() -> None:
    """Open the config file in your $EDITOR."""
    Config.load()  # creates the default file if missing
    click.edit(filename=str(CONFIG_FILE))
    console.print(f"Config: {CONFIG_FILE}")


@app.command()
def check(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="No output, never open a browser (for timers)."),
    no_drafts: bool = typer.Option(False, "--no-drafts", help="Don't create reply drafts this run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only: no drafts, notifications or saved state."),
) -> None:
    """Triage new unread email, notify you about important ones and draft replies."""
    cfg, state = Config.load(), State.load()
    llm = _llm(cfg)
    svc = gmail.build_service(get_credentials(interactive=not quiet))

    now = time.time()
    since = state.last_check - 300 if state.last_check else now - cfg.lookback_hours * 3600
    seen = set(state.seen_ids)
    emails = [e for e in gmail.fetch_new(svc, int(since), cfg.max_emails) if e.id not in seen]

    results = []
    for i, email in enumerate(emails, 1):
        status = nullcontext() if quiet else console.status(f"[{i}/{len(emails)}] {email.subject[:70]}")
        with status:
            t = llm.triage(email.as_prompt())
            if any(v and v.lower() in email.sender.lower() for v in cfg.vip_senders):
                t.importance = max(t.importance, 9)
            important = t.importance >= cfg.importance_threshold
            drafted = False
            if (important and t.needs_reply and cfg.auto_draft and not no_drafts
                    and not dry_run and not email.is_automated):
                gmail.create_reply_draft(svc, email, llm.draft_reply(email.as_prompt(3000)))
                drafted = True
        results.append((email, t, drafted))
        if not dry_run:
            state.seen_ids.append(email.id)
            if important:
                state.flagged[email.id] = {
                    "subject": email.subject, "sender": email.sender_name, "summary": t.summary,
                    "importance": t.importance, "flagged_at": now, "reminded_at": now, "drafted": drafted,
                }

    new_important = [r for r in results if r[1].importance >= cfg.importance_threshold]
    if not dry_run:
        _notify_new(new_important)
        _remind_unread(svc, state, cfg, now, skip={e.id for e, _, _ in results})
        state.last_check = now
        state.save()

    if not quiet:
        if not results:
            console.print("[green]No new unread email.[/]")
            return
        table = Table(title=f"{len(results)} new email(s), {len(new_important)} important")
        for col in ("Imp", "From", "Subject", "What it wants", "Draft"):
            table.add_column(col, overflow="fold")
        for e, t, d in sorted(results, key=lambda r: -r[1].importance):
            table.add_row(f"[{_importance_style(t.importance)}]{t.importance}[/]", e.sender_name[:28],
                          e.subject[:50], t.summary, "yes" if d else "")
        console.print(table)


def _notify_new(important: list) -> None:
    if not important:
        return
    if len(important) <= 3:
        for e, t, drafted in important:
            body = f"{e.subject}\n{t.summary}" + ("\nReply draft is waiting in Gmail." if drafted else "")
            notify(f"{t.importance}/10 · {e.sender_name}", body, urgent=t.importance >= 9)
    else:
        lines = "\n".join(f"• {e.sender_name}: {e.subject}" for e, _, _ in important[:6])
        notify(f"{len(important)} important emails", lines, urgent=any(t.importance >= 9 for _, t, _ in important))


def _remind_unread(svc, state: State, cfg: Config, now: float, skip: set[str]) -> None:
    due = []
    for mid, info in list(state.flagged.items()):
        if mid in skip:
            continue
        if now - info["flagged_at"] > 7 * 86400:
            del state.flagged[mid]  # give up after a week
            continue
        if now - info["reminded_at"] < cfg.remind_every_hours * 3600:
            continue
        if not gmail.is_unread(svc, mid):
            del state.flagged[mid]  # you've read it
            continue
        info["reminded_at"] = now
        due.append(info)
    if due:
        notify(f"Still unread: {len(due)} important email(s)",
               "\n".join(f"• {i['sender']}: {i['subject']}" for i in due[:6]))


@app.command()
def pending() -> None:
    """Show important emails you haven't read yet."""
    state = State.load()
    svc = gmail.build_service(get_credentials())
    for mid in [m for m in state.flagged if not gmail.is_unread(svc, m)]:
        del state.flagged[mid]
    state.save()
    if not state.flagged:
        console.print("[green]Nothing important waiting.[/]")
        return
    table = Table(title="Important & unread")
    for col in ("Imp", "From", "Subject", "What it wants", "Draft"):
        table.add_column(col, overflow="fold")
    for info in sorted(state.flagged.values(), key=lambda i: -i["importance"]):
        table.add_row(str(info["importance"]), info["sender"][:28], info["subject"][:50],
                      info["summary"], "yes" if info.get("drafted") else "")
    console.print(table)


@app.command()
def plan(
    tasks: str = typer.Argument(None, help="Tasks as text. Omit to use --file, stdin or your $EDITOR."),
    file: Path = typer.Option(None, "--file", "-f", exists=True, dir_okay=False, help="Read tasks from a file."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Create events without asking."),
) -> None:
    """Turn your tasks for the week or month into Google Calendar events."""
    if tasks:
        text = tasks
    elif file:
        text = file.read_text()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        edited = click.edit(PLAN_TEMPLATE, extension=".md") or ""
        text = "\n".join(l for l in edited.splitlines() if not l.lstrip().startswith("#"))
    if not text.strip():
        console.print("[yellow]No tasks given.[/]")
        raise typer.Exit(1)

    cfg = Config.load()
    llm = _llm(cfg)
    cal = gcal.build_service(get_credentials())
    with console.status("Reading your calendar..."):
        existing = gcal.list_events(cal, days=42)
    with console.status(f"Planning with {cfg.model} (can take a minute on CPU)..."):
        result = llm.parse_plan(text, existing)

    events = []
    for ev in result.events:
        try:
            day = date.fromisoformat(ev.date)
            start = dtime.fromisoformat(ev.start_time) if ev.start_time else None
        except ValueError:
            console.print(f"[yellow]Skipping '{ev.title}': bad date/time {ev.date} {ev.start_time}[/]")
            continue
        events.append((ev, day, start))
    if not events:
        console.print("[red]The model didn't produce any usable events. Try rephrasing or a bigger model.[/]")
        raise typer.Exit(1)

    events.sort(key=lambda x: (x[1], x[2] or dtime.min))
    table = Table(title="Proposed events")
    for col in ("Day", "Time", "Duration", "Title", "Notes"):
        table.add_column(col, overflow="fold")
    for ev, day, start in events:
        table.add_row(f"{day:%a %d %b}", start.strftime("%H:%M") if start else "all day",
                      f"{ev.duration_minutes} min" if start else "", ev.title, ev.notes)
    console.print(table)

    if not yes and not Confirm.ask(f"Create these {len(events)} events in Google Calendar?"):
        console.print("Nothing created. Rephrase and run again if something's off.")
        raise typer.Exit()
    for ev, day, start in events:
        created = gcal.create_event(cal, ev.title, day, start, ev.duration_minutes, ev.notes)
        console.print(f"[green]✓[/] {ev.title}  [dim]{created.get('htmlLink')}[/]")


@app.command()
def chat() -> None:
    """Chat with your assistant: search mail, check your calendar, add events, save drafts."""
    from .agent import run_chat

    cfg = Config.load()
    llm = _llm(cfg)
    creds = get_credentials()
    run_chat(console, llm, gmail.build_service(creds), gcal.build_service(creds))
