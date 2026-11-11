"""Desktop notifications via notify-send (KDE Plasma shows these natively)."""
from __future__ import annotations

import html
import shutil
import subprocess


def notify(title: str, body: str, urgent: bool = False) -> None:
    if not shutil.which("notify-send"):
        print(f"[notify] {title}: {body}")
        return
    subprocess.run(
        [
            "notify-send",
            "--app-name=Mail Agent",
            "--icon=mail-unread",
            f"--urgency={'critical' if urgent else 'normal'}",  # critical stays until dismissed
            html.escape(title),
            html.escape(body),
        ],
        check=False,
        timeout=10,
    )
