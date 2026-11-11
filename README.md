# mail-agent

A local Ollama assistant for Gmail and Google Calendar, managed with `uv`.

- `mail-agent check`: triages new unread email, sends KDE desktop notifications for important ones,
  saves reply **drafts** in Gmail (it never sends), and re-reminds you about important mail you haven't read.
- `mail-agent plan`: turns your tasks for the week or month into Google Calendar events, showing you the plan before creating anything.
- `mail-agent chat`: a tool-calling agent ("what did Alice want?", "draft a reply to that", "what's on Thursday?").
  Anything that writes asks you first.
- `mail-agent pending`: important emails you still haven't read.

## 1. Ollama

```bash
sudo systemctl enable --now ollama
ollama pull qwen3.5:4b        # already on your machine; the default model
```

## 2. Google Cloud (one-time, ~10 minutes)

1. Go to https://console.cloud.google.com, create a project (e.g. "mail-agent").
2. **APIs & Services → Library**: enable **Gmail API** and **Google Calendar API**.
3. **Google Auth Platform** (OAuth consent screen): app type **External**, fill in the name and your email,
   and under **Audience → Test users** add your own Gmail address.
4. **Clients → Create client → Desktop app**. Download the JSON and save it as
   `~/.config/mail-agent/credentials.json`.

**Gotcha:** while the app's publishing status is "Testing", Google expires your login every 7 days,
which will quietly break the timer. To avoid that, go to **Audience → Publish app**. It's fine to stay
unverified for personal use; at sign-in you click *Advanced → Go to mail-agent (unsafe)* once.

Scopes requested: read Gmail, create drafts, and manage calendar events.

## 3. Install & sign in

```bash
cd mail-agent
uv sync
uv run mail-agent auth        # opens the browser once
uv run mail-agent config      # edit about_me, vip_senders, signature, model...
```

## 4. Use it

```bash
uv run mail-agent check --dry-run   # see how it rates your inbox without changing anything
uv run mail-agent check
uv run mail-agent plan "Gym Mon/Wed/Fri 6am. Finish client report by Thursday. Dentist on the 20th at 14:30"
uv run mail-agent plan              # opens $EDITOR for a longer list
uv run mail-agent plan -f tasks.md
uv run mail-agent chat
```

## 5. Run it automatically (every 30 min)

```bash
uv tool install --editable .        # puts `mail-agent` in ~/.local/bin
mkdir -p ~/.config/systemd/user
cp systemd/mail-agent.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mail-agent.timer

systemctl --user list-timers mail-agent.timer    # next run
journalctl --user -u mail-agent -f               # logs
```

## Choosing a model

Your laptop runs models on the CPU (the "llvmpipe" graphics line means no GPU acceleration),
so expect roughly 10-20 s per email with `qwen3.5:4b`. That's fine for a background timer.

| Model | Where it runs | Notes |
|---|---|---|
| `qwen3.5:4b` (default) | local | Private. Best tool calling of your local models. |
| `llama3.2:latest` | local | Slightly faster, weaker at tool calling and planning. |
| `gpt-oss:20b-cloud`, `kimi-k2.5:cloud` | Ollama cloud | Much faster and smarter, but your email text leaves your machine. |

A good mix is `model = "qwen3.5:4b"` with `draft_model = "gpt-oss:20b-cloud"` if you're OK sending
only the important emails to the cloud for drafting. The `qwen2.5-coder` and embedding models aren't useful here.

## Safety notes

- Emails are untrusted input (prompt injection). That's why the agent can only *draft* (never send),
  and in chat mode every calendar event and draft needs your confirmation.
- Tokens live in `~/.config/mail-agent/token.json` (chmod 600). Revoke access any time at
  https://myaccount.google.com/permissions.

## Files

```
~/.config/mail-agent/
  config.toml        your settings
  credentials.json   OAuth client from Google Cloud
  token.json         your login (created by `mail-agent auth`)
  state.json         seen/flagged emails, last check time
```
