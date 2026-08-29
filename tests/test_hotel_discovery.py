from datetime import datetime, timezone

from app.domain.hotels import BoundingBox, DiscoveryState, HotelDiscoveryResult, OsmIdentity
from app.integrations.overpass.client import OverpassClient
from app.integrations.overpass.errors import OverpassError, OverpassRateLimited
from app.services.cache import CacheService
from app.services.hotel_discovery import HotelDiscoveryService


AOI = BoundingBox(29.421, -98.490, 29.429, -98.482)
NOW = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)


class StubTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.queries: list[str] = []

    def execute(self, query: str) -> dict[str, object]:
        self.queries.append(query)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response


def payload(elements: list[dict[str, object]]) -> dict[str, object]:
    return {
        "osm3s": {"timestamp_osm_base": "2026-08-29T11:58:00Z"},
        "elements": elements,
    }


def hotel(
    osm_id: int,
    name: str | None,
    *,
    osm_type: str = "node",
    lat: float = 29.424,
    lon: float = -98.486,
    tags: dict[str, str] | None = None,
    members: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    element: dict[str, object] = {
        "type": osm_type,
        "id": osm_id,
        "tags": {
            "tourism": "hotel",
            **({"name": name} if name is not None else {}),
            **(tags or {}),
        },
    }
    if osm_type == "node":
        element.update(lat=lat, lon=lon)
    else:
        element["center"] = {"lat": lat, "lon": lon}
    if members is not None:
        element["members"] = members
    return element


def discover(elements: list[dict[str, object]]) -> HotelDiscoveryResult:
    client = OverpassClient(StubTransport([payload(elements)]), max_attempts=1)
    return HotelDiscoveryService(
        client,
        CacheService(),
        provider_endpoint="https://overpass.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: NOW,
    ).discover()


def test_discovery_normalizes_nodes_ways_relations_and_source_identity() -> None:
    result = discover(
        [
            hotel(1, "Node Hotel"),
            hotel(2, "Way Hotel", osm_type="way", lat=29.425),
            hotel(3, "Relation Hotel", osm_type="relation", lat=29.426),
        ]
    )

    assert result.state is DiscoveryState.UNAVAILABLE
    assert result.source_timestamp == datetime(2026, 8, 29, 11, 58, tzinfo=timezone.utc)
    assert result.retrieved_at == NOW
    assert result.discovered_count == 3
    assert [candidate.primary_identity for candidate in result.candidates] == [
        OsmIdentity("node", 1),
        OsmIdentity("way", 2),
        OsmIdentity("relation", 3),
    ]
    assert [(candidate.latitude, candidate.longitude) for candidate in result.candidates] == [
        (29.424, -98.486),
        (29.425, -98.486),
        (29.426, -98.486),
    ]


def test_discovery_deduplicates_identity_relation_membership_and_strong_metadata() -> None:
    result = discover(
        [
            hotel(1, "Exact Hotel"),
            hotel(1, "Exact Hotel"),
            hotel(2, None, osm_type="way"),
            hotel(
                3,
                "Member Hotel",
                osm_type="relation",
                members=[{"type": "way", "ref": 2, "role": "building"}],
            ),
            hotel(
                4,
                "Metadata Hotel",
                tags={"addr:housenumber": "100", "addr:street": "Alamo Plaza"},
            ),
            hotel(
                5,
                " metadata   HOTEL ",
                osm_type="way",
                tags={"addr:housenumber": "100", "addr:street": "ALAMO PLAZA"},
            ),
        ]
    )

    assert result.discovered_count == 6
    assert result.usable_count == 3
    assert result.candidates[0].source_identities == (OsmIdentity("node", 1),)
    assert result.candidates[1].source_identities == (
        OsmIdentity("way", 2),
        OsmIdentity("relation", 3),
    )
    assert result.candidates[1].name == "Member Hotel"
    assert result.candidates[2].source_identities == (
        OsmIdentity("node", 4),
        OsmIdentity("way", 5),
    )


def test_nearby_hotels_and_names_without_corroboration_remain_distinct() -> None:
    result = discover(
        [
            hotel(1, "Marriott", lat=29.424000, lon=-98.486000),
            hotel(2, "Marriott", osm_type="way", lat=29.424001, lon=-98.486001),
            hotel(3, "A Hotel", lat=29.425000, lon=-98.485000),
            hotel(4, "B Hotel", osm_type="way", lat=29.425000, lon=-98.485000),
        ]
    )

    assert result.usable_count == 4
    assert all(len(candidate.source_identities) == 1 for candidate in result.candidates)


def test_website_and_operator_corroborate_names_but_conflicts_do_not_merge() -> None:
    result = discover(
        [
            hotel(1, "Website Hotel", tags={"website": "https://example.test/hotel/"}),
            hotel(
                2,
                " website hotel ",
                osm_type="way",
                tags={"contact:website": "https://EXAMPLE.test/hotel"},
            ),
            hotel(3, "Operator Hotel", tags={"operator": "Local Lodging"}),
            hotel(
                4,
                "OPERATOR HOTEL",
                osm_type="way",
                tags={"operator": " local lodging "},
            ),
            hotel(5, "Conflicted Hotel", tags={"operator": "Operator One"}),
            hotel(
                6,
                "Conflicted Hotel",
                osm_type="way",
                tags={"operator": "Operator Two"},
            ),
        ]
    )

    assert result.usable_count == 4
    assert result.candidates[0].source_identities == (
        OsmIdentity("node", 1),
        OsmIdentity("way", 2),
    )
    assert result.candidates[1].source_identities == (
        OsmIdentity("node", 3),
        OsmIdentity("way", 4),
    )
    assert result.candidates[2].source_identities == (OsmIdentity("node", 5),)
    assert result.candidates[3].source_identities == (OsmIdentity("way", 6),)


def test_missing_names_or_coordinates_are_not_usable_and_under_five_is_explicit() -> None:
    nameless = hotel(1, None)
    no_center = hotel(2, "No Center", osm_type="way")
    no_center.pop("center")
    result = discover([nameless, no_center, hotel(3, "One"), hotel(4, "Two"), hotel(5, "Three")])

    assert result.state is DiscoveryState.UNAVAILABLE
    assert result.discovered_count == 5
    assert result.usable_count == 3
    assert result.reason == "insufficient_usable_hotels"


def test_exactly_five_usable_hotels_are_available() -> None:
    result = discover([hotel(osm_id, f"Hotel {osm_id}") for osm_id in range(1, 6)])

    assert result.state is DiscoveryState.AVAILABLE
    assert result.usable_count == 5


def test_provider_failure_replays_exact_cache_with_original_timestamp_and_ids() -> None:
    cache = CacheService()
    successful = HotelDiscoveryService(
        OverpassClient(
            StubTransport(
                [payload([hotel(osm_id, f"Cached Hotel {osm_id}") for osm_id in range(1, 6)])]
            ),
            max_attempts=1,
        ),
        cache,
        provider_endpoint="https://overpass.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: NOW,
    )
    successful.discover()
    failing = HotelDiscoveryService(
        OverpassClient(StubTransport([OverpassError("offline")]), max_attempts=1),
        cache,
        provider_endpoint="https://overpass.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: datetime(2026, 8, 30, tzinfo=timezone.utc),
    )

    result = failing.discover()

    assert result.state is DiscoveryState.AVAILABLE
    assert result.source == "cache"
    assert result.stale is True
    assert result.source_timestamp == datetime(2026, 8, 29, 11, 58, tzinfo=timezone.utc)
    assert result.candidates[0].source_identities == (OsmIdentity("node", 1),)


def test_provider_failure_without_cache_is_explicitly_unavailable() -> None:
    service = HotelDiscoveryService(
        OverpassClient(StubTransport([OverpassError("offline")]), max_attempts=1),
        CacheService(),
        provider_endpoint="https://overpass.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: NOW,
    )

    result = service.discover()

    assert result.state is DiscoveryState.UNAVAILABLE
    assert result.reason == "provider_failure"
    assert result.candidates == ()


def test_malformed_provider_response_is_not_cached_and_is_explicitly_unavailable() -> None:
    cache = CacheService()
    malformed = {"osm3s": {"timestamp_osm_base": "2026-08-29T11:58:00Z"}}
    service = HotelDiscoveryService(
        OverpassClient(StubTransport([malformed]), max_attempts=1),
        cache,
        provider_endpoint="https://overpass.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: NOW,
    )

    result = service.discover()

    assert result.state is DiscoveryState.UNAVAILABLE
    assert result.reason == "provider_failure"


def test_malformed_object_identity_and_website_are_skipped_or_unavailable() -> None:
    invalid_id = discover([hotel(0, "Invalid ID")])
    assert invalid_id.state is DiscoveryState.UNAVAILABLE
    assert invalid_id.discovered_count == 0

    invalid_website = discover([hotel(1, "Invalid Website", tags={"website": "example.test:bad"})])
    assert invalid_website.state is DiscoveryState.UNAVAILABLE
    assert invalid_website.reason == "provider_failure"

    invalid_host = discover([hotel(1, "Invalid Host", tags={"website": "http://[invalid"})])
    assert invalid_host.state is DiscoveryState.UNAVAILABLE
    assert invalid_host.reason == "provider_failure"


def test_malformed_relation_member_id_cannot_merge_an_unrelated_hotel() -> None:
    relation = hotel(
        2,
        "Relation Hotel",
        osm_type="relation",
        members=[
            {"type": "node", "ref": True},
            {"type": "way", "ref": 0},
            {"type": "way", "ref": -1},
        ],
    )

    result = discover([hotel(1, "Independent Hotel"), relation])

    assert result.usable_count == 2
    assert all(len(candidate.source_identities) == 1 for candidate in result.candidates)


def test_cache_identity_separates_overpass_provider_endpoints() -> None:
    cache = CacheService()
    first = HotelDiscoveryService(
        OverpassClient(
            StubTransport([payload([hotel(osm_id, f"Hotel {osm_id}") for osm_id in range(1, 6)])]),
            max_attempts=1,
        ),
        cache,
        provider_endpoint="https://one.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: NOW,
    )
    first.discover()
    second = HotelDiscoveryService(
        OverpassClient(StubTransport([OverpassError("offline")]), max_attempts=1),
        cache,
        provider_endpoint="https://two.example.test/interpreter",
        district_aoi=AOI,
        clock=lambda: NOW,
    )

    assert second.discover().reason == "provider_failure"


def test_overpass_client_queries_all_object_types_and_bounds_429_retry() -> None:
    transport = StubTransport([OverpassRateLimited(), payload([])])
    sleeps: list[float] = []
    client = OverpassClient(transport, max_attempts=2, retry_delay_seconds=30, sleep=sleeps.append)

    assert client.query(AOI) == payload([])
    assert sleeps == [30]
    assert len(transport.queries) == 2
    assert 'nwr["tourism"="hotel"](29.421,-98.49,29.429,-98.482);' in transport.queries[0]
    assert "out center;" in transport.queries[0]


def test_overpass_client_stops_after_bounded_429_attempts() -> None:
    transport = StubTransport([OverpassRateLimited(), OverpassRateLimited()])
    sleeps: list[float] = []
    client = OverpassClient(transport, max_attempts=2, retry_delay_seconds=30, sleep=sleeps.append)

    try:
        client.query(AOI)
    except OverpassRateLimited:
        pass
    else:
        raise AssertionError("expected rate limiting to be surfaced")
    assert len(transport.queries) == 2
    assert sleeps == [30]
