"""
Example workflow: NDVI from the red and nir bands of one staged STAC item.

Replace this file with your own code. Keep the `run(inputs, output_dir) -> OutputSpec` signature.
"""

from pathlib import Path

import numpy as np

from eodh_workflow import CollectionSpec, ItemSpec, OutputSpec, RasterAsset, WorkflowInputs, write_cog_chunked

RENDERS = {
    "ndvi": {
        "title": "NDVI",
        "assets": ["data"],
        "rescale": [[-1, 1]],
        "colormap_name": "rdylgn",
        "resampling": "average",
    }
}


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """(NIR - Red) / (NIR + Red), NaN where the denominator is 0."""
    denominator = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denominator != 0, (nir - red) / denominator, np.nan)
    return np.clip(result, -1, 1).astype("float32")


def run(inputs: WorkflowInputs, output_dir: Path) -> OutputSpec:
    item = inputs.stac_item
    item_id = f"{item.id}_ndvi"
    cog = output_dir / f"{item_id}.tif"
    # Reads in chunks sized to the container's memory limit; NaN wherever an input pixel is nodata.
    write_cog_chunked([item.band("nir"), item.band("red")], cog, ndvi)

    return OutputSpec(
        collection=CollectionSpec(
            id="ndvi",
            title="NDVI",
            description="Normalised Difference Vegetation Index, (NIR - Red) / (NIR + Red), in [-1, 1].",
            keywords=["ndvi", "vegetation"],
            renders=RENDERS,
        ),
        items=[ItemSpec(id=item_id, source_item=item, assets={"data": RasterAsset(cog, bands=[{"name": "ndvi"}])})],
    )
