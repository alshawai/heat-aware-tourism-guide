"""Acquisition sidecar layout shared by execution, trip adapters, and acquisition.

The sidecar convention (`<stem>.acquisition.json` beside every committed
fixture) is the single authoritative fixture match identity (ADR 0004); this
module is the only place that knows the file layout.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.provenance import AcquisitionRecord

SIDECAR_SUFFIX = ".acquisition.json"


def sidecar_path(fixture_path: Path) -> Path:
    return fixture_path.with_name(f"{fixture_path.stem}{SIDECAR_SUFFIX}")


def load_acquisition_record(fixture_path: Path) -> AcquisitionRecord | None:
    """Load the sidecar record, or None when the fixture has no sidecar."""
    path = sidecar_path(fixture_path)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"acquisition sidecar {path} must contain a JSON object")
    return AcquisitionRecord.from_payload(payload)


def write_sidecar(fixture_path: Path, record: AcquisitionRecord) -> None:
    sidecar_path(fixture_path).write_text(
        json.dumps(record.to_payload(), indent=2) + "\n", encoding="utf-8"
    )
