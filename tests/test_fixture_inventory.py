"""Committed fixture inventory gates: sidecars exist and no secrets are committed (ADR 0004)."""

import json
from pathlib import Path
import re
from typing import Iterator

from app.domain.provenance import AcquisitionRecord

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SECRET_KEY_PATTERN = re.compile(r"(?i)(api[_ -]?key|authorization|token|bearer|secret)")
SECRET_VALUE_PATTERN = re.compile(r"^(?:fg|sk)_[A-Za-z0-9]{20,}$")


def _committed_json_files() -> list[Path]:
    return sorted(FIXTURES.rglob("*.json"))


def _sidecars() -> list[Path]:
    return [path for path in _committed_json_files() if path.name.endswith(".acquisition.json")]


def _records() -> Iterator[tuple[Path, AcquisitionRecord]]:
    for path in _sidecars():
        payload = json.loads(path.read_text(encoding="utf-8"))
        yield path, AcquisitionRecord.from_payload(payload)


def test_every_committed_fixture_has_an_acquisition_sidecar() -> None:
    fixtures = [path for path in _committed_json_files() if not path.name.endswith(".acquisition.json")]
    assert len(fixtures) >= 11
    for path in fixtures:
        sidecar = path.with_name(f"{path.stem}.acquisition.json")
        assert sidecar.is_file(), f"{path.name} is missing its acquisition sidecar"


def test_every_sidecar_parses_into_a_valid_acquisition_record() -> None:
    for path, record in _records():
        assert record.source in {"provider", "synthesized"}, path.name
        assert record.endpoint, path.name
        assert record.schema_version, path.name


def test_synthesized_records_never_fabricate_activity_ids_or_retrieval_times() -> None:
    for path, record in _records():
        if record.source == "synthesized":
            assert record.activity_id is None, path.name
            assert record.retrieved_at is None, path.name


def test_committed_fixture_json_contains_no_secrets() -> None:
    def walk(value: object) -> Iterator[str]:
        if isinstance(value, dict):
            for key, item in value.items():
                assert not SECRET_KEY_PATTERN.search(str(key)), (
                    f"secret-shaped key {key!r} in {path.name}"
                )
                yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, str):
            yield value

    for path in _committed_json_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        for text in walk(data):
            assert not SECRET_VALUE_PATTERN.match(text), f"key-shaped value in {path.name}"
            assert "Bearer " not in text, f"bearer token in {path.name}"
            assert not text.startswith("eyJ"), f"JWT-shaped value in {path.name}"
