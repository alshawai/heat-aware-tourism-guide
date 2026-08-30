import hashlib
import json
from pathlib import Path

import pytest

from app.domain.contracts import (
    EnrichmentState,
    ExecutionMode,
    ResultState,
    RouteDecisionState,
    RouteSetState,
    TemporalEvidenceState,
)
from app.services.sidecars import load_acquisition_record
from app.services.trip_adapters import _request_from_fixture_identity
from app.services.trip_contract_v2 import decode_trip_analysis_v2, encode_trip_analysis_v2
from app.services.trip_snapshot_generation import INPUTS, generate_issue23_snapshots


def _load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_generator_is_byte_deterministic_in_two_temp_directories(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    first_paths = generate_issue23_snapshots(first / "trips")
    second_paths = generate_issue23_snapshots(second / "trips")

    for left, right in zip(first_paths, second_paths, strict=True):
        assert left.read_bytes() == right.read_bytes()
        assert (
            left.with_name(f"{left.stem}.acquisition.json").read_bytes()
            == right.with_name(f"{right.stem}.acquisition.json").read_bytes()
        )


def test_generator_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "trips"
    generate_issue23_snapshots(output)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_issue23_snapshots(output)


def test_generator_rejects_changed_input_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = INPUTS["menger_osrm"]
    monkeypatch.setitem(
        INPUTS, "menger_osrm", type(original)(original.fixture, original.role, "0" * 64)
    )
    with pytest.raises(ValueError, match="input hash mismatch"):
        generate_issue23_snapshots(tmp_path / "trips")


def test_committed_snapshots_decode_and_encode_exactly() -> None:
    for path in sorted(Path("fixtures/trips").glob("*.trip.json")):
        record = load_acquisition_record(path)
        assert record is not None
        request = _request_from_fixture_identity(record.request_configuration)
        payload = _load(path)
        response = decode_trip_analysis_v2(payload, request, ExecutionMode.FIXTURE)
        assert encode_trip_analysis_v2(response) == payload


def test_required_snapshot_states_and_evidence_labels() -> None:
    snapshots = {path.name: _load(path) for path in Path("fixtures/trips").glob("*.trip.json")}
    canonical = snapshots["menger-alamo.trip.json"]
    assert canonical["state"] == ResultState.DEGRADED.value
    assert canonical["best_time"]["temporal_evidence"] == TemporalEvidenceState.INCONSISTENT.value  # type: ignore[index]
    assert canonical["best_time"]["recommendation_time"] is None  # type: ignore[index]
    assert len(canonical["routes"]["alternatives"]) == 1  # type: ignore[index]
    assert canonical["routes"]["route_set_state"] == RouteSetState.SINGLE_ROUTE.value  # type: ignore[index]
    assert canonical["hotels"]["usable_count"] >= 5  # type: ignore[index]

    main = snapshots["main-plaza-market-square.trip.json"]
    assert main["routes"]["route_set_state"] == RouteSetState.SINGLE_ROUTE.value  # type: ignore[index]
    assert "synthesized-demo" in main["best_time"]["provenance"]["provider"]  # type: ignore[index]

    cathedral = snapshots["cathedral-governors-palace.trip.json"]
    assert cathedral["routes"]["route_set_state"] == RouteSetState.ALTERNATIVES_RETURNED.value  # type: ignore[index]
    assert (
        cathedral["routes"]["decision_state"]
        == RouteDecisionState.INSUFFICIENT_SHADE_COMPARISON_REQUIRED.value
    )  # type: ignore[index]
    assert cathedral["routes"]["recommended_id"] is None  # type: ignore[index]
    assert cathedral["hotels"]["enrichment"]["state"] == EnrichmentState.UNAVAILABLE.value  # type: ignore[index]

    unavailable = snapshots["briscoe-tower-unavailable.trip.json"]
    assert unavailable["state"] == ResultState.UNAVAILABLE.value
    assert unavailable["unavailable"]["code"] == "provider_data_missing"  # type: ignore[index]
    assert unavailable["best_time"] is unavailable["hotels"] is unavailable["routes"] is None


def test_product_sidecar_references_every_used_raw_input() -> None:
    for path in Path("fixtures/trips").glob("*.trip.json"):
        record = load_acquisition_record(path)
        assert record is not None
        for reference in record.derived_from:
            source = Path(reference.fixture)
            assert hashlib.sha256(source.read_bytes()).hexdigest() == reference.sha256
        if path.name == "briscoe-tower-unavailable.trip.json":
            assert record.derived_from == ()
