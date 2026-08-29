"""Overpass integration failures."""


class OverpassError(RuntimeError):
    """A request or response failure from Overpass."""


class OverpassRateLimited(OverpassError):
    """Overpass rejected a request with HTTP 429."""
