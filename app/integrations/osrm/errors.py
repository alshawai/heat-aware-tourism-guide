"""OSRM integration errors."""


class OsrmError(RuntimeError):
    """Base class for route-provider failures."""


class OsrmTransportError(OsrmError):
    """The route provider could not be reached or returned an HTTP failure."""


class OsrmMalformedResponse(OsrmError):
    """The route provider returned an invalid response shape."""


class OsrmNoRoute(OsrmError):
    """The route provider found no pedestrian route."""
