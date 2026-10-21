"""Coordinate conversion and nearest-neighbour helpers.

All distances are calculated on the British National Grid (EPSG:27700), where one unit
is one metre. Latitude and longitude (WGS84) are only used for the map.
"""

from __future__ import annotations

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

_to_latlon = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
_to_grid = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)


def grid_to_latlon(easting, northing) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = _to_latlon.transform(np.asarray(easting, float), np.asarray(northing, float))
    return np.asarray(lat), np.asarray(lon)


def latlon_to_grid(lat, lon) -> tuple[np.ndarray, np.ndarray]:
    easting, northing = _to_grid.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.asarray(easting), np.asarray(northing)


def nearest(points: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance to, and index of, the nearest target for every point."""
    if len(targets) == 0:
        return np.full(len(points), np.nan), np.full(len(points), -1)
    distance, index = cKDTree(targets).query(points, k=1)
    return distance, index


def count_within(points: np.ndarray, targets: np.ndarray, radius: float) -> np.ndarray:
    """How many targets lie within `radius` metres of every point."""
    if len(targets) == 0:
        return np.zeros(len(points), dtype=int)
    return np.asarray(cKDTree(targets).query_ball_point(points, r=radius, return_length=True))
