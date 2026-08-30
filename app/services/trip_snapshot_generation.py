"""Deterministic, offline product snapshot generation for Issue 23."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, cast
from zoneinfo import ZoneInfo

from shapely.geometry import MultiLineString

from app.domain.contracts import (
    BestTimeResult,
    Confidence,
    Coordinates,
    EnrichmentState,
    ExecutionMode,
    HeatMetricName,
    HotelComponentTemporalMetadata,
    HotelRankingResult,
    HourlyEntry,
    Metric,
    MetricLabel,
    OptionalEnrichment,
    Provenance,
    RankedHotel,
    ResultState,
    RouteComparisonResult,
    TemporalEvidenceState,
    TripAnalysisRequest,
    TripAnalysisResponse,
    TripMode,
    UnavailableResult,
)
from app.domain.heat_policy import classify_heat
from app.domain.provenance import AcquisitionRecord, Transformation, UpstreamAcquisitionReference
from app.domain.route_decision import RouteDecisionInput, decide_route_comparison
from app.domain.route_shade import solar_position
from app.domain.routing import RouteRequest, RouteSet
from app.domain.trip import HotelCandidate, HotelRanker
from app.integrations.fortyguard.contracts import (
    AnalyticType,
    EnvParamsRequest,
    HeatmapRequest,
    normalize_env_params_response,
    normalize_heatmap_response,
)
from app.integrations.fortyguard.live import translate_heatmap_response
from app.integrations.osrm.client import normalize_response
from app.services.building_execution import BuildingOutcome
from app.services.route_analysis import _building_provenance, _solar_provenance
from app.services.route_shade import RouteShadeService
from app.services.routing import route_request_payload
from app.services.sidecars import load_acquisition_record, sidecar_path
from app.services.trip_adapters import _best_time_result, _environment_result
from app.services.trip_contract_v2 import decode_trip_analysis_v2, encode_trip_analysis_v2

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXED_GENERATED_AT = datetime.fromisoformat("2026-08-30T16:00:00+00:00")
SNAPSHOT_TRANSFORMATION = Transformation("trip-product-snapshot", 1)
DISTRICT = "Downtown San Antonio"
HOTEL_FIXTURE = "fixtures/hotel-heat-analysis.json"


@dataclass(frozen=True)
class InputSpec:
    fixture: str
    role: str
    sha256: str


INPUTS = {
    "menger_osrm": InputSpec(
        "fixtures/providers/osrm/menger-alamo.json",
        "routing",
        "7f5408f0b2520887b2b6ddfc01b00971e7617830e22c5794cf594a160c41a3d0",
    ),
    "main_osrm": InputSpec(
        "fixtures/providers/osrm/main-plaza-market-square.json",
        "routing",
        "bfad4e015c360213d95ea4a5b72950d61e5e825421a2335543f9075b6aee08f4",
    ),
    "cathedral_osrm": InputSpec(
        "fixtures/providers/osrm/cathedral-governors-palace.json",
        "routing",
        "aba78baeb0bb390741e0641a5828c377ca347d9deb2511360a85c9019f54a87f",
    ),
    "buildings": InputSpec(
        "fixtures/providers/overpass/cathedral-governors-palace-buildings.json",
        "building_geometry",
        "e6176d2f673389a59e7d55624734a54b768a8f56f8baafe6fcbe31adb90b5d60",
    ),
    "destination_tcm": InputSpec(
        "fixtures/providers/fortyguard/menger-alamo-destination-tcm-2024-07-15.json",
        "destination_tcm",
        "98293540939b8dd1ca4c268c0e2fc9afc124b61494e20cc38564f5a06fb50c61",
    ),
    "environment": InputSpec(
        "fixtures/providers/fortyguard/menger-alamo-destination-env-params-2024-07-15.json",
        "environment_parameters",
        "3c7e85101cbf6961eeed391443cecb4c97bc6c9beda36fc0cfdf730cd5ea9df4",
    ),
    "district_tcm": InputSpec(
        "fixtures/providers/fortyguard/canonical-district-anchor-date-tcm-2024-07-15.json",
        "hotel_night_and_day_tcm",
        "f440eeb83743303e8a99126d0e53f02ff1625f1875aa9c60b5092f96ed0257ca",
    ),
    "district_exceedance": InputSpec(
        "fixtures/providers/fortyguard/canonical-district-anchor-exceedance-above-35c-2024-07-15.json",
        "hotel_hot_hours",
        "4226735c20081617206c77672cd1b142f643c9fcfe0da5d8be455a0c5fca54b7",
    ),
    "district_persistence": InputSpec(
        "fixtures/providers/fortyguard/canonical-district-anchor-persistence-above-35c-2024-07-15.json",
        "hotel_persistence",
        "8b9cb5fc1cd31151dac10fdf854a890468b714061f3f98c2902db496da4b50d4",
    ),
    "hotels": InputSpec(
        HOTEL_FIXTURE,
        "base_hotel_discovery",
        "fde152a6c473fb6a38a6fe2928ccf4718a17d621e61f7d7c8da3d84d5a69e84b",
    ),
}


def _place(
    application_id: str,
    name: str,
    latitude: float,
    longitude: float,
    osm_identity: str,
    coordinate_meaning: str,
) -> dict[str, object]:
    return {
        "application_id": application_id,
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "osm_identity": osm_identity,
        "coordinate_meaning": coordinate_meaning,
        "authority": "OpenStreetMap/Nominatim selected object",
    }


SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "filename": "menger-alamo.trip.json",
        "mode": TripMode.CURATED,
        "origin": _place(
            "menger-hotel",
            "Menger Hotel",
            29.4245914,
            -98.4864288,
            "way/23727574",
            "Nominatim centroid",
        ),
        "destination": _place(
            "the-alamo",
            "The Alamo",
            29.425833,
            -98.485833,
            "way/129152944",
            "component central point",
        ),
        "landmark_name": "The Alamo",
        "start_hour": 8,
        "end_hour": 20,
        "inputs": (
            "menger_osrm",
            "destination_tcm",
            "environment",
            "district_tcm",
            "district_exceedance",
            "district_persistence",
            "hotels",
        ),
    },
    {
        "filename": "main-plaza-market-square.trip.json",
        "mode": TripMode.EXPLORATORY,
        "origin": _place(
            "main-plaza",
            "Main Plaza",
            29.4245773,
            -98.4935063,
            "way/93118472",
            "Nominatim centroid of park polygon",
        ),
        "destination": _place(
            "historic-market-square-el-mercado",
            "Historic Market Square (El Mercado)",
            29.4254009,
            -98.4994785,
            "way/79636475",
            "Nominatim centroid of building footprint",
        ),
        "landmark_name": "Historic Market Square (El Mercado)",
        "start_hour": 10,
        "end_hour": 17,
        "inputs": ("main_osrm",),
    },
    {
        "filename": "cathedral-governors-palace.trip.json",
        "mode": TripMode.EXPLORATORY,
        "origin": _place(
            "san-fernando-cathedral",
            "San Fernando Cathedral",
            29.424559,
            -98.4942042,
            "way/80647022",
            "Nominatim centroid of cathedral footprint",
        ),
        "destination": _place(
            "spanish-governors-palace",
            "Spanish Governor's Palace",
            29.4248225,
            -98.4959872,
            "way/78601534",
            "Nominatim centroid of museum footprint",
        ),
        "landmark_name": "Spanish Governor's Palace",
        "start_hour": 10,
        "end_hour": 17,
        "inputs": (
            "cathedral_osrm",
            "buildings",
            "district_tcm",
            "district_exceedance",
            "district_persistence",
            "hotels",
        ),
    },
    {
        "filename": "briscoe-tower-unavailable.trip.json",
        "mode": TripMode.EXPLORATORY,
        "origin": _place(
            "briscoe-western-art-museum",
            "Briscoe Western Art Museum",
            29.4228983,
            -98.4888465,
            "way/337650172",
            "Nominatim centroid of museum footprint",
        ),
        "destination": _place(
            "tower-of-the-americas",
            "Tower of the Americas",
            29.4190825,
            -98.4835734,
            "way/78485919",
            "Nominatim centroid of tower footprint",
        ),
        "landmark_name": "Tower of the Americas",
        "start_hour": 10,
        "end_hour": 17,
        "inputs": (),
    },
)


def generate_issue23_snapshots(
    output_dir: Path = REPOSITORY_ROOT / "fixtures" / "trips", *, overwrite: bool = False
) -> tuple[Path, ...]:
    """Generate all four snapshots without network access or implicit overwrite."""
    if not output_dir.parent.is_dir():
        raise ValueError(f"snapshot output parent does not exist: {output_dir.parent}")
    targets = tuple(output_dir / str(item["filename"]) for item in SCENARIOS)
    for target in targets:
        if not overwrite and (target.exists() or sidecar_path(target).exists()):
            raise FileExistsError(f"refusing to overwrite snapshot pair: {target}")
    validated = {name: _validate_input(spec) for name, spec in INPUTS.items()}
    output_dir.mkdir(exist_ok=True)
    for scenario, target in zip(SCENARIOS, targets, strict=True):
        request = _request(scenario)
        response = _build_response(str(scenario["filename"]), request, validated)
        payload = encode_trip_analysis_v2(response)
        decoded = decode_trip_analysis_v2(payload, request, ExecutionMode.FIXTURE)
        if encode_trip_analysis_v2(decoded) != payload:
            raise ValueError(f"snapshot codec was not stable for {target.name}")
        _write_json(target, payload)
        references = tuple(
            UpstreamAcquisitionReference(
                INPUTS[name].fixture, INPUTS[name].role, INPUTS[name].sha256
            )
            for name in cast(tuple[str, ...], scenario["inputs"])
        )
        record = AcquisitionRecord(
            source="synthesized",
            provider="heat-aware-tourism-guide",
            endpoint="local:trip-product-snapshot",
            request_configuration=_request_configuration(scenario),
            retrieved_at=None,
            data_date=request.date,
            status="unavailable" if response.state is ResultState.UNAVAILABLE else "ok",
            schema_version="trip-contract-v2",
            provider_config_version="trip-product-config-v1",
            activity_id=None,
            derived_from=references,
            transformations=(SNAPSHOT_TRANSFORMATION,),
        )
        _write_json(sidecar_path(target), record.to_payload())
    return targets


def _validate_input(spec: InputSpec) -> tuple[Mapping[str, object], AcquisitionRecord]:
    path = REPOSITORY_ROOT / spec.fixture
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != spec.sha256:
        raise ValueError(
            f"input hash mismatch for {spec.fixture}: expected {spec.sha256}, got {digest}"
        )
    record = load_acquisition_record(path)
    if record is None or (
        not record.replayable
        and not (spec.fixture == HOTEL_FIXTURE and record.status == "complete")
    ):
        raise ValueError(f"input fixture is not replayable: {spec.fixture}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"input fixture must contain an object: {spec.fixture}")
    return payload, record


def _request(scenario: Mapping[str, object]) -> TripAnalysisRequest:
    origin = scenario["origin"]
    destination = scenario["destination"]
    assert isinstance(origin, Mapping) and isinstance(destination, Mapping)
    return TripAnalysisRequest(
        mode=scenario["mode"],  # type: ignore[arg-type]
        origin=Coordinates(float(origin["latitude"]), float(origin["longitude"])),
        destination=Coordinates(float(destination["latitude"]), float(destination["longitude"])),
        landmark_name=str(scenario["landmark_name"]),
        district_name=DISTRICT,
        date="2024-07-15",
        start_hour=cast(int, scenario["start_hour"]),
        end_hour=cast(int, scenario["end_hour"]),
        cautious=False,
    )


def _request_configuration(scenario: Mapping[str, object]) -> dict[str, object]:
    return {
        "mode": cast(TripMode, scenario["mode"]).value,
        "landmark_name": scenario["landmark_name"],
        "district_name": DISTRICT,
        "date": "2024-07-15",
        "start_hour": scenario["start_hour"],
        "end_hour": scenario["end_hour"],
        "cautious": False,
        "origin": scenario["origin"],
        "destination": scenario["destination"],
        "generator_version": "trip-product-snapshot-v1",
        "generator_metadata": _generator_metadata(str(scenario["filename"])),
        "hotel_aoi": {"south": 29.421, "west": -98.49, "north": 29.429, "east": -98.482},
        "building_aoi": (
            {
                "south": 29.422431929,
                "west": -98.498865419,
                "north": 29.427384596,
                "east": -98.491604468,
            }
            if scenario["filename"] == "cathedral-governors-palace.trip.json"
            else None
        ),
        "route_heat_aoi": None,
    }


def _build_response(
    filename: str,
    request: TripAnalysisRequest,
    inputs: Mapping[str, tuple[Mapping[str, object], AcquisitionRecord]],
) -> TripAnalysisResponse:
    if filename == "briscoe-tower-unavailable.trip.json":
        return TripAnalysisResponse(
            f"{request.mode.value}:{request.date}:{request.start_hour}-{request.end_hour}",
            request.mode,
            ExecutionMode.FIXTURE,
            ResultState.UNAVAILABLE,
            unavailable=UnavailableResult(
                "The initial TCM analysis failed and no exact cache or fixture fallback was available.",
                True,
                "provider_data_missing",
                "retry_or_edit_setup",
            ),
        )
    if filename == "menger-alamo.trip.json":
        best = _canonical_best_time(request, inputs)
        hotels = _provider_hotels(inputs)
        routes = _route_result(request, inputs["menger_osrm"], best, heat_provider="fortyguard")
        return TripAnalysisResponse(
            "curated:2024-07-15:8-20",
            request.mode,
            ExecutionMode.FIXTURE,
            ResultState.DEGRADED,
            best_time=best,
            hotels=hotels,
            routes=routes,
            degraded_reasons={
                "best_time": "provider timezone GMT-7 conflicts with America/Chicago; recommendation is hour-only",
                "routes": "only one pedestrian route was returned; comparison is limited",
            },
        )
    best = _synthetic_best_time(request, elevated=filename.startswith("cathedral"))
    hotels = _synthetic_hotels(inputs, enrichment_failure=filename.startswith("cathedral"))
    if filename == "main-plaza-market-square.trip.json":
        routes = _route_result(
            request, inputs["main_osrm"], best, heat_provider="heat-aware-tourism-guide-demo-heat"
        )
        reasons = {
            "best_time": "demo TCM and environmental evidence is synthesized, not provider-observed",
            "hotels": "demo hotel evidence is synthesized, not provider-observed",
            "routes": "one returned route limits comparison; route heat reuses synthesized destination demo TCM",
        }
    else:
        routes = _cathedral_routes(request, inputs, best)
        reasons = {
            "best_time": "elevated demo TCM is synthesized solely to exercise ADR 0007",
            "hotels": "optional hotel enrichment was unavailable; base ranking remains",
            "routes": "building-height evidence is insufficient for a route recommendation",
        }
    return TripAnalysisResponse(
        "exploratory:2024-07-15:10-17",
        request.mode,
        ExecutionMode.FIXTURE,
        ResultState.DEGRADED,
        best_time=best,
        hotels=hotels,
        routes=routes,
        degraded_reasons=reasons,
    )


def _canonical_best_time(
    request: TripAnalysisRequest,
    inputs: Mapping[str, tuple[Mapping[str, object], AcquisitionRecord]],
) -> BestTimeResult:
    tcm_payload, tcm_record = inputs["destination_tcm"]
    tcm_request = HeatmapRequest(
        AnalyticType.TCM,
        request.destination.latitude,
        request.destination.longitude,
        date.fromisoformat(request.date),
        forecast=False,
        start_hour=8,
        end_hour=20,
    )
    _validate_heatmap_identity(tcm_record, tcm_request)
    translated = translate_heatmap_response(tcm_payload, request=tcm_request)
    heatmap = normalize_heatmap_response(
        translated,
        request=tcm_request,
        retrieved_at=tcm_record.retrieved_at,
        activity_id=tcm_record.activity_id,
        transformations=tcm_record.transformations,
    )
    env_payload, env_record = inputs["environment"]
    env_request = EnvParamsRequest(
        request.destination.latitude,
        request.destination.longitude,
        date.fromisoformat(request.date),
        34.0147,
        start_hour=8,
        end_hour=20,
    )
    for key, expected in {
        "latitude": env_request.latitude,
        "longitude": env_request.longitude,
        "start_date": env_request.start_date.isoformat(),
        "temperature_anchor_celsius": env_request.temperature_anchor_celsius,
        "start_hour": env_request.start_hour,
        "end_hour": env_request.end_hour,
    }.items():
        if env_record.request_configuration.get(key) != expected:
            raise ValueError(f"environment sidecar does not match exact request field {key}")
    normalized_env = normalize_env_params_response(env_payload, request=env_request)
    from app.services.execution import EnvParamsOutcome

    environment = _environment_result(
        request,
        34.0147,
        heatmap,
        EnvParamsOutcome(
            normalized_env,
            "provider",
            env_record.activity_id,
            env_record.transformations,
            retrieved_at=env_record.retrieved_at,
            data_date=env_record.data_date,
        ),
    )
    exceedance = _normalized_metric(inputs["district_exceedance"], AnalyticType.EXCEEDANCE)
    persistence = _normalized_metric(inputs["district_persistence"], AnalyticType.PERSISTENCE)
    result = _best_time_result(
        request,
        heatmap,
        environment,
        environment_failure=None,
        exceedance_hours=exceedance,
        persistence_hours=persistence,
    )
    return replace(
        result,
        temporal_evidence=TemporalEvidenceState.INCONSISTENT,
        recommendation_time=None,
        recommendation_timezone=None,
        recommendation_reason=result.recommendation_reason
        + "; hour-only recommendation because provider GMT-7 conflicts with America/Chicago",
        provenance=replace(
            result.provenance,
            fresh=False,
            note="Genuine FortyGuard TCM and recovered environment values; provider GMT-7 conflicts with America/Chicago, so no exact local timestamp is claimed.",
        ),
    )


def _normalized_metric(
    source: tuple[Mapping[str, object], AcquisitionRecord], analytic: AnalyticType
) -> float:
    payload, record = source
    threshold = None if analytic is AnalyticType.TCM else 35.0
    direction = None if analytic is AnalyticType.TCM else "above"
    request = HeatmapRequest(
        analytic,
        29.425,
        -98.486,
        date(2024, 7, 15),
        forecast=False,
        threshold_celsius=threshold,
        direction=direction,
        granularity=80,
    )
    _validate_heatmap_identity(record, request)
    translated = translate_heatmap_response(payload, request=request)
    result = normalize_heatmap_response(
        translated,
        request=request,
        retrieved_at=record.retrieved_at,
        activity_id=record.activity_id,
        transformations=record.transformations,
    )
    return float(max(tile.metric_value for tile in result.tiles))


def _provider_hotels(
    inputs: Mapping[str, tuple[Mapping[str, object], AcquisitionRecord]],
) -> HotelRankingResult:
    tcm = _normalized_metric(inputs["district_tcm"], AnalyticType.TCM)
    hot = _normalized_metric(inputs["district_exceedance"], AnalyticType.EXCEEDANCE)
    persistence = _normalized_metric(inputs["district_persistence"], AnalyticType.PERSISTENCE)
    hotel_payload, _ = inputs["hotels"]
    discovery = hotel_payload["hotel_discovery"]
    assert isinstance(discovery, Mapping) and isinstance(discovery["hotels"], list)
    candidates = tuple(
        HotelCandidate(
            str(item["name"]),
            {"night": tcm, "hot_hours": hot, "persistence": persistence, "day": tcm},
        )
        for item in discovery["hotels"]
        if isinstance(item, Mapping)
    )
    ranked = HotelRanker().rank(candidates)
    _, record = inputs["district_tcm"]
    return HotelRankingResult(
        ranked=tuple(
            RankedHotel(
                item.identity, dict(item.components), item.score, item.percentile, item.tie_group
            )
            for item in ranked
        ),
        weights=dict(HotelRanker.default_weights),
        usable_count=len(ranked),
        discovered_count=int(discovery["discovered_count"]),
        provenance=Provenance(
            "computed",
            "2024-07-15",
            Confidence.SUFFICIENT,
            record.retrieved_at.isoformat(),
            "hotel-ranking-v1",
            "heat-aware-tourism-guide",
            "completed",
            {
                "hotel_discovery_source": "committed synthesized base fixture",
                "component_evidence": "three genuine canonical district FortyGuard anchors",
                "component_provider": "fortyguard",
                "spatial_interpretation": "anchor values applied equally; no interval or per-hotel maxima invented",
            },
            False,
            note="Computed ranking from genuine district heat components and synthesized base hotel discovery. Night/day are the same date-level TCM anchor, not validated interval maxima.",
            activity_id=record.activity_id,
        ),
        component_units={"night": "C", "hot_hours": "hours", "persistence": "hours", "day": "C"},
        component_temporal_metadata=_hotel_temporal_metadata(),
    )


def _hotel_temporal_metadata() -> dict[str, HotelComponentTemporalMetadata]:
    return {
        name: HotelComponentTemporalMetadata(
            start,
            end,
            "America/Chicago",
            "[start,end)",
            "date_level_tcm",
            False,
            "date_level_not_interval_maximum",
        )
        for name, start, end in (("night", "00:00", "05:00"), ("day", "10:00", "17:00"))
    }


def _synthetic_best_time(request: TripAnalysisRequest, *, elevated: bool) -> BestTimeResult:
    values = (38.0, 39.0, 40.0) if elevated else (32.0, 33.0, 34.0)
    hours = (10, 13, 16)
    hourly = tuple(
        HourlyEntry(hour, Metric(value, "C", MetricLabel.PROVIDER_TCM, False))
        for hour, value in zip(hours, values, strict=True)
    )
    provider = "heat-aware-tourism-guide-synthesized-demo-heat"
    return BestTimeResult(
        hourly,
        10,
        "coolest synthesized demo period; not a provider observation",
        MetricLabel.PROVIDER_TCM,
        Provenance(
            "synthesized",
            request.date,
            Confidence.INSUFFICIENT,
            FIXED_GENERATED_AT.isoformat(),
            "demo-best-time-v1",
            provider,
            "synthesized_demo",
            {
                "evidence_class": "synthesized_demo",
                "purpose": "offline product-state demonstration",
            },
            False,
            note="No live or provider heat acquisition supports these demo values.",
        ),
        len(hourly) / 24,
        classify_heat(values[0], metric=HeatMetricName.TCM),
        recommended_hour_tcm_celsius=values[0],
        recommendation_time=(
            datetime(2024, 7, 15, 10, tzinfo=ZoneInfo("America/Chicago")) if elevated else None
        ),
        recommendation_timezone=("America/Chicago" if elevated else None),
        temporal_evidence=(
            TemporalEvidenceState.EXACT if elevated else TemporalEvidenceState.UNAVAILABLE
        ),
    )


def _synthetic_hotels(
    inputs: Mapping[str, tuple[Mapping[str, object], AcquisitionRecord]],
    *,
    enrichment_failure: bool,
) -> HotelRankingResult:
    base = _provider_hotels(inputs) if enrichment_failure else None
    if base is None:
        candidates = tuple(
            HotelCandidate(
                f"Demo Hotel {index}",
                {
                    "night": 30.0 + index,
                    "hot_hours": float(index),
                    "persistence": float(index) / 2,
                    "day": 35.0 + index,
                },
            )
            for index in range(1, 6)
        )
        ranked_domain = HotelRanker().rank(candidates)
        ranked = tuple(
            RankedHotel(
                item.identity, dict(item.components), item.score, item.percentile, item.tie_group
            )
            for item in ranked_domain
        )
        base = HotelRankingResult(
            ranked,
            dict(HotelRanker.default_weights),
            len(ranked),
            len(ranked),
            _demo_provenance(
                "demo-hotel-ranking-v1", "heat-aware-tourism-guide-synthesized-demo-hotels"
            ),
            component_units={
                "night": "C",
                "hot_hours": "hours",
                "persistence": "hours",
                "day": "C",
            },
            component_temporal_metadata=_hotel_temporal_metadata(),
        )
    return replace(
        base,
        provenance=(
            base.provenance
            if enrichment_failure
            else _demo_provenance(
                "demo-hotel-ranking-v1",
                "heat-aware-tourism-guide-synthesized-demo-hotels",
            )
        ),
        enrichment=(
            OptionalEnrichment(
                EnrichmentState.UNAVAILABLE,
                "optional_provider_failure",
                "Optional hotel enrichment was unavailable; base hotel results are unchanged.",
            )
            if enrichment_failure
            else OptionalEnrichment(EnrichmentState.NOT_REQUESTED)
        ),
    )


def _route_result(
    request: TripAnalysisRequest,
    source: tuple[Mapping[str, object], AcquisitionRecord],
    best: BestTimeResult,
    *,
    heat_provider: str,
) -> RouteComparisonResult:
    routes, routing = _normalized_routes(source, request)
    assert routing.data_date is not None
    routing_provenance = Provenance(
        "fixture",
        routing.data_date,
        Confidence.SUFFICIENT,
        routing.retrieved_at.isoformat(),
        "osrm-route-normalization-v1",
        "fossgis-osrm",
        "completed",
        dict(routing.request_configuration),
        False,
        note=f"Genuine OSRM response retrieved {routing.retrieved_at.isoformat()}.",
    )
    heat = Provenance(
        best.provenance.source,
        request.date,
        best.provenance.confidence,
        best.provenance.retrieved_at,
        "route-landmark-heat-reuse-v1",
        heat_provider,
        best.provenance.response_status,
        {
            "route_heat_source": "landmark_reuse",
            "evidence_class": "provider" if heat_provider == "fortyguard" else "synthesized_demo",
        },
        False,
        note="Route heat reuses destination TCM; no corridor heat acquisition was made.",
    )
    return cast(
        RouteComparisonResult,
        decide_route_comparison(
            RouteDecisionInput(routes, best.recommended_hour_tcm_celsius),
            cautious=False,
            provenance=_decision_provenance(routing_provenance, heat),
            routing_provenance=routing_provenance,
            heat_provenance=heat,
        ),
    )


def _normalized_routes(
    source: tuple[Mapping[str, object], AcquisitionRecord], request: TripAnalysisRequest
) -> tuple[RouteSet, AcquisitionRecord]:
    payload, record = source
    identity = route_request_payload(
        RouteRequest(
            request.origin,
            request.destination,
            "foot",
            True,
            "full",
            "geojson",
            False,
            "fossgis-routed-foot",
            "v1",
        )
    )
    if record.request_configuration != identity:
        raise ValueError("OSRM sidecar does not match the exact product route request")
    return normalize_response(payload, provider_instance="fossgis-routed-foot"), record


class _FixedBuildingExecution:
    def __init__(self, payload: Mapping[str, object], record: AcquisitionRecord) -> None:
        self.payload = payload
        self.record = record

    def identity(self, _aoi: object) -> dict[str, Any]:
        return dict(self.record.request_configuration)

    def run(self, _aoi: object) -> BuildingOutcome:
        assert self.record.data_date is not None
        return BuildingOutcome(
            self.payload,
            "fixture",
            True,
            self.record.retrieved_at,
            self.record.data_date,
            "replayed genuine Overpass fixture",
        )


def _cathedral_routes(
    request: TripAnalysisRequest,
    inputs: Mapping[str, tuple[Mapping[str, object], AcquisitionRecord]],
    best: BestTimeResult,
) -> RouteComparisonResult:
    routes, routing_record = _normalized_routes(inputs["cathedral_osrm"], request)
    building_payload, building_record = inputs["buildings"]
    instant = best.recommendation_time
    assert instant is not None
    centroid = MultiLineString([route.geometry.coordinates for route in routes.routes]).centroid
    solar = solar_position(instant, centroid.y, centroid.x)
    shade = RouteShadeService(
        cast(Any, _FixedBuildingExecution(building_payload, building_record))
    ).load(routes, solar, instant)
    assert routing_record.data_date is not None
    routing = Provenance(
        "fixture",
        routing_record.data_date,
        Confidence.SUFFICIENT,
        routing_record.retrieved_at.isoformat(),
        "osrm-route-normalization-v1",
        "fossgis-osrm",
        "completed",
        dict(routing_record.request_configuration),
        False,
        note="Genuine two-route OSRM response.",
    )
    heat = Provenance(
        "synthesized",
        request.date,
        Confidence.INSUFFICIENT,
        FIXED_GENERATED_AT.isoformat(),
        "route-landmark-heat-reuse-v1",
        "heat-aware-tourism-guide-synthesized-demo-heat",
        "synthesized_demo",
        {"route_heat_source": "landmark_reuse", "purpose": "exercise ADR 0007 only"},
        False,
        note="No Cathedral heat acquisition exists; 38 C is synthesized demo heat, not a provider observation.",
    )
    building = _building_provenance(shade, clock=lambda: FIXED_GENERATED_AT)
    building = replace(
        building,
        provider="overpass-api-de",
        note="Modeled locally from genuine Overpass building geometry; not measured shade.",
    )
    solar_provenance = _solar_provenance(
        solar, instant, centroid.y, centroid.x, clock=lambda: FIXED_GENERATED_AT
    )
    decision_provenance = _decision_provenance(routing, heat)
    return cast(
        RouteComparisonResult,
        decide_route_comparison(
            RouteDecisionInput(routes, 38.0, shade_evidence=shade.evidence),
            cautious=False,
            provenance=decision_provenance,
            routing_provenance=routing,
            heat_provenance=heat,
            building_provenance=building,
            solar_provenance=solar_provenance,
        ),
    )


def _decision_provenance(routing: Provenance, heat: Provenance) -> Provenance:
    confidence = (
        Confidence.SUFFICIENT
        if routing.confidence is heat.confidence is Confidence.SUFFICIENT
        else Confidence.INSUFFICIENT
    )
    return Provenance(
        "computed",
        "2024-07-15",
        confidence,
        FIXED_GENERATED_AT.isoformat(),
        "route-heat-gate-v1",
        "heat-aware-tourism-guide",
        "completed",
        {"routing_provider": routing.provider, "heat_provider": heat.provider},
        False,
    )


def _demo_provenance(transformation: str, provider: str) -> Provenance:
    return Provenance(
        "synthesized",
        "2024-07-15",
        Confidence.INSUFFICIENT,
        FIXED_GENERATED_AT.isoformat(),
        transformation,
        provider,
        "synthesized_demo",
        {"evidence_class": "synthesized_demo"},
        False,
        note="Demo values are not acquired provider observations.",
    )


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_heatmap_identity(record: AcquisitionRecord, request: HeatmapRequest) -> None:
    expected = {
        "analytic_type": request.analytic_type.value,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "start_date": request.start_date.isoformat(),
        "forecast": request.forecast,
        "threshold_celsius": request.threshold_celsius,
        "direction": request.direction,
        "granularity": request.granularity,
    }
    if request.start_hour is not None:
        expected.update(start_hour=request.start_hour, end_hour=request.end_hour)
    for key, value in expected.items():
        if record.request_configuration.get(key) != value:
            raise ValueError(f"FortyGuard sidecar does not match exact request field {key}")


def _generator_metadata(filename: str) -> dict[str, object]:
    if filename == "menger-alamo.trip.json":
        return {
            "evidence": "provider inputs plus computed product decisions",
            "temporal_caveat": "GMT-7 environment evidence is inconsistent with America/Chicago",
        }
    if filename == "main-plaza-market-square.trip.json":
        return {
            "synthesized_sections": ["best_time", "hotels", "route_heat"],
            "route_heat_semantics": "reuses synthesized destination demo TCM",
            "provider_observations": ["routing"],
        }
    if filename == "cathedral-governors-palace.trip.json":
        return {
            "synthesized_sections": ["best_time_heat", "optional_enrichment_failure"],
            "demo_heat_purpose": "exercise ADR 0007; not a provider observation",
            "computed_sections": ["solar_position", "modeled_building_shade"],
            "provider_observations": ["routing", "building_geometry", "hotel_components"],
        }
    return {
        "synthesized_sections": ["core_provider_failure"],
        "provider_observations": [],
        "orchestration_stopped_before": ["environment", "hotels", "routing"],
    }
