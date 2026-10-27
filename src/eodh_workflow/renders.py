"""
STAC render extension helpers, for outputs whose renders are not known in advance.

A render tells the tiler which asset and bands to show, how to stretch them (`rescale`) and
which colour map to use. See https://github.com/stac-extensions/render.
"""

import copy
import logging
from typing import Dict, List, Optional, Sequence

import numpy as np
import rasterio

logger = logging.getLogger(__name__)

DEFAULT_ASSET_KEY = "data"
# Longest side, in pixels, of the decimated read used to estimate a percentile stretch.
_STRETCH_SAMPLE_SIZE = 1024


def remap_source_renders(
    source_renders: Optional[dict], source_asset_key: str, output_asset_key: str = DEFAULT_ASSET_KEY
) -> Dict[str, dict]:
    """
    Copy the source renders that only use `source_asset_key`, pointing them at `output_asset_key`.

    Renders that reference any other asset are dropped: the output only carries the one asset.
    """
    remapped = {}
    for render_id, render in (source_renders or {}).items():
        if not isinstance(render, dict) or render.get("assets") != [source_asset_key]:
            continue
        render = copy.deepcopy(render)
        render["assets"] = [output_asset_key]
        if isinstance(render.get("expression"), str):
            render["expression"] = render["expression"].replace(f"{source_asset_key}_", f"{output_asset_key}_")
        remapped[render_id] = render
    if source_renders and not remapped:
        logger.info(f"No source renders use only asset {source_asset_key!r}; none copied")
    return remapped


def _percentile_rescale(src, bidx: int) -> List[float]:
    """2nd-98th percentile of the valid pixels of a band, read from a decimated overview."""
    scale = max(src.width, src.height) / _STRETCH_SAMPLE_SIZE
    out_shape = (max(1, int(src.height / max(scale, 1))), max(1, int(src.width / max(scale, 1))))
    data = src.read(bidx, out_shape=out_shape, masked=True).astype("float64")
    valid = data.compressed()
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return [0.0, 1.0]
    low, high = (float(v) for v in np.percentile(valid, [2, 98]))
    if high <= low:
        high = low + 1
    return [round(low, 6), round(high, 6)]


def fallback_render(
    cog_path, common_names: Sequence[Optional[str]] = (), asset_key: str = DEFAULT_ASSET_KEY
) -> Dict[str, dict]:
    """
    Build a render from a COG itself, for when you have no fixed render and no source render to copy.

    `common_names` gives each output band's common name (or None), in band order. Uses the
    red/green/blue bands when all three exist, otherwise band 1 in greyscale. Every render gets
    an explicit per-band percentile `rescale`.
    """
    band_by_common_name = {}
    for index, common_name in enumerate(common_names, start=1):
        if common_name and common_name not in band_by_common_name:
            band_by_common_name[common_name] = index

    with rasterio.open(str(cog_path)) as src:
        if all(name in band_by_common_name for name in ("red", "green", "blue")):
            bidx = [band_by_common_name[name] for name in ("red", "green", "blue")]
            return {
                "true-colour": {
                    "title": "True colour",
                    "assets": [asset_key],
                    "bidx": bidx,
                    "rescale": [_percentile_rescale(src, b) for b in bidx],
                }
            }
        return {
            "greyscale": {
                "title": "Band 1",
                "assets": [asset_key],
                "bidx": [1],
                "rescale": [_percentile_rescale(src, 1)],
            }
        }
