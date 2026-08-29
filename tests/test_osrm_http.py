"""OSRM HTTP integration behavior for issue #18 phase 2."""

import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from app.domain.contracts import Coordinates
from app.domain.routing import RouteRequest
from app.integrations.osrm.client import OsrmClient
from app.integrations.osrm.errors import OsrmMalformedResponse, OsrmNoRoute, OsrmTransportError
from app.integrations.osrm.transport import HttpOsrmTransport
from app.settings import SettingsError, load_settings


class _Response:
    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _request() -> RouteRequest:
    return RouteRequest(
        origin=Coordinates(29.4245914, -98.4864288),
        destination=Coordinates(29.425833, -98.485833),
        profile="foot",
        alternatives=True,
        overview="full",
        geometries="geojson",
        steps=False,
        provider_instance="fossgis-routed-foot",
        request_version="osrm-route-v1",
    )


def _payload(route_count: int = 2) -> dict[str, object]:
    routes = []
    for index in range(route_count):
        routes.append(
            {
                "distance": 132.0 + index * 18,
                "duration": 105.0 + index * 12,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-98.4864288, 29.4245914],
                        [-98.4860 + index * 0.0001, 29.4252],
                        [-98.485833, 29.425833],
                    ],
                },
            }
        )
    return {"code": "Ok", "routes": routes}


def test_client_makes_one_full_geojson_pedestrian_request() -> None:
    opened: list[tuple[str, float, str]] = []

    def opener(request: object, timeout: float) -> _Response:
        opened.append(
            (
                getattr(request, "full_url"),
                timeout,
                getattr(request, "headers")["User-agent"],
            )
        )
        return _Response(_payload())

    client = OsrmClient(
        HttpOsrmTransport(
            "https://routing.openstreetmap.de/routed-foot/route/v1",
            user_agent="HeatAwareTourismGuide/0.1 (contact: project repository)",
            timeout_seconds=7.5,
            opener=opener,
        )
    )

    routes = client.route(_request())

    assert len(opened) == 1
    url, timeout, user_agent = opened[0]
    assert url.startswith(
        "https://routing.openstreetmap.de/routed-foot/route/v1/foot/"
        "-98.4864288,29.4245914;-98.485833,29.425833?"
    )
    assert "alternatives=true" in url
    assert "overview=full" in url
    assert "geometries=geojson" in url
    assert "steps=false" in url
    assert timeout == 7.5
    assert "HeatAwareTourismGuide" in user_agent
    assert [route.identity for route in routes.routes] == ["route-1", "route-2"]
    assert routes.shortest.distance_m == 132.0


def test_client_accepts_one_returned_route_without_fabricating_an_alternative() -> None:
    transport = HttpOsrmTransport(
        "https://routing.example.test/route/v1",
        user_agent="HeatAwareTourismGuide contact project repository",
        opener=lambda request, timeout: _Response(_payload(1)),
    )
    routes = OsrmClient(transport).route(_request())
    assert len(routes.routes) == 1
    assert routes.routes[0].identity == "route-1"


# pytest's parameterization decorator is untyped.
@pytest.mark.parametrize(  # type: ignore[misc]
    "payload,error_type",
    [
        ({"code": "NoRoute", "routes": []}, OsrmNoRoute),
        ({"code": "Ok", "routes": []}, OsrmNoRoute),
        ({"code": "Ok", "routes": [{"distance": 10, "duration": 2}]}, OsrmMalformedResponse),
        ({"code": "Ok", "routes": [{"distance": -1, "duration": 2, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]}, OsrmMalformedResponse),
    ],
)
def test_client_classifies_no_route_and_malformed_responses(
    payload: dict[str, object], error_type: type[Exception]
) -> None:
    transport = HttpOsrmTransport(
        "https://routing.example.test/route/v1",
        user_agent="HeatAwareTourismGuide contact project repository",
        opener=lambda request, timeout: _Response(payload),
    )
    with pytest.raises(error_type):
        OsrmClient(transport).route(_request())


def test_transport_classifies_http_and_invalid_json_failures() -> None:
    def fail_http(request: object, timeout: float) -> object:
        raise HTTPError("url", 503, "failed", Message(), None)

    transport = HttpOsrmTransport(
        "https://routing.example.test/route/v1",
        user_agent="HeatAwareTourismGuide contact project repository",
        opener=fail_http,
    )
    with pytest.raises(OsrmTransportError, match="503"):
        OsrmClient(transport).route(_request())

    class InvalidResponse(_Response):
        def __init__(self) -> None:
            self.body = b"not json"

    malformed = HttpOsrmTransport(
        "https://routing.example.test/route/v1",
        user_agent="HeatAwareTourismGuide contact project repository",
        opener=lambda request, timeout: InvalidResponse(),
    )
    with pytest.raises(OsrmMalformedResponse, match="JSON"):
        OsrmClient(malformed).route(_request())


def test_osrm_settings_have_validated_defaults_and_environment_overrides() -> None:
    defaults = load_settings(environ={}).osrm
    assert defaults.profile == "foot"
    assert defaults.alternatives is True
    assert defaults.overview == "full"
    assert defaults.geometries == "geojson"
    assert defaults.representative_distance_m == 1500.0
    assert defaults.minimum_heat_coverage == 0.70

    overridden = load_settings(
        environ={
            "OSRM_BASE_URL": "https://routing.example.test/route/v1",
            "OSRM_TIMEOUT_SECONDS": "8",
            "ROUTE_REPRESENTATIVE_DISTANCE_M": "900",
            "ROUTE_MINIMUM_HEAT_COVERAGE": "0.8",
        }
    ).osrm
    assert overridden.base_url == "https://routing.example.test/route/v1"
    assert overridden.timeout_seconds == 8
    assert overridden.representative_distance_m == 900
    assert overridden.minimum_heat_coverage == 0.8

    with pytest.raises(SettingsError, match="ROUTE_MINIMUM_HEAT_COVERAGE"):
        load_settings(environ={"ROUTE_MINIMUM_HEAT_COVERAGE": "1.1"})
