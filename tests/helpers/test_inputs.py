import copy

import pytest

from eodh_workflow import read_staged_item
from eodh_workflow.testing import stage_item


def test_band_prefers_single_band_asset(staged):
    item = read_staged_item(staged)
    red = item.band("red")
    # `visual` also has a red band; the single-band `red` asset wins.
    assert red.path.name == "red.tif"
    assert red.index == 1


def test_band_in_multi_band_asset(tmp_path, input_item):
    item = copy.deepcopy(input_item)
    item["assets"] = {"cog": item["assets"]["visual"]}
    staged = read_staged_item(stage_item(item, tmp_path / "staged"))
    band = staged.band("blue")
    assert band.path.name == "cog.tif"
    assert band.index == 3


def test_missing_band_lists_common_names(staged):
    with pytest.raises(KeyError, match="'nir'"):
        read_staged_item(staged).band("swir16")


def test_more_than_one_item_is_refused(staged):
    catalog = staged / "catalog.json"
    catalog.write_text(catalog.read_text().replace('"links": [', '"links": [{"rel": "item", "href": "x.json"}, '))
    with pytest.raises(ValueError, match="takes one"):
        read_staged_item(staged)
