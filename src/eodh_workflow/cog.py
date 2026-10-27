"""
Cloud Optimised GeoTIFF output.

GDAL's COG driver cannot take windowed writes, so data is written to a tiled GTiff first and
then copied with the COG driver. `write_cog` does both for an array in memory. For images that
do not fit in memory, use `eodh_workflow.raster.write_cog_chunked`.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
import rasterio.shutil
import rasterio.windows
from rasterio.crs import CRS
from rasterio.transform import Affine

logger = logging.getLogger(__name__)


def output_profile(src, process_window, count: int, dtype: Optional[str], nodata) -> dict:
    """
    Tiled GTiff profile for an intermediate output on the grid of `process_window` in `src`.

    `dtype=None` keeps the source dtype and nodata; otherwise `nodata` is used.
    """
    profile = src.profile.copy()
    profile.update(
        {
            "driver": "GTiff",
            "height": process_window.height,
            "width": process_window.width,
            "transform": rasterio.windows.transform(process_window, src.transform),
            "count": count,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "compress": "deflate",
            "zlevel": 1,
            "bigtiff": "IF_SAFER",
        }
    )
    # Source-specific encoding settings; the final COG sets its own.
    for key in ("photometric", "predictor"):
        profile.pop(key, None)
    if dtype is not None:
        profile["dtype"] = dtype
        profile["nodata"] = nodata
    return profile


def temp_path_for(output_cog: Path) -> Path:
    """Path of the intermediate GTiff, next to the output so it is on the same volume."""
    output_cog = Path(output_cog)
    return output_cog.with_name(f"{output_cog.stem}.tmp.tif")


def cog_from_gtiff(temp_path: Path, output_cog: Path, overview_resampling: str = "average") -> None:
    """
    Copy a GTiff to a COG with internal overviews, then delete the GTiff.

    Use `average` overview resampling for continuous data and `nearest` for classes or masks.
    """
    try:
        rasterio.shutil.copy(
            str(temp_path),
            str(output_cog),
            driver="COG",
            COMPRESS="DEFLATE",
            PREDICTOR="YES",
            BLOCKSIZE=512,
            OVERVIEWS="AUTO",
            RESAMPLING=overview_resampling.upper(),
            BIGTIFF="IF_SAFER",
        )
        logger.info(f"Wrote COG {output_cog} (overview resampling: {overview_resampling})")
    finally:
        Path(temp_path).unlink(missing_ok=True)


def write_cog(
    output_cog: Path,
    data: np.ndarray,
    crs,
    transform: Affine,
    nodata=None,
    overview_resampling: str = "average",
) -> Path:
    """
    Write an array as a COG. `data` is (height, width) or (bands, height, width).

    For float data, use `nodata=float("nan")` and set invalid pixels to NaN.
    """
    output_cog = Path(output_cog)
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    count, height, width = data.shape
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": count,
        "dtype": data.dtype.name,
        "crs": CRS.from_user_input(crs),
        "transform": transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "deflate",
        "bigtiff": "IF_SAFER",
    }
    temp_path = temp_path_for(output_cog)
    with rasterio.open(temp_path, "w", **profile) as dst:
        dst.write(data)
    cog_from_gtiff(temp_path, output_cog, overview_resampling)
    return output_cog
