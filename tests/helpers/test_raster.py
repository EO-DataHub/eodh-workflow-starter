import numpy as np
import pytest
import rasterio

from eodh_workflow import read_staged_item, write_cog_chunked
from eodh_workflow.testing import write_synthetic_raster


def _difference(a, b):
    return (a - b).astype("float32")


@pytest.mark.parametrize("bbox", [None, (-5.45, 57.20, -5.40, 57.23)])
def test_chunked_output_matches_single_chunk(staged, tmp_path, bbox):
    """Chunk offsets are where a windowed loop goes wrong, so compare against a one-chunk run."""
    item = read_staged_item(staged)
    bands = [item.band("nir"), item.band("red")]
    outputs = []
    for name, chunk_size in [("single", (4096, 4096)), ("chunked", (100, 100))]:
        path = write_cog_chunked(bands, tmp_path / f"{name}.tif", _difference, bbox=bbox, chunk_size=chunk_size)
        with rasterio.open(path) as src:
            outputs.append(src.read(1))
    np.testing.assert_array_equal(outputs[0], outputs[1])
    assert not list(tmp_path.glob("*.tmp.tif"))


def test_mismatched_input_grids_are_rejected(tmp_path):
    a = write_synthetic_raster(tmp_path / "a.tif", [500])
    b = write_synthetic_raster(tmp_path / "b.tif", [500], origin=(455010.0, 5722000.0))
    with pytest.raises(ValueError, match="matching transforms"):
        write_cog_chunked([(a, 1), (b, 1)], tmp_path / "out.tif", _difference)
