"""
Test helpers: synthetic rasters, and a staged directory laid out the way ADES stage-in writes it.

`stage_item` takes one real STAC item JSON and writes small synthetic rasters for its GeoTIFF
assets, with the same band layout and on a grid near the item's real location. Tests and
`make check-docker` use it, so the workflow runs on the item's real metadata without network access.

    python -m eodh_workflow stage <item.json> <staged_dir>
"""

import copy
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Sequence

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import transform

from .inputs import asset_bands, band_common_name, is_geotiff

logger = logging.getLogger(__name__)

SIZE = 600  # > 512 so COG outputs get at least one overview level
NODATA_COLUMNS = 20  # left-hand columns set to nodata in every band
# Typical surface reflectance (x 10000) of vegetation, per STAC common name. Other bands get 1000.
DEFAULT_VALUES = {"coastal": 400, "blue": 300, "green": 2500, "red": 500, "rededge": 2000, "nir": 3000, "nir08": 3000}


def write_synthetic_raster(
    path: Path,
    values: Sequence[float],
    crs="EPSG:32630",
    origin=(455000.0, 5722000.0),
    resolution: float = 10.0,
    size: int = SIZE,
    dtype: str = "uint16",
    nodata=0,
) -> Path:
    """
    Write a tiled GTiff with one band per value: the value plus a gradient (0-100 over the image)
    that varies along both axes, so a row or column offset error changes the result.
    The first `NODATA_COLUMNS` columns are nodata.
    """
    gradient = (
        np.linspace(0, 60, size, dtype="float64")[np.newaxis, :]
        + np.linspace(0, 40, size, dtype="float64")[:, np.newaxis]
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=len(values),
        dtype=dtype,
        crs=CRS.from_user_input(crs),
        transform=from_origin(*origin, resolution, resolution),
        nodata=nodata,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        for index, value in enumerate(values, start=1):
            band = (value + gradient).astype(dtype)
            band[:, :NODATA_COLUMNS] = nodata
            dst.write(band, index)
    return Path(path)


def _item_grid(item: dict, size: int):
    """CRS, top-left origin and resolution of a synthetic grid at the centre of the item."""
    properties = item.get("properties", {})
    code = properties.get("proj:code") or (f"EPSG:{properties['proj:epsg']}" if properties.get("proj:epsg") else None)
    crs = CRS.from_user_input(code or "EPSG:4326")
    resolution = 10.0 if crs.is_projected else 0.0001
    bbox = item.get("bbox")
    if bbox:
        # A 3D bbox is (xmin, ymin, zmin, xmax, ymax, zmax).
        xmin, ymin, xmax, ymax = (bbox[0], bbox[1], bbox[3], bbox[4]) if len(bbox) == 6 else bbox
        lon, lat = (xmin + xmax) / 2, (ymin + ymax) / 2
    else:
        lon, lat = -3.5, 51.6
    xs, ys = transform("EPSG:4326", crs, [lon], [lat])
    half = size * resolution / 2
    return crs, (xs[0] - half, ys[0] + half), resolution


def stage_item(
    item: dict,
    staged_dir: Path,
    values: Optional[Dict[str, float]] = None,
    asset_keys: Optional[Sequence[str]] = None,
    size: int = SIZE,
) -> Path:
    """
    Write a staged directory for `item`: `catalog.json` -> `<item_id>/<item_id>.json`, with a
    synthetic raster beside the item for each GeoTIFF asset (or each of `asset_keys`).

    Each band's value comes from `values` (or `DEFAULT_VALUES`) by its common name. Assets that
    are not GeoTIFFs are dropped. Returns `staged_dir`.
    """
    values = {**DEFAULT_VALUES, **(values or {})}
    item = copy.deepcopy(item)
    staged_dir = Path(staged_dir)
    item_dir = staged_dir / item["id"]
    item_dir.mkdir(parents=True, exist_ok=True)
    crs, origin, resolution = _item_grid(item, size)

    staged_assets = {}
    for key, asset in item.get("assets", {}).items():
        if (asset_keys is not None and key not in asset_keys) or not is_geotiff(asset):
            continue
        bands = asset_bands(asset) or [{}]
        band_values = [values.get(band_common_name(b) or key, 1000) for b in bands]
        write_synthetic_raster(item_dir / f"{key}.tif", band_values, crs, origin, resolution, size)
        staged_assets[key] = {**asset, "href": f"./{key}.tif"}
    if not staged_assets:
        raise ValueError(f"Item {item['id']!r} has no GeoTIFF assets to stage")
    item["assets"] = staged_assets
    item["links"] = []  # stage-in drops every item link

    (item_dir / f"{item['id']}.json").write_text(json.dumps(item, indent=2))
    catalog = {
        "type": "Catalog",
        "stac_version": "1.0.0",
        "id": "catalog",
        "description": "staged",
        "links": [{"rel": "item", "href": f"./{item['id']}/{item['id']}.json", "type": "application/json"}],
    }
    (staged_dir / "catalog.json").write_text(json.dumps(catalog, indent=2))
    logger.info(f"Staged item {item['id']!r} with assets {sorted(staged_assets)} in {staged_dir}")
    return staged_dir
