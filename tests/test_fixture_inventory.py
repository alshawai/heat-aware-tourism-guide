"""Committed fixture inventory gates: sidecars exist and no secrets are committed (ADR 0004)."""

import hashlib
import json
from pathlib import Path
import re
from typing import Iterator

import pytest

from app.domain.provenance import AcquisitionRecord, UpstreamAcquisitionReference

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPOSITORY_ROOT = FIXTURES.parent
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


def _validate_derived_references(repository_root: Path, record: AcquisitionRecord) -> None:
    for reference in record.derived_from:
        fixture_path = repository_root / reference.fixture
        assert fixture_path.is_file(), f"missing derived fixture {reference.fixture}"
        assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == reference.sha256, (
            f"digest mismatch for derived fixture {reference.fixture}"
        )


def test_every_committed_fixture_has_an_acquisition_sidecar() -> None:
    fixtures = [
        path for path in _committed_json_files() if not path.name.endswith(".acquisition.json")
    ]
    assert len(fixtures) >= 11
    for path in fixtures:
        sidecar = path.with_name(f"{path.stem}.acquisition.json")
        assert sidecar.is_file(), f"{path.name} is missing its acquisition sidecar"


def test_every_sidecar_parses_into_a_valid_acquisition_record() -> None:
    for path, record in _records():
        assert record.source in {"provider", "synthesized"}, path.name
        assert record.provider.strip(), path.name
        assert record.endpoint, path.name
        assert record.schema_version, path.name


def test_synthesized_records_never_fabricate_activity_ids_or_retrieval_times() -> None:
    for path, record in _records():
        if record.source == "synthesized":
            assert record.activity_id is None, path.name
            assert record.retrieved_at is None, path.name


def test_provider_records_have_retrieval_and_configuration_metadata() -> None:
    for path, record in _records():
        if record.source == "provider":
            assert record.retrieved_at is not None, path.name
            assert (record.provider_config_version or "").strip(), path.name


def test_derived_acquisition_references_match_exact_fixture_bytes() -> None:
    for _, record in _records():
        _validate_derived_references(REPOSITORY_ROOT, record)


def test_derived_acquisition_reference_validation_checks_exact_bytes(tmp_path: Path) -> None:
    fixture = tmp_path / "fixtures" / "source.json"
    fixture.parent.mkdir()
    fixture.write_bytes(b'{"value": 1}\n')
    reference = UpstreamAcquisitionReference(
        "fixtures/source.json", "heat", hashlib.sha256(fixture.read_bytes()).hexdigest()
    )
    record = AcquisitionRecord(
        source="synthesized",
        provider="heat-aware-tourism-guide",
        endpoint="local:product",
        request_configuration={},
        retrieved_at=None,
        data_date="2026-08-23",
        status="ok",
        schema_version="v1",
        provider_config_version=None,
        activity_id=None,
        derived_from=(reference,),
    )
    _validate_derived_references(tmp_path, record)
    fixture.write_bytes(b'{"value": 2}\n')
    with pytest.raises(AssertionError, match="digest mismatch"):
        _validate_derived_references(tmp_path, record)


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
