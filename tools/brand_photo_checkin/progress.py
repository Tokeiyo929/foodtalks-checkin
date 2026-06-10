from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .models import JsonValue

PROGRESS_JSON: Final = "progress.json"
PROGRESS_TEXT: Final = "progress.txt"


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    phase: str
    status: str
    total: int
    completed: int
    skipped: int
    failed: int
    current_id: str
    message: str
    updated_at: str


def write_progress(
    run_dir: Path,
    *,
    phase: str,
    status: str,
    total: int,
    completed: int,
    skipped: int,
    failed: int,
    current_id: str,
    message: str,
) -> None:
    snapshot = ProgressSnapshot(
        phase=phase,
        status=status,
        total=total,
        completed=completed,
        skipped=skipped,
        failed=failed,
        current_id=current_id,
        message=message,
        updated_at=datetime.now(UTC).isoformat(),
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    try_write_json_atomic(run_dir / PROGRESS_JSON, progress_json(snapshot))
    try_write_text_atomic(run_dir / PROGRESS_TEXT, progress_text(snapshot))


def progress_json(snapshot: ProgressSnapshot) -> JsonValue:
    return asdict(snapshot)


def progress_text(snapshot: ProgressSnapshot) -> str:
    done = snapshot.completed + snapshot.failed
    percent = 0.0 if snapshot.total == 0 else done / snapshot.total * 100
    return (
        f"phase: {snapshot.phase}\n"
        f"status: {snapshot.status}\n"
        f"progress: {done}/{snapshot.total} ({percent:.1f}%)\n"
        f"completed: {snapshot.completed}\n"
        f"skipped: {snapshot.skipped}\n"
        f"failed: {snapshot.failed}\n"
        f"current: {snapshot.current_id}\n"
        f"message: {snapshot.message}\n"
        f"updated_at: {snapshot.updated_at}\n"
    )


def write_json_atomic(path: Path, payload: JsonValue) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def try_write_json_atomic(path: Path, payload: JsonValue) -> None:
    try:
        write_json_atomic(path, payload)
    except OSError:
        return


def try_write_text_atomic(path: Path, text: str) -> None:
    try:
        write_text_atomic(path, text)
    except OSError:
        return
