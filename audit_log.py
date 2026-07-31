from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def audit_log_path() -> Path:
    return Path.home() / ".victor_pdf_toolbox" / "audit.log"


def append_audit_event(
    operation: str,
    source: str = "",
    target: str = "",
    detail: str = "",
) -> None:
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    line = f"{timestamp}\t{operation}\t{source}\t{target}\t{detail}\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
