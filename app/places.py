"""Server-owned place catalog for San Antonio exploratory trip setup."""

from __future__ import annotations

from typing import TypedDict


class Place(TypedDict):
    id: str
    name: str
    context: str
    latitude: float
    longitude: float


PLACES: tuple[Place, ...] = (
    {
        "id": "menger-hotel",
        "name": "Menger Hotel",
        "context": "San Antonio, TX",
        "latitude": 29.4245914,
        "longitude": -98.4864288,
    },
    {
        "id": "the-alamo",
        "name": "The Alamo",
        "context": "San Antonio, TX",
        "latitude": 29.425833,
        "longitude": -98.485833,
    },
    {
        "id": "main-plaza",
        "name": "Main Plaza",
        "context": "San Antonio, TX",
        "latitude": 29.4245773,
        "longitude": -98.4935063,
    },
    {
        "id": "historic-market-square-el-mercado",
        "name": "Historic Market Square (El Mercado)",
        "context": "San Antonio, TX",
        "latitude": 29.4254009,
        "longitude": -98.4994785,
    },
    {
        "id": "san-fernando-cathedral",
        "name": "San Fernando Cathedral",
        "context": "San Antonio, TX",
        "latitude": 29.4245590,
        "longitude": -98.4942042,
    },
    {
        "id": "spanish-governors-palace",
        "name": "Spanish Governor's Palace",
        "context": "San Antonio, TX",
        "latitude": 29.4248225,
        "longitude": -98.4959872,
    },
    {
        "id": "briscoe-western-art-museum",
        "name": "Briscoe Western Art Museum",
        "context": "San Antonio, TX",
        "latitude": 29.4228983,
        "longitude": -98.4888465,
    },
    {
        "id": "tower-of-the-americas",
        "name": "Tower of the Americas",
        "context": "San Antonio, TX",
        "latitude": 29.4190825,
        "longitude": -98.4835734,
    },
)


def search_places(query: str) -> list[Place]:
    """Return catalog places whose display names contain the normalized query."""
    normalized_query = query.strip().casefold()
    return [place.copy() for place in PLACES if normalized_query in place["name"].casefold()]
