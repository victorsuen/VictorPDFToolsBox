from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def audit_log_path() -> Path:
    return Path.home() / ".victor_pdf_toolbox" / "audit.log"


@dataclass(frozen=True)
class AuditEvent:
    timestamp: str
    operation: str
    source: str = ""
    target: str = ""
    detail: str = ""


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


def read_audit_events(limit: int = 500, path: Path | None = None) -> list[AuditEvent]:
    """Return audit rows, newest first."""

    log = path or audit_log_path()
    if not log.exists():
        return []
    events: list[AuditEvent] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            parts = parts + [""] * (5 - len(parts))
        events.append(
            AuditEvent(
                timestamp=parts[0],
                operation=parts[1],
                source=parts[2],
                target=parts[3],
                detail=parts[4],
            )
        )
    events.reverse()
    if limit and limit > 0:
        return events[:limit]
    return events
