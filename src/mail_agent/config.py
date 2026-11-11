"""Configuration (TOML) and on-disk state (JSON) in ~/.config/mail-agent."""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR = Path(os.environ.get("MAIL_AGENT_HOME", Path.home() / ".config" / "mail-agent"))
CONFIG_FILE = APP_DIR / "config.toml"
CREDENTIALS_FILE = APP_DIR / "credentials.json"
TOKEN_FILE = APP_DIR / "token.json"
STATE_FILE = APP_DIR / "state.json"

DEFAULT_CONFIG = '''\
# Mail Agent configuration

# Ollama model for triage, planning and chat.
#   Local (private, slower on CPU): "qwen3.5:4b" (best local tool-caller you have), "llama3.2:latest"
#   Cloud (fast, but email text is sent to Ollama's servers): "gpt-oss:20b-cloud", "kimi-k2.5:cloud"
model = "qwen3.5:4b"

# Optional separate model for writing reply drafts ("" = same as model).
draft_model = ""

ollama_host = "http://localhost:11434"

# Qwen3.5 "thinks" by default. Off is much faster on CPU and fine for these tasks.
think = false

num_ctx = 8192

# First run looks back this far; later runs continue from the last check.
lookback_hours = 24
max_emails = 20

# 1-10. Emails at or above this get a desktop notification (and a reply draft if one is needed).
importance_threshold = 7
auto_draft = true

# Re-notify about important emails that are still unread after this many hours.
remind_every_hours = 4

# Helps the model judge importance and write drafts in your voice.
about_me = """
I'm a software developer. Emails from clients, about payments, job opportunities
or deadlines matter most. Newsletters and automated notifications are low priority.
"""

# Always treated as important (case-insensitive substring match on the From header).
# Example: vip_senders = ["boss@company.com", "@bigclient.com"]
vip_senders = []

# Appended to every reply draft.
signature = """
Best regards,
Your Name
"""
'''


@dataclass
class Config:
    model: str = "qwen3.5:4b"
    draft_model: str = ""
    ollama_host: str = "http://localhost:11434"
    think: bool = False
    num_ctx: int = 8192
    lookback_hours: int = 24
    max_emails: int = 20
    importance_threshold: int = 7
    auto_draft: bool = True
    remind_every_hours: float = 4
    about_me: str = ""
    vip_senders: list[str] = field(default_factory=list)
    signature: str = ""

    @classmethod
    def load(cls) -> "Config":
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            CONFIG_FILE.write_text(DEFAULT_CONFIG)
        data = tomllib.loads(CONFIG_FILE.read_text())
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class State:
    last_check: float = 0.0
    seen_ids: list[str] = field(default_factory=list)
    # message id -> {subject, sender, summary, importance, flagged_at, reminded_at, drafted}
    flagged: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "State":
        if STATE_FILE.exists():
            try:
                return cls(**json.loads(STATE_FILE.read_text()))
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.seen_ids = self.seen_ids[-1000:]
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(STATE_FILE)
