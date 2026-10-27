"""
Offline checks of a workflow output directory: the rules the Hub depends on to publish and
render the outputs. `write_outputs` runs them after it writes; the tests and `make check-docker`
run them on outputs from the real entrypoint.

    python -m eodh_workflow validate <output_dir>
"""

import json
import logging
import math
import re
from pathlib import Path
from typing import List, Sequence

import pystac
from pystac.validation import JsonSchemaSTACValidator
from rio_cogeo.cogeo import cog_validate

logger = logging.getLogger(__name__)

SCHEMAS = Path(__file__).parent / "schemas"
EXTENSION_SCHEMAS = {
    "https://stac-extensions.github.io/render/v2.1.0/schema.json": "render-v2.1.0.json",
    "https://stac-extensions.github.io/projection/v2.0.0/schema.json": "projection-v2.0.0.json",
    "https://stac-extensions.github.io/eo/v2.0.0/schema.json": "eo-v2.0.0.json",
}
RUN_SUFFIX = re.compile(r"-\d{8}T\d{6}-[0-9a-f]{6}$")


class OutputError(ValueError):
    """The output spec breaks a rule the Hub depends on. The message lists every problem."""

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        super().__init__("Invalid workflow output:\n" + "\n".join(f"- {p}" for p in self.problems))


class OfflineValidator(JsonSchemaSTACValidator):
    """pystac validator that only uses pystac's bundled core schemas and the schemas in `schemas/`."""

    def __init__(self):
        super().__init__()
        for uri, filename in EXTENSION_SCHEMAS.items():
            self.schema_cache[uri] = json.loads((SCHEMAS / filename).read_text())

    def _get_schema(self, schema_uri: str) -> dict:
        if schema_uri not in self.schema_cache:
            raise pystac.STACValidationError(
                f"No bundled schema for {schema_uri}. Use only the extensions in eodh_workflow/schemas/, "
                "or remove the extension."
            )
        return self.schema_cache[schema_uri]


def cog_problems(path: Path) -> List[str]:
    """Why `path` is not a COG the tiler can read efficiently. Missing overviews count as a problem."""
    is_valid, errors, warnings = cog_validate(str(path), quiet=True)
    problems = list(errors)
    problems += [w for w in warnings if "overview" in w.lower()]
    return problems if (problems or not is_valid) else []


def _validate_schemas(catalog: pystac.Catalog) -> List[str]:
    previous = pystac.validation.RegisteredValidator.get_validator()
    pystac.validation.set_validator(OfflineValidator())
    try:
        catalog.validate_all()
        return []
    except pystac.STACValidationError as e:
        return [f"STAC schema validation failed: {e}"]
    finally:
        pystac.validation.set_validator(previous)


def _bbox_close(a, b) -> bool:
    return len(a) == len(b) and all(math.isclose(x, y, abs_tol=1e-6) for x, y in zip(a, b))


def output_problems(output_dir: Path) -> List[str]:
    """Every rule the output directory breaks. An empty list means the output is valid."""
    output_dir = Path(output_dir).resolve()
    catalog_path = output_dir / "catalog.json"
    if not catalog_path.exists():
        return [f"No catalog.json at the root of {output_dir}"]

    catalog = pystac.Catalog.from_file(str(catalog_path))
    problems = _validate_schemas(catalog)

    if list(catalog.get_items()):
        problems.append("Items must be inside the collection, not directly under the catalog")
    collections = list(catalog.get_children())
    if len(collections) != 1 or not isinstance(collections[0], pystac.Collection):
        return problems + [f"The catalog must have exactly one child collection; found {len(collections)} children"]
    collection = collections[0]
    if not RUN_SUFFIX.search(collection.id):
        problems.append(
            f"Collection ID {collection.id!r} is not unique per run. Stage-out writes every run under the same "
            "catalog folder, so a fixed collection ID makes runs overwrite each other."
        )

    raw_collection = json.loads((output_dir / collection.id / "collection.json").read_text())
    collection_renders = raw_collection.get("renders") or {}
    expected_files = {catalog_path, output_dir / collection.id / "collection.json"}

    items = list(collection.get_items())
    if not items:
        problems.append("The collection has no items")
    item_bboxes = []
    for item in items:
        item_path = output_dir / collection.id / item.id / f"{item.id}.json"
        if not item_path.exists():
            problems.append(f"Item {item.id!r} is not at {item_path.relative_to(output_dir)}")
            continue
        expected_files.add(item_path)
        raw_item = json.loads(item_path.read_text())
        item_bboxes.append(item.bbox)

        has_cog = False
        for key, asset in raw_item.get("assets", {}).items():
            href = asset.get("href", "")
            if "://" in href or href.startswith("/"):
                problems.append(f"Asset {key!r} of item {item.id!r} has a non-relative href {href!r}")
                continue
            path = (item_path.parent / href).resolve()
            if not path.is_relative_to(output_dir):
                problems.append(f"Asset {key!r} of item {item.id!r} points outside the output directory: {href}")
                continue
            if not path.exists():
                problems.append(f"Asset {key!r} of item {item.id!r} points at a missing file: {href}")
                continue
            expected_files.add(path)
            if asset.get("type") == pystac.MediaType.COG:
                has_cog = True
                errors = cog_problems(path)
                if errors:
                    problems.append(f"Asset {key!r} of item {item.id!r} is not a valid COG: {'; '.join(errors)}")

        renders = raw_item.get("properties", {}).get("renders") or {}
        if has_cog and not renders:
            problems.append(f"Item {item.id!r} has COG assets but no renders")
        if renders != collection_renders:
            problems.append(f"Renders on item {item.id!r} differ from the collection renders")
        for render_id, render in renders.items():
            if not render.get("rescale"):
                problems.append(f"Render {render_id!r} on item {item.id!r} has no rescale")
            for key in render.get("assets") or []:
                if key not in raw_item.get("assets", {}):
                    problems.append(f"Render {render_id!r} on item {item.id!r} uses missing asset {key!r}")

    # Stage-out uses the collection as it is, so its extent must already cover the items.
    if item_bboxes:
        union = [
            min(b[0] for b in item_bboxes),
            min(b[1] for b in item_bboxes),
            max(b[2] for b in item_bboxes),
            max(b[3] for b in item_bboxes),
        ]
        if not _bbox_close(collection.extent.spatial.bboxes[0], union):
            problems.append(f"Collection spatial extent {collection.extent.spatial.bboxes[0]} does not match items")

    stray = sorted(
        str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file() and p not in expected_files
    )
    if stray:
        problems.append(
            f"Files in the output directory that no asset references: {stray}. Stage-out uploads everything; "
            "delete temporary files or add them as assets."
        )
    return problems


def assert_valid_output_dir(output_dir: Path) -> None:
    """Raise `OutputError` if the output directory breaks any rule."""
    problems = output_problems(output_dir)
    if problems:
        raise OutputError(problems)
