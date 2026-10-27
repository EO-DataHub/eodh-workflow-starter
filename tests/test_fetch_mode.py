"""
Fetch mode: the workflow has no stage-in input and fetches its own data from string inputs.
This shows the pattern from AGENTS.md, with the network fetch replaced by the staged fixture.
"""

import types

import pystac

import main
import workflow
from eodh_workflow import CollectionSpec, ItemSpec, OutputSpec, RasterAsset, output_problems, write_cog_chunked


def fetch_mode_run(inputs, output_dir):
    assert inputs.stac_item is None
    # In a real workflow this reads over the network; the CWL needs NetworkAccess.
    item = pystac.Item.from_file(inputs.params["item_url"])
    cog = output_dir / f"{item.id}_ndvi.tif"
    bands = [(item.assets[key].get_absolute_href(), 1) for key in ("nir", "red")]
    write_cog_chunked(bands, cog, workflow.ndvi)
    return OutputSpec(
        collection=CollectionSpec(id="ndvi", title="NDVI", description="NDVI", renders=workflow.RENDERS),
        # Set source_item whenever the data came from a STAC item, so its metadata is carried over.
        items=[ItemSpec(id=f"{item.id}_ndvi", source_item=item.to_dict(), assets={"data": RasterAsset(cog)})],
    )


def test_fetch_mode(staged, tmp_path, monkeypatch, input_item):
    staged_item_path = staged / input_item["id"] / f"{input_item['id']}.json"
    real_from_file = pystac.Item.from_file

    def fake_from_file(href, *args, **kwargs):
        assert href == "https://example.com/item.json"
        return real_from_file(str(staged_item_path))

    monkeypatch.setattr(pystac.Item, "from_file", fake_from_file)
    monkeypatch.setattr(main, "workflow", types.SimpleNamespace(run=fetch_mode_run))

    output_dir = tmp_path / "out"
    main.main([f"--output_dir={output_dir}", "--item_url=https://example.com/item.json"])

    assert output_problems(output_dir) == []
    item = next(pystac.Catalog.from_file(str(output_dir / "catalog.json")).get_items(recursive=True))
    assert item.properties["eodh:source_item_id"] == input_item["id"]
    assert item.properties["platform"] == input_item["properties"]["platform"]
