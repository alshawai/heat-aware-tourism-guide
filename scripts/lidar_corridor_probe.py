"""Probe official USGS lidar coverage for bounded tourism corridors.

The default run only retrieves catalog metadata. Pass ``--download`` to save
the intersecting LAZ files; downloaded binary data is intentionally ignored by
git and should be treated as a local research artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import LineString
from shapely.ops import transform
from pyproj import Transformer

API_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASET = "Lidar Point Cloud (LPC)"

CORRIDORS = {
    "san_antonio": {
        "origin": (-98.4861, 29.4259),
        "destination": (-98.4853, 29.4225),
    },
    "austin": {
        "origin": (-97.7415, 30.2676),
        "destination": (-97.7405, 30.2747),
    },
}


def corridor_aoi(
    origin: tuple[float, float], destination: tuple[float, float], buffer_m: float
) -> tuple[float, float, float, float]:
    """Return a WGS84 bbox around a locally projected route corridor."""
    route = LineString([origin, destination])
    zone = int((route.centroid.x + 180) // 6) + 1
    crs = f"EPSG:{32600 + zone}"
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    buffered = transform(inverse, transform(forward, route).buffer(buffer_m))
    return tuple(round(value, 7) for value in buffered.bounds)


def fetch_products(bbox: tuple[float, float, float, float], timeout: float) -> dict[str, object]:
    params = urlencode(
        {
            "bbox": ",".join(str(value) for value in bbox),
            "datasets": DATASET,
            "outputFormat": "json",
            "max": 100,
        }
    )
    request = Request(f"{API_URL}?{params}", headers={"User-Agent": "heat-aware-tourism-guide/0.1"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("National Map response must be a JSON object")
    return cast(dict[str, object], payload)


def download_file(url: str, destination: Path, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": "heat-aware-tourism-guide/0.1"})
    digest = hashlib.sha256()
    partial = destination.with_suffix(f"{destination.suffix}.part")
    try:
        with urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
    except (HTTPError, OSError):
        partial.unlink(missing_ok=True)
        raise
    partial.replace(destination)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buffer-m", type=float, default=100.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--download", action="store_true", help="Download intersecting LAZ files")
    parser.add_argument("--city", choices=sorted(CORRIDORS), action="append")
    parser.add_argument("--output", type=Path, default=Path("data/lidar-prototype"))
    args = parser.parse_args()
    if args.buffer_m <= 0:
        parser.error("--buffer-m must be positive")

    args.output.mkdir(parents=True, exist_ok=True)
    selected = args.city or list(CORRIDORS)
    corridors: dict[str, dict[str, Any]] = {}
    records: dict[str, Any] = {
        "source": API_URL,
        "dataset": DATASET,
        "buffer_m": args.buffer_m,
        "corridors": corridors,
    }
    for name in selected:
        points = CORRIDORS[name]
        bbox = corridor_aoi(points["origin"], points["destination"], args.buffer_m)
        response = fetch_products(bbox, args.timeout)
        items = response.get("items", [])
        if not isinstance(items, list):
            raise ValueError(f"National Map response for {name} has invalid items")
        corridor: dict[str, object] = {
            "origin": points["origin"],
            "destination": points["destination"],
            "bbox": bbox,
            "query_url": response.get("sciencebaseQuery"),
            "total": response.get("total", len(items)),
            "items": items,
        }
        corridors[name] = corridor
        print(f"{name}: {len(items)} intersecting lidar product(s)")

    output = args.output / "coverage.json"
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Metadata written to {output}")
    if args.download:
        download_root = args.output / "laz"
        download_root.mkdir(exist_ok=True)
        for name, corridor in corridors.items():
            seen_urls: set[str] = set()
            items = cast(list[dict[str, Any]], corridor["items"])
            for item in items:
                url = item.get("downloadLazURL") or item.get("downloadURL")
                if not isinstance(url, str) or url in seen_urls:
                    continue
                seen_urls.add(url)
                filename = url.rsplit("/", maxsplit=1)[-1]
                destination = download_root / filename
                if destination.exists():
                    print(f"{name}: already downloaded {destination}")
                    continue
                print(f"{name}: downloading {filename}")
                checksum = download_file(url, destination, args.timeout)
                print(f"{name}: sha256={checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
