"""
Level 3: run the real entrypoint (src/main.py) on the staged fixture, then check the output
directory against every rule the Hub depends on.
"""

import pystac

import main
from eodh_workflow import output_problems


def _run(staged, output_dir):
    main.main([f"--stac_item_dir={staged}", f"--output_dir={output_dir}"])
    assert output_problems(output_dir) == []
    catalog = pystac.Catalog.from_file(str(output_dir / "catalog.json"))
    return catalog, next(catalog.get_children())


def test_output_is_valid_and_renderable(staged, tmp_path, input_item):
    _, collection = _run(staged, tmp_path / "out")
    item = next(collection.get_items())
    assert item.properties["eodh:source_item_id"] == input_item["id"]
    assert item.properties["renders"] == collection.extra_fields["renders"]


def test_each_run_gets_its_own_collection(staged, tmp_path):
    first_catalog, first = _run(staged, tmp_path / "first")
    second_catalog, second = _run(staged, tmp_path / "second")
    assert first_catalog.id == second_catalog.id
    assert first.id != second.id
