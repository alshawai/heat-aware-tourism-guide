"""Derive lightweight object-height statistics from one USGS LAZ tile.

This is a research prototype, not the production shade engine. It uses a
projected route buffer and a regular grid to compare non-ground returns with
ground returns. Install ``laspy[lazrs]`` in the local research environment;
the application runtime does not depend on it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import laspy
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point

ROUTES = {
    "san_antonio": (Point(-98.4861, 29.4259), Point(-98.4853, 29.4225)),
    "austin": (Point(-97.7415, 30.2676), Point(-97.7405, 30.2747)),
}
UTM_CRS = "EPSG:6343"
OBJECT_CLASSES = {3, 4, 5, 6, 9, 10, 13, 14}


def route_bounds(route: tuple[Point, Point], buffer_m: float) -> tuple[float, float, float, float]:
    transformer = Transformer.from_crs("EPSG:4326", UTM_CRS, always_xy=True)
    projected = LineString([transformer.transform(point.x, point.y) for point in route])
    return projected.buffer(buffer_m).bounds


def derive_stats(path: Path, *, route: tuple[Point, Point], buffer_m: float, cell_m: float) -> dict[str, Any]:
    if buffer_m <= 0 or cell_m <= 0:
        raise ValueError("buffer_m and cell_m must be positive")
    min_x, min_y, max_x, max_y = route_bounds(route, buffer_m)
    width = int(np.ceil((max_x - min_x) / cell_m))
    height = int(np.ceil((max_y - min_y) / cell_m))
    ground_sum = np.zeros((height, width), dtype=np.float64)
    ground_count = np.zeros((height, width), dtype=np.uint32)
    object_max = np.full((height, width), np.nan, dtype=np.float32)
    object_count = np.zeros((height, width), dtype=np.uint32)
    points_in_corridor = 0
    class_counts: dict[int, int] = {}

    with laspy.open(path) as source:
        for chunk in source.chunk_iterator(1_000_000):
            x = np.asarray(chunk.x)
            y = np.asarray(chunk.y)
            z = np.asarray(chunk.z)
            inside = (x >= min_x) & (x < max_x) & (y >= min_y) & (y < max_y)
            if not np.any(inside):
                continue
            x, y, z = x[inside], y[inside], z[inside]
            classes = np.asarray(chunk.classification)[inside].astype(np.int16)
            points_in_corridor += int(len(z))
            unique, counts = np.unique(classes, return_counts=True)
            for class_id, count in zip(unique.tolist(), counts.tolist(), strict=True):
                class_counts[class_id] = class_counts.get(class_id, 0) + count
            columns = np.floor((x - min_x) / cell_m).astype(np.int64)
            rows = np.floor((y - min_y) / cell_m).astype(np.int64)
            valid = (rows >= 0) & (rows < height) & (columns >= 0) & (columns < width)
            rows, columns, z, classes = rows[valid], columns[valid], z[valid], classes[valid]
            ground = classes == 2
            np.add.at(ground_sum, (rows[ground], columns[ground]), z[ground])
            np.add.at(ground_count, (rows[ground], columns[ground]), 1)
            objects = np.isin(classes, list(OBJECT_CLASSES))
            for row, column, elevation in zip(rows[objects], columns[objects], z[objects], strict=True):
                current = object_max[row, column]
                object_max[row, column] = elevation if np.isnan(current) else max(current, elevation)
                object_count[row, column] += 1

    ground = np.divide(ground_sum, ground_count, out=np.full_like(ground_sum, np.nan), where=ground_count > 0)
    height_grid = object_max - ground
    valid_heights = height_grid[np.isfinite(height_grid) & (height_grid > 0)]
    return {
        "source_file": str(path),
        "source_crs": UTM_CRS,
        "route": [[point.x, point.y] for point in route],
        "buffer_m": buffer_m,
        "cell_m": cell_m,
        "grid_shape": [height, width],
        "points_in_corridor": points_in_corridor,
        "ground_cells": int(np.count_nonzero(ground_count)),
        "object_cells": int(np.count_nonzero(object_count)),
        "class_counts": {str(key): value for key, value in sorted(class_counts.items())},
        "positive_object_height_cells": int(len(valid_heights)),
        "object_height_m": {
            "min": float(np.min(valid_heights)) if len(valid_heights) else None,
            "median": float(np.median(valid_heights)) if len(valid_heights) else None,
            "max": float(np.max(valid_heights)) if len(valid_heights) else None,
        },
        "interpretation": "Surface-minus-ground screening statistic; not validated building height or shade.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("laz", type=Path)
    parser.add_argument("--city", choices=sorted(ROUTES), default="san_antonio")
    parser.add_argument("--buffer-m", type=float, default=100.0)
    parser.add_argument("--cell-m", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=Path("data/lidar-prototype/san_antonio-stats.json"))
    args = parser.parse_args()
    result = derive_stats(args.laz, route=ROUTES[args.city], buffer_m=args.buffer_m, cell_m=args.cell_m)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(json.dumps(result["object_height_m"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
