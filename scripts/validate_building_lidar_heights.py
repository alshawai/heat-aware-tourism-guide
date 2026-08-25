"""Compare OSM building footprints with classified USGS lidar returns.

This bounded research check estimates a robust roof-minus-ground height for
each OSM building footprint intersecting the canonical San Antonio corridor.
It is evidence for data coverage, not a finished shadow model.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np
from pyproj import Transformer
from shapely import contains_xy
from shapely.geometry import Polygon
from shapely.ops import transform

ROUTE = ((-98.4861, 29.4259), (-98.4853, 29.4225))
PROJECTED_CRS = "EPSG:6343"


def parse_buildings(path: Path) -> list[dict[str, Any]]:
    root = ElementTree.parse(path).getroot()
    nodes = {
        node.attrib["id"]: (float(node.attrib["lon"]), float(node.attrib["lat"]))
        for node in root.findall("node")
    }
    buildings: list[dict[str, Any]] = []
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib.get("v", "") for tag in way.findall("tag")}
        if "building" not in tags:
            continue
        coordinates = [nodes[ref.attrib["ref"]] for ref in way.findall("nd")]
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
            continue
        polygon = Polygon(coordinates)
        if polygon.is_valid and not polygon.is_empty:
            buildings.append({"id": int(way.attrib["id"]), "tags": tags, "polygon": polygon})
    return buildings


def project_polygon(polygon: Polygon) -> Polygon:
    transformer = Transformer.from_crs("EPSG:4326", PROJECTED_CRS, always_xy=True)
    return transform(transformer.transform, polygon)


def estimate_heights(
    laz_path: Path,
    buildings: list[dict[str, Any]],
    *,
    route: tuple[tuple[float, float], ...],
    corridor_m: float,
) -> list[dict[str, Any]]:
    import laspy

    route_transformer = Transformer.from_crs("EPSG:4326", PROJECTED_CRS, always_xy=True)
    projected_route = [route_transformer.transform(*point) for point in route]
    from shapely.geometry import LineString

    corridor = LineString(projected_route).buffer(corridor_m)
    selected = [building for building in buildings if project_polygon(building["polygon"]).intersects(corridor)]
    projected = [project_polygon(building["polygon"]) for building in selected]
    ground: list[list[float]] = [[] for _ in selected]
    roofs: list[list[float]] = [[] for _ in selected]
    with laspy.open(laz_path) as source:
        for chunk in source.chunk_iterator(1_000_000):
            x = np.asarray(chunk.x)
            y = np.asarray(chunk.y)
            z = np.asarray(chunk.z)
            classes = np.asarray(chunk.classification)
            for index, polygon in enumerate(projected):
                inside = contains_xy(polygon, x, y)
                if np.any(inside):
                    ground[index].extend(z[inside & (classes == 2)].tolist())
                    roofs[index].extend(z[inside & (classes == 6)].tolist())

    results = []
    for building, polygon, ground_values, roof_values in zip(selected, projected, ground, roofs, strict=True):
        estimate = None
        if ground_values and roof_values:
            estimate = float(np.median(roof_values) - np.median(ground_values))
        results.append(
            {
                "osm_way_id": building["id"],
                "tags": building["tags"],
                "area_m2": polygon.area,
                "ground_points": len(ground_values),
                "roof_points": len(roof_values),
                "estimated_height_m": estimate,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("osm_xml", type=Path)
    parser.add_argument("laz", type=Path)
    parser.add_argument("--route-json", type=Path, help="OSRM GeoJSON response; uses the first route")
    parser.add_argument("--corridor-m", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=Path("data/lidar-prototype/building-heights.json"))
    args = parser.parse_args()
    route = ROUTE
    if args.route_json:
        response = json.loads(args.route_json.read_text(encoding="utf-8"))
        coordinates = response["routes"][0]["geometry"]["coordinates"]
        route = tuple((float(point[0]), float(point[1])) for point in coordinates)
    results = estimate_heights(
        args.laz,
        parse_buildings(args.osm_xml),
        route=route,
        corridor_m=args.corridor_m,
    )
    payload = {
        "source_osm": str(args.osm_xml),
        "source_lidar": str(args.laz),
        "corridor_m": args.corridor_m,
        "buildings": results,
        "buildings_with_positive_height": sum(
            result["estimated_height_m"] is not None and result["estimated_height_m"] > 0 for result in results
        ),
        "coverage_basis": "OSM closed building ways intersecting the route corridor and having ground plus class-6 roof returns.",
        "interpretation": "Research validation only; building footprint completeness and shadow accuracy remain unverified.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}: {len(results)} buildings, {payload['buildings_with_positive_height']} with estimates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
