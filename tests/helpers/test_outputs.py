import json
import math

import numpy as np
import pystac
import pytest
from rasterio.transform import from_origin

from eodh_workflow import (
    CollectionSpec,
    FileAsset,
    ItemSpec,
    OutputError,
    RasterAsset,
    output_problems,
    read_staged_item,
    write_cog,
    write_outputs,
)
from eodh_workflow.testing import write_synthetic_raster

RENDERS = {"grey": {"title": "Grey", "assets": ["data"], "rescale": [[0, 1]], "colormap_name": "greys"}}
CRS = "EPSG:32630"


def _cog(path, value=0.5, origin=(455000.0, 5722000.0)):
    data = np.full((600, 600), value, dtype="float32")
    data[:, :10] = np.nan
    return write_cog(path, data, CRS, from_origin(*origin, 10, 10), nodata=float("nan"))


def _collection(**kwargs):
    return CollectionSpec(**{"id": "demo", "title": "Demo", "description": "Demo output", "renders": RENDERS, **kwargs})


def _load(output_dir):
    catalog = pystac.Catalog.from_file(str(output_dir / "catalog.json"))
    collection = next(catalog.get_children())
    return catalog, collection, sorted(collection.get_items(), key=lambda i: i.id)


def test_single_item_metadata(tmp_path, staged, input_item):
    tmp_path = tmp_path / "out"
    tmp_path.mkdir()
    source = read_staged_item(staged)
    cog = _cog(tmp_path / "a.tif")
    write_outputs(
        tmp_path,
        _collection(keywords=["demo"]),
        [ItemSpec("a", {"data": RasterAsset(cog, bands=[{"name": "value"}])}, source_item=source)],
    )
    assert output_problems(tmp_path) == []
    catalog, collection, [item] = _load(tmp_path)

    assert catalog.id == "demo"
    assert collection.id.startswith("demo-")
    raw_item = json.loads((tmp_path / collection.id / "a" / "a.json").read_text())
    properties = raw_item["properties"]
    assert raw_item["stac_version"] == "1.1.0"
    assert properties["datetime"] == input_item["properties"]["datetime"]
    assert properties["platform"] == input_item["properties"]["platform"]
    assert properties["eodh:source_item_id"] == input_item["id"]
    assert properties["proj:code"] == CRS
    assert properties["gsd"] == 10
    assert properties["renders"] == RENDERS

    asset = raw_item["assets"]["data"]
    assert asset["href"] == "../../a.tif"
    assert asset["type"] == pystac.MediaType.COG
    assert asset["roles"] == ["data"]
    [band] = asset["bands"]
    assert band["name"] == "value"
    assert band["data_type"] == "float32"
    assert band["nodata"] == "nan"
    assert band["statistics"]["minimum"] == pytest.approx(0.5)

    raw_collection = json.loads((tmp_path / collection.id / "collection.json").read_text())
    assert raw_collection["renders"] == RENDERS
    assert "statistics" not in raw_collection["item_assets"]["data"]["bands"][0]
    assert collection.extent.spatial.bboxes[0] == item.bbox
    assert collection.license == "other"


def test_several_items_and_a_file_asset(tmp_path):
    a = _cog(tmp_path / "a.tif")
    b = _cog(tmp_path / "b.tif", origin=(470000.0, 5722000.0))
    csv = tmp_path / "stats.csv"
    csv.write_text("mean\n0.5\n")
    write_outputs(
        tmp_path,
        _collection(),
        [
            ItemSpec("a", {"data": RasterAsset(a), "stats": FileAsset(csv, "text/csv")}),
            ItemSpec("b", {"data": RasterAsset(b)}),
        ],
    )
    assert output_problems(tmp_path) == []
    _, collection, items = _load(tmp_path)
    assert [i.id for i in items] == ["a", "b"]
    extent = collection.extent.spatial.bboxes[0]
    assert extent[0] == items[0].bbox[0] and extent[2] == items[1].bbox[2]
    assert items[0].assets["stats"].media_type == "text/csv"


def test_file_only_item_needs_geometry(tmp_path):
    csv = tmp_path / "stats.csv"
    csv.write_text("x\n")
    geometry = {"type": "Point", "coordinates": [-3.5, 51.6]}
    with pytest.raises(OutputError, match="geometry"):
        write_outputs(tmp_path, _collection(renders={}), [ItemSpec("a", {"table": FileAsset(csv, "text/csv")})])
    write_outputs(
        tmp_path, _collection(renders={}), [ItemSpec("a", {"table": FileAsset(csv, "text/csv")}, geometry=geometry)]
    )
    _, _, [item] = _load(tmp_path)
    assert item.bbox == [-3.5, 51.6, -3.5, 51.6]
    assert "renders" not in item.properties


@pytest.mark.parametrize(
    "renders, message",
    [
        ({}, "renders is empty"),
        ({"r": {"assets": ["data"], "colormap_name": "greys"}}, "has no 'rescale'"),
        ({"r": {"assets": ["missing"], "rescale": [[0, 1]]}}, "does not have"),
    ],
)
def test_bad_renders_are_refused(tmp_path, renders, message):
    cog = _cog(tmp_path / "a.tif")
    with pytest.raises(OutputError, match=message):
        write_outputs(tmp_path, _collection(renders=renders), [ItemSpec("a", {"data": RasterAsset(cog)})])
    assert not (tmp_path / "catalog.json").exists()


def test_non_cog_raster_is_refused(tmp_path):
    tif = write_synthetic_raster(tmp_path / "plain.tif", [1000], size=1100)
    with pytest.raises(OutputError, match="not a valid COG"):
        write_outputs(tmp_path, _collection(), [ItemSpec("a", {"data": RasterAsset(tif)})])


def test_asset_outside_output_dir_is_refused(tmp_path):
    cog = _cog(tmp_path / "a.tif")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    with pytest.raises(OutputError, match="not under the output directory"):
        write_outputs(output_dir, _collection(), [ItemSpec("a", {"data": RasterAsset(cog)})])


def test_stray_files_are_refused(tmp_path):
    cog = _cog(tmp_path / "a.tif")
    (tmp_path / "scratch.tmp").write_text("left behind")
    with pytest.raises(OutputError, match="scratch.tmp"):
        write_outputs(tmp_path, _collection(), [ItemSpec("a", {"data": RasterAsset(cog)})])


def test_customise_runs_before_validation(tmp_path):
    cog = _cog(tmp_path / "a.tif")

    def add_property(catalog):
        for item in catalog.get_items(recursive=True):
            item.properties["demo:note"] = "customised"

    write_outputs(tmp_path, _collection(), [ItemSpec("a", {"data": RasterAsset(cog)})], customise=add_property)
    _, _, [item] = _load(tmp_path)
    assert item.properties["demo:note"] == "customised"

    def break_renders(catalog):
        for item in catalog.get_items(recursive=True):
            item.properties["renders"]["grey"]["assets"] = ["gone"]

    out = tmp_path / "second"
    out.mkdir()
    with pytest.raises(OutputError, match="differ from the collection"):
        write_outputs(out, _collection(), [ItemSpec("a", {"data": RasterAsset(_cog(out / "a.tif"))})], break_renders)


def test_extra_properties_override(tmp_path):
    cog = _cog(tmp_path / "a.tif")
    write_outputs(
        tmp_path, _collection(), [ItemSpec("a", {"data": RasterAsset(cog)}, extra_properties={"demo:threshold": 0.3})]
    )
    _, _, [item] = _load(tmp_path)
    assert math.isclose(item.properties["demo:threshold"], 0.3)
