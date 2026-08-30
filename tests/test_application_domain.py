from datetime import datetime, timezone
from typing import Any

import pytest

from app.domain.analysis import extract_exposure, point_join_contract, polygon_join_contract
from app.domain.provenance import (
    AcquisitionRecord,
    CacheKey,
    Provenance,
    UpstreamAcquisitionReference,
)
from app.domain.readiness import (
    EnrichmentOutcome,
    EnrichmentPlanner,
    EnrichmentRequest,
    ReadinessInput,
    readiness,
)
from app.services.cache import CacheService


def test_cache_key_separates_endpoint_and_schema_for_same_payload() -> None:
    payload = {"latitude": 29.4241, "longitude": -98.4936}
    assert CacheKey.create("heatmap", "v1", payload, "fortyguard-config-v1") != CacheKey.create(
        "status", "v1", payload, "fortyguard-config-v1"
    )
    assert CacheKey.create("heatmap", "v1", payload, "fortyguard-config-v1") == CacheKey.create(
        "heatmap", "v1", dict(reversed(list(payload.items()))), "fortyguard-config-v1"
    )


def test_cache_key_separates_provider_configuration_versions() -> None:
    payload = {"latitude": 29.4241, "longitude": -98.4936}
    assert CacheKey.create("heatmap", "v1", payload, "fortyguard-config-v1") != CacheKey.create(
        "heatmap", "v1", payload, "fortyguard-config-v2"
    )


def test_acquisition_record_round_trips_through_payload() -> None:
    record = AcquisitionRecord(
        source="provider",
        provider="fortyguard",
        endpoint="/v1/heatmap",
        request_configuration={"analytic_type": "tcm", "latitude": 29.4241},
        retrieved_at=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        data_date="2026-08-23",
        status="ok",
        schema_version="v1",
        provider_config_version="fortyguard-config-v1",
        activity_id="activity-1",
        derived_from=(
            UpstreamAcquisitionReference("fixtures/acquired/input.json", "heat", "a" * 64),
        ),
    )
    payload = record.to_payload()
    assert AcquisitionRecord.from_payload(payload) == record


def test_acquisition_record_rejects_unknown_source_and_missing_identity() -> None:
    base: dict[str, Any] = {
        "source": "synthesized",
        "provider": "heat-aware-tourism-guide",
        "endpoint": "/v1/heatmap",
        "request_configuration": {"analytic_type": "tcm"},
        "retrieved_at": None,
        "data_date": "2026-08-23",
        "status": "ok",
        "schema_version": "v1",
        "provider_config_version": None,
        "activity_id": None,
        "derived_from": [],
        "transformations": [],
    }
    with pytest.raises(ValueError, match="source"):
        AcquisitionRecord.from_payload({**base, "source": "guessed"})
    with pytest.raises(ValueError, match="endpoint"):
        AcquisitionRecord.from_payload({**base, "endpoint": ""})
    with pytest.raises(ValueError, match="provider"):
        AcquisitionRecord.from_payload({**base, "provider": " "})


def test_synthesized_acquisition_record_has_no_fabricated_activity_or_time() -> None:
    record = AcquisitionRecord(
        source="synthesized",
        provider="heat-aware-tourism-guide",
        endpoint="/v1/heatmap",
        request_configuration={"analytic_type": "tcm"},
        retrieved_at=None,
        data_date="2026-08-20",
        status="ok",
        schema_version="v1",
        provider_config_version=None,
        activity_id=None,
        derived_from=(),
    )
    assert record.activity_id is None
    assert record.retrieved_at is None
    assert record.to_payload()["activity_id"] is None


def test_acquisition_record_enforces_source_specific_metadata() -> None:
    values: dict[str, Any] = {
        "source": "provider",
        "provider": "fortyguard",
        "endpoint": "/v1/heatmap",
        "request_configuration": {},
        "retrieved_at": datetime(2026, 8, 23, tzinfo=timezone.utc),
        "data_date": "2026-08-23",
        "status": "ok",
        "schema_version": "v1",
        "provider_config_version": "fortyguard-config-v1",
        "activity_id": None,
        "derived_from": (),
    }
    with pytest.raises(ValueError, match="retrieval time"):
        AcquisitionRecord(**{**values, "retrieved_at": None})
    with pytest.raises(ValueError, match="configuration version"):
        AcquisitionRecord(**{**values, "provider_config_version": " "})
    with pytest.raises(ValueError, match="synthesized"):
        AcquisitionRecord(
            **{
                **values,
                "source": "synthesized",
                "provider": "heat-aware-tourism-guide",
                "provider_config_version": None,
            }
        )


def test_upstream_acquisition_reference_rejects_malformed_values() -> None:
    invalid_values = [
        ({"fixture": "/fixtures/input.json"}, "repository-relative"),
        ({"fixture": "fixtures/../input.json"}, "traversal"),
        ({"role": " "}, "role"),
        ({"sha256": "A" * 64}, "lowercase"),
        ({"sha256": "a" * 63}, "lowercase"),
    ]
    values = {"fixture": "fixtures/input.json", "role": "heat", "sha256": "a" * 64}
    for overrides, message in invalid_values:
        with pytest.raises(ValueError, match=message):
            UpstreamAcquisitionReference(**{**values, **overrides})


def test_upstream_acquisition_reference_parser_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="invalid fields"):
        UpstreamAcquisitionReference.from_payload(
            {
                "fixture": "fixtures/input.json",
                "role": "heat",
                "sha256": "a" * 64,
                "sidecar": "unexpected",
            }
        )


def test_stale_cache_provenance_is_explicit() -> None:
    provenance = Provenance.cached(
        retrieved_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        data_date="2026-08-20",
        activity_id="activity-1",
    )
    assert provenance.source == "cache"
    assert provenance.stale is True
    assert provenance.activity_id == "activity-1"


def test_cache_hit_is_marked_as_replayed_and_cache_miss_is_none() -> None:
    service = CacheService()
    key = service.put(
        "heatmap",
        "v1",
        {"metric": "tcm"},
        {"value": 35},
        retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        data_date="2026-08-23",
        activity_id="a1",
        provider_config_version="fortyguard-config-v1",
    )
    hit = service.get(key)
    assert hit is not None
    assert hit.provenance.source == "cache"
    assert hit.provenance.stale is True
    assert hit.provenance.raw_payload == {"value": 35}
    assert (
        service.get(CacheKey.create("heatmap", "v1", {"metric": "other"}, "fortyguard-config-v1"))
        is None
    )


def test_cache_hit_requires_matching_provider_configuration_version() -> None:
    service = CacheService()
    key = service.put(
        "heatmap",
        "v1",
        {"metric": "tcm"},
        {"value": 35},
        retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        data_date="2026-08-23",
        provider_config_version="fortyguard-config-v1",
    )
    assert service.get(key) is not None
    assert (
        service.get(CacheKey.create("heatmap", "v1", {"metric": "tcm"}, "fortyguard-config-v2"))
        is None
    )


def test_cache_preserves_forecast_and_data_date_metadata() -> None:
    service = CacheService()
    key = service.put(
        "heatmap",
        "v1",
        {"metric": "tcm"},
        {"value": 35},
        retrieved_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
        data_date="2026-08-23",
        forecast=True,
        provider_config_version="fortyguard-config-v1",
    )
    entry = service.get(key)
    assert entry is not None
    assert entry.provenance.forecast is True
    assert entry.provenance.data_date == "2026-08-23"


def test_enrichment_is_top_n_and_budgeted_without_blocking_core_flow() -> None:
    plan = EnrichmentPlanner(credits=3).plan(
        ["hotel-a", "hotel-b", "hotel-c", "hotel-d"],
        EnrichmentRequest(top_n=2, credits_per_item=2),
    )
    assert plan.selected == ("hotel-a",)
    assert plan.remaining_credits == 1
    assert plan.base_result_preserved is True


def test_enrichment_execution_preserves_ranked_output_after_partial_failure() -> None:
    planner = EnrichmentPlanner(credits=4)

    def enrich(candidate: str) -> dict[str, str]:
        if candidate == "hotel-b":
            raise RuntimeError("optional provider failed")
        return {"candidate": candidate}

    result = planner.execute(
        ["hotel-a", "hotel-b", "hotel-c"],
        EnrichmentRequest(top_n=2, credits_per_item=2),
        enrich,
    )
    assert result.base_ranking == ("hotel-a", "hotel-b", "hotel-c")
    assert result.enriched == {"hotel-a": {"candidate": "hotel-a"}}
    assert result.failures == {"hotel-b": "optional provider failed"}
    assert result.remaining_credits == 0
    assert planner.credits == 0


def test_enrichment_execution_records_actual_provider_usage() -> None:
    from app.domain.ledger import CreditLedger

    ledger = CreditLedger(5)
    result = EnrichmentPlanner(5).execute(
        ["hotel-a"],
        EnrichmentRequest(top_n=1, credits_per_item=2),
        lambda _: EnrichmentOutcome({"canopy": 42}, "activity-1", 2, "/v1/satellite"),
        ledger=ledger,
    )
    assert result.enriched["hotel-a"] == {"canopy": 42}
    assert ledger.reported_credits == 2
    assert ledger.records[0].activity_id == "activity-1"


def test_historical_exposure_is_explicit_supporting_context() -> None:
    summary = extract_exposure(
        {
            "value": 6,
            "unit": "hours",
            "valid_from": "2026-08-20T00:00:00+00:00",
            "valid_to": "2026-08-20T23:00:00+00:00",
            "fresh_at": "2026-08-21T00:00:00+00:00",
        },
        metric="exceedance",
        threshold_celsius=35,
        direction="above",
        source="fortyguard",
        forecast=False,
    )
    assert summary.role == "supporting_context"
    assert summary.forecast is False
    assert summary.threshold_celsius == 35
    assert summary.fresh_at == "2026-08-21T00:00:00+00:00"


def test_exposure_rejects_forecast_and_missing_freshness() -> None:
    payload = {"value": 6, "unit": "C", "valid_from": "start", "valid_to": "end"}
    with pytest.raises(ValueError, match="freshness"):
        extract_exposure(
            payload,
            metric="exceedance",
            threshold_celsius=35,
            direction="above",
            source="fortyguard",
            forecast=False,
        )
    with pytest.raises(ValueError, match="historical"):
        extract_exposure(
            {**payload, "fresh_at": "fresh"},
            metric="persistence",
            threshold_celsius=35,
            direction="above",
            source="fortyguard",
            forecast=True,
        )


def test_exposure_rejects_boolean_and_non_finite_values() -> None:
    base = {"unit": "hours", "valid_from": "start", "valid_to": "end", "fresh_at": "fresh"}
    with pytest.raises(ValueError, match="value"):
        extract_exposure(
            {**base, "value": True},
            metric="exceedance",
            threshold_celsius=35,
            direction="above",
            source="fortyguard",
            forecast=False,
        )
    with pytest.raises(ValueError, match="value"):
        extract_exposure(
            {**base, "value": float("nan")},
            metric="persistence",
            threshold_celsius=35,
            direction="above",
            source="fortyguard",
            forecast=False,
        )


def test_readiness_returns_deterministic_reason_codes() -> None:
    result = readiness(
        ReadinessInput(heat_celsius=38, threshold_celsius=35, coverage=0.9, forecast=True)
    )
    assert result.priority == "high"
    assert result.reason_codes == ("HEAT_THRESHOLD_EXCEEDED",)


def test_spatial_contract_reports_partial_polygon_coverage_and_point_fallback() -> None:
    polygon = polygon_join_contract([(30, 2), (40, 1)], coverage=0.75, projected_crs="EPSG:32614")
    assert polygon.value == 100 / 3
    assert polygon.quality == "partial"
    point = point_join_contract(
        containing_value=None,
        boundary=False,
        outside_aoi=True,
        nearest_value=35,
        nearest_distance_m=12,
    )
    assert point.quality == "nearest_fallback"
    assert point.distance_m == 12


def test_provenance_transformations_default_to_empty_and_serialize_structured() -> None:
    from dataclasses import asdict

    from app.domain.provenance import Provenance, Transformation

    plain = Provenance(
        "fixture", datetime(2026, 8, 27, tzinfo=timezone.utc), "2026-08-27", False, True
    )
    assert plain.transformations == ()

    stamped = Provenance(
        "provider",
        datetime(2026, 8, 27, tzinfo=timezone.utc),
        "2026-08-27",
        False,
        True,
        "activity-1",
        None,
        (Transformation("tcm_unit_celsius", 1), Transformation("valid_time_from_request", 1)),
    )
    assert asdict(stamped)["transformations"] == (
        {"name": "tcm_unit_celsius", "version": 1},
        {"name": "valid_time_from_request", "version": 1},
    )


def test_transformation_rejects_blank_names_and_non_positive_versions() -> None:
    from app.domain.provenance import Transformation

    with pytest.raises(ValueError, match="name"):
        Transformation("", 1)
    with pytest.raises(ValueError, match="version"):
        Transformation("tcm_unit_celsius", 0)
