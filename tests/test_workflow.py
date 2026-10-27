"""Level 2: unit tests for run() in src/workflow.py."""

import numpy as np
import pytest
import rasterio

import workflow
from eodh_workflow import RasterAsset, WorkflowInputs, read_staged_item
from eodh_workflow.testing import DEFAULT_VALUES, NODATA_COLUMNS


def test_ndvi_formula():
    nir = np.array([3000.0, 0.0, 1000.0])
    red = np.array([500.0, 0.0, 3000.0])
    result = workflow.ndvi(nir, red)
    assert result[0] == pytest.approx(2500 / 3500)
    assert np.isnan(result[1])  # denominator 0
    assert result[2] == pytest.approx(-0.5)
    assert result.dtype == np.float32


def test_run_writes_ndvi_cog(staged, tmp_path, input_item):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    spec = workflow.run(WorkflowInputs(stac_item=read_staged_item(staged)), output_dir)

    assert spec.collection.renders["ndvi"]["rescale"] == [[-1, 1]]
    [item] = spec.items
    assert item.id == f"{input_item['id']}_ndvi"
    assert item.source_item.id == input_item["id"]
    asset = item.assets["data"]
    assert isinstance(asset, RasterAsset)

    with rasterio.open(asset.path) as src:
        assert src.dtypes[0] == "float32"
        data = src.read(1)
    assert np.isnan(data[:, :NODATA_COLUMNS]).all()
    nir, red = DEFAULT_VALUES["nir"], DEFAULT_VALUES["red"]
    assert data[0, NODATA_COLUMNS] == pytest.approx((nir - red) / (nir + red), abs=0.01)
