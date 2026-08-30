"""Acquisition sidecar layout shared by execution, trip adapters, and acquisition.

The sidecar convention (`<stem>.acquisition.json` beside every committed
fixture) is the single authoritative fixture match identity (ADR 0004); this
module is the only place that knows the file layout.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

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


def replace_pair(
    fixture_path: Path,
    fixture_bytes: bytes,
    record: AcquisitionRecord,
    *,
    fail_after_fixture: bool = False,
) -> None:
    """Replace a fixture and its sidecar with rollback-safe pair semantics."""
    sidecar = sidecar_path(fixture_path)
    sidecar_bytes = (json.dumps(record.to_payload(), indent=2, sort_keys=True) + "\n").encode()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    originals = {
        path: path.read_bytes() if path.exists() else None for path in (fixture_path, sidecar)
    }
    temporary: list[Path] = []
    try:
        for path, data in ((fixture_path, fixture_bytes), (sidecar, sidecar_bytes)):
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as temp:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
                temporary.append(Path(temp.name))
        os.replace(temporary[0], fixture_path)
        if fail_after_fixture:
            raise OSError("injected second-write failure")
        os.replace(temporary[1], sidecar)
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
